import re
from collections import defaultdict
from datetime import date, timedelta

from artifactory import ArtifactoryPath
from teamcity.messages import TeamcityServiceMessages

from artifactory_cleanup.rules.base import Rule

TC = TeamcityServiceMessages()
docker_repos = defaultdict(lambda: defaultdict(int))


class RuleForDocker(Rule):
    """
    Parent class for Docker rules
    """

    def get_docker_images_list(self, docker_repo):
        _href = "{}/api/docker/{}/v2/_catalog".format(self.artifactory_server, docker_repo)
        r = self.artifactory_session.get(_href)
        r.raise_for_status()
        content = r.json()

        return content['repositories']

    def get_docker_tags_list(self, docker_repo, docker_image):
        _href = "{}/api/docker/{}/v2/{}/tags/list".format(self.artifactory_server, docker_repo, docker_image)
        r = self.artifactory_session.get(_href)
        r.raise_for_status()
        content = r.json()

        return content['tags']

    def _manifest_to_image(self, artifact):
        """
        Converts an artifact named "manifest.json" to the folder containing it and sets size to 0.
        """
        if artifact['name'] == 'manifest.json':
            artifact['size'] = 0
            artifact['path'], artifact['name'] = artifact['path'].rsplit('/', 1)

    def _collect_docker_size(self, new_result):
        TC.blockOpened('_collect_docker_size.')
        repos = list(set(x['repo'] for x in new_result))
        repo_args = []

        for repo in repos:
            if repo not in docker_repos:
                repo_args.append({
                    "repo": repo
                })

        if repo_args:
            aql = ArtifactoryPath(self.artifactory_server, session=self.artifactory_session)
            args = ['items.find', {"$or": repo_args}]

            artifacts_list = aql.aql(*args)

            for layer in artifacts_list:
                docker_repos[layer['repo']][layer['path']] += layer['size']

        for artifact in new_result:
            image = f"{artifact['path']}/{artifact['name']}"
            artifact['size'] = docker_repos[artifact['repo']][image]

        TC.blockClosed('_collect_docker_size.')

    def filter_result(self, result_artifacts):
        """ Determines the size of deleted images """
        new_result = super(RuleForDocker, self).filter_result(result_artifacts)
        self._collect_docker_size(new_result)

        return new_result


class delete_docker_images_older_than(RuleForDocker):
    """ Removes Docker image older than ``days`` days"""

    def __init__(self, *, days):
        self.days = timedelta(days=days)

    def _aql_add_filter(self, aql_query_list):
        today = date.today()
        older_than_date = today - self.days
        older_than_date_txt = older_than_date.isoformat()
        print('Delete docker images older than {}'.format(older_than_date_txt))
        update_dict = {
            "modified": {
                "$lt": older_than_date_txt,
            },
            "name": {
                "$match": 'manifest.json',
            }
        }
        aql_query_list.append(update_dict)
        return aql_query_list

    def _filter_result(self, result_artifact):
        for artifact in result_artifact:
            self._manifest_to_image(artifact)

        return result_artifact


class delete_docker_images_not_used(RuleForDocker):
    """ Removes Docker image not downloaded ``days`` days """

    def __init__(self, *, days):
        self.days = timedelta(days=days)

    def _aql_add_filter(self, aql_query_list):
        last_day = date.today() - self.days
        print('Delete docker images not used from {}'.format(last_day.isoformat()))
        update_dict = {
            "name": {
                "$match": 'manifest.json',
            },
            "$or": [
                {"stat.downloaded": {"$lte": last_day.isoformat()}},  # Скачивались давно
                {"$and": [
                    {"stat.downloads": {"$eq": None}},  # Не скачивались
                    {"created": {"$lte": last_day.isoformat()}
                     }]},
            ],
        }
        aql_query_list.append(update_dict)
        return aql_query_list

    def _filter_result(self, result_artifact):
        for artifact in result_artifact:
            self._manifest_to_image(artifact)

        return result_artifact


