from artifactory_cleanup import rules
from artifactory_cleanup.rules import CleanupPolicy

RULES = [
    CleanupPolicy(
        'Feature Branches',
        rules.repo('davita-docker'),
        rules.delete_docker_images_not_used(days=30),
        rules.delete_docker_image_if_value_in_property('docker.label.branch', ['develop','future-develop','unicorn-develop'], False)
        ## PROTECTED BRANCHES: develop, unicorn-develop, future-develop, bugfix/RELEASE*
    ),
    CleanupPolicy(
        'Protected Branches',
        rules.repo('davita-docker'),
        rules.delete_docker_images_not_used(days=365),
        rules.delete_docker_image_if_value_in_property('docker.label.branch', ['develop','future-develop','unicorn-develop'], True)
    )
]
