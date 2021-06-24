from artifactory_cleanup import rules
from artifactory_cleanup.rules import CleanupPolicy

RULES = [
    CleanupPolicy(
        'Feature Branches',
        rules.repo('davita-docker'),
        rules.delete_docker_images_not_used(days=30),
        rules.delete_docker_image_if_value_in_property(
            property_key = 'docker.label.branch',
            property_values = ['develop','future-develop','unicorn-develop'],
            property_values_regexp = r'^BUGFIX/RELEASE.+',
            value_present = False
        )
        ## PROTECTED BRANCHES: develop, unicorn-develop, future-develop, bugfix/RELEASE*
    ),
    CleanupPolicy(
        'Protected Branches',
        rules.repo('davita-docker'),
        rules.delete_docker_images_not_used(days=365),
        rules.delete_docker_image_if_value_in_property(
            property_key = 'docker.label.branch',
            property_values = ['develop','future-develop','unicorn-develop'],
            property_values_regexp = r'^BUGFIX/RELEASE.+',
            value_present = True
        ),
    ),
    CleanupPolicy(
        'Unlabeled Images',
        rules.repo('davita-docker'),
        rules.delete_docker_images_not_used(days=365),
        rules.delete_docker_image_if_value_in_property(
            property_key = 'docker.label.branch',
            delete_if_key_not_present = True,
        ),
    ),
]
