from artifactory_cleanup import rules
from artifactory_cleanup.rules import CleanupPolicy

RULES = [
    # CleanupPolicy(
    #     'Delete all images that have not been used in 365 days from davita-docker exclude latest, release',
    #     rules.repo('test-docker'),
    #     rules.exclude_docker_images(['*:latest', '*:release*']),
    #     rules.delete_docker_images_not_used(days=365),
    # ),
    CleanupPolicy(
        'Testing Cleanup Policies',
        rules.repo('test-docker'),
        # rules.exclude_docker_images(['*:latest', '*:release*']),
        rules.delete_docker_images_not_used(days=30),
        rules.delete_docker_image_if_not_value_in_property('docker.label.branch', ['develop','future-develop','unicorn-develop'])
        # rules.delete_docker_image_if_not_value_in_property('davita-docker', 'docker.label.branch', ['develop','future-develop'])
        # rules.property_neq('docker.label.branch','develop'),
        # rules.property_neq('docker.label.branch','future-develop'),
        # rules.property_neq('docker.label.branch','unicorn-develop')

        ## PROTECTED BRANCHES: develop, unicorn-develop, future-develop, bugfix/RELEASE*
    ),
]