class keep_latest_n_version_images_by_property(Rule):
    r"""
    Leaves ``count`` Docker images with the same major.
    If you need to add minor then put 2 or if patch then put 3.

    :param custom_regexp: how to determine version.
    По умолчанию ``r'(^ \d*\.\d*\.\d*.\d+$)``. Ищет версию в ``properties`` файла ``manifest.json``
    """

    def __init__(self, count, custom_regexp=r'(^\d*\.\d*\.\d*.\d+$)', number_of_digits_in_version=1):
        self.count = count
        self.custom_regexp = custom_regexp
        self.property = r'docker.manifest'
        self.number_of_digits_in_version = number_of_digits_in_version

    def _filter_result(self, result_artifact):
        artifacts_by_path_and_name = defaultdict(list)
        for artifact in result_artifact[:]:
            property = artifact['properties'][self.property]
            version = re.findall(self.custom_regexp, property)
            if len(version) == 1:
                version_splitted = version[0].split('.')
                key = artifact['path'] + '/' + version_splitted[0]
                key += ".".join(version_splitted[:self.number_of_digits_in_version])
                artifacts_by_path_and_name[key].append([version_splitted[0], artifact])

        for artifactory_with_version in artifacts_by_path_and_name.values():
            artifactory_with_version.sort(key=lambda x: [int(x) for x in x[0].split('.')])

            good_artifact_count = len(artifactory_with_version) - self.count
            if good_artifact_count < 0:
                good_artifact_count = 0

            good_artifacts = artifactory_with_version[good_artifact_count:]
            for artifact in good_artifacts:
                self.remove_artifact(artifact[1], result_artifact)

        return result_artifact


class delete_docker_image_if_not_contained_in_properties(RuleForDocker):
    """
    .. warning::

        Multiscanner project specific rule https://wiki.ptsecurity.com/x/koFIAg

    Remove Docker image, if it is not found in the properties of the artifact repository.

    """

    def __init__(self, docker_repo, properties_prefix, image_prefix=None, full_docker_repo_name=None):
        self.docker_repo = docker_repo
        self.properties_prefix = properties_prefix
        self.image_prefix = image_prefix
        self.full_docker_repo_name = full_docker_repo_name

    def get_properties_dict(self, result_artifact):
        properties_dict = defaultdict(dict)

        for artifact in result_artifact:
            if artifact.get('properties'):
                properties_with_image = [x for x in artifact['properties'].keys()
                                         if x.startswith(self.properties_prefix)]

                for i in properties_with_image:
                    # Create a dictionary with a property key, without a prefix.
                    # Property = docker.image, prefix = docker. -> key = image
                    properties_dict[i[len(self.properties_prefix):]].setdefault(artifact['properties'][i], True)

        return properties_dict

    def _filter_result(self, result_artifact):
        images = self.get_docker_images_list(self.docker_repo)
        properties_dict = self.get_properties_dict(result_artifact)
        result_docker_images = []

        for image in images:
            # legacy
            image_legacy = None
            if self.image_prefix and image.startswith(self.image_prefix):
                # Remove the prefix from the image name
                image_legacy = image[len(self.image_prefix):]
            elif not self.image_prefix:
                continue

            if image in properties_dict.keys() or image_legacy in properties_dict.keys():
                tags = self.get_docker_tags_list(self.docker_repo, image)

                for tag in tags:
                    docker_name = '{}:{}'.format(image, tag)
                    docker_name_legacy = None
                    if self.full_docker_repo_name:
                        docker_name_legacy = '{}/{}'.format(self.full_docker_repo_name, docker_name)
                    # If this docker tag is not found in the metadata properties, then add it to the list for deletion
                    if not properties_dict[image].pop(docker_name, None) \
                            and not properties_dict[image_legacy].pop(docker_name, None) \
                            and not properties_dict[image_legacy].pop(docker_name_legacy, None):
                        result_docker_images.append({'repo': self.docker_repo,
                                                     'path': image,
                                                     'name': tag,
                                                     })

        return result_docker_images


class delete_docker_image_if_not_contained_in_properties_value(RuleForDocker):
    """
    Remove Docker image, if it is not found in the properties of the artifact repository

    .. warning::

        Multiscanner project specific rule https://wiki.ptsecurity.com/x/koFIAg

    """

    def __init__(self, docker_repo, properties_prefix, image_prefix=None, full_docker_repo_name=None):
        self.docker_repo = docker_repo
        self.properties_prefix = properties_prefix
        self.image_prefix = image_prefix
        self.full_docker_repo_name = full_docker_repo_name

    def get_properties_values(self, result_artifact):
        """ Creates a list of artifact property values if the value starts with self.properties_prefix"""
        properties_values = set()
        for artifact in result_artifact:
            properties_values |= set((artifact['properties'].get(x) for x in artifact.get('properties', {})
                                      if x.startswith(self.properties_prefix)))

        return properties_values

    def _filter_result(self, result_artifact):
        images = self.get_docker_images_list(self.docker_repo)
        properties_values = self.get_properties_values(result_artifact)
        result_docker_images = []

        for image in images:
            if not image.startswith(self.image_prefix):
                continue

            # For debag output all properties that begin as image
            values_with_image_name = [x for x in properties_values if x.startswith(image)]
            TC.blockOpened('Values of properties with name as image {}'.format(image))
            for value in values_with_image_name:
                print(value)
            TC.blockClosed('Values of properties with name as image {}'.format(image))

            tags = self.get_docker_tags_list(self.docker_repo, image)

            TC.blockOpened('Checking image {}'.format(image))
            for tag in tags:
                docker_name = '{}:{}'.format(image, tag)
                print('INFO - Checking docker with name {}'.format(docker_name))
                # If this Docker tag is not found in the metadata properties, then add it to the list for deletion
                if docker_name not in properties_values:
                    result_docker_images.append({'repo': self.docker_repo,
                                                 'path': image,
                                                 'name': tag,
                                                 })
            TC.blockClosed('Checking image {}'.format(image))

        return result_docker_images

class delete_docker_image_if_value_in_property(RuleForDocker):
    """ Removes Docker image if the property value is set or not (value_present)"""

    def __init__(self, property_key='docker.label.branch', property_values=[], property_values_regexp=None, regexp_flags=[re.IGNORECASE], value_present=True, delete_if_key_not_present=False):

        self.property_key = property_key
        self.property_values = property_values
        self.value_present = value_present
        self.delete_if_key_not_present = delete_if_key_not_present

        print('property_values_regexp: {}'.format(property_values_regexp))
        if property_values_regexp:
            self.property_values_pattern = re.compile(property_values_regexp, *regexp_flags)
            print('property_values_pattern: {}'.format(self.property_values_pattern))

        else:
            self.property_values_pattern = None

    def _aql_add_filter(self, aql_query_list):
        # TODO: Add this conditionally
        update_dict = {
            "name": {
                "$match": 'manifest.json',
            }
        }
        aql_query_list.append(update_dict)
        return aql_query_list

    def _filter_result(self, result_artifact):
        result_docker_images = []

        for artifact in result_artifact:
            properties = artifact.get('properties', {})
            val = properties.get(self.property_key)
            if val: # the property key was present as the val is not None
                if self.value_present: # If we want to find the values
                    if ((val in self.property_values) or (self.property_values_pattern and self.property_values_pattern.match(val))):
                        self._manifest_to_image(artifact)
                        result_docker_images.append(artifact)
                else: # self.value_present is false, we do not want to find the values
                    if ((not val in self.property_values) and (self.property_values_pattern and not self.property_values_pattern.match(val))):
                        self._manifest_to_image(artifact)
                        result_docker_images.append(artifact)
            else:
                if self.delete_if_key_not_present:
                    self._manifest_to_image(artifact)
                    result_docker_images.append(artifact)

        return result_docker_images
