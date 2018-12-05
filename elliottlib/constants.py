"""
This file contains constants that are used to manage OCP Image and RPM builds
"""

# config data pulled from here
OCP_BUILD_DATA_RO = "https://github.com/openshift/ocp-build-data"
# above is used so that anyone can clone
OCP_BUILD_DATA_RW = "git@github.com:openshift/ocp-build-data.git"

BREW_HUB = "https://brewhub.engineering.redhat.com/brewhub"
BREW_IMAGE_HOST = "brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888"
CGIT_URL = "http://pkgs.devel.redhat.com/cgit"

VALID_BUG_STATES = ['NEW', 'ASSIGNED', 'POST', 'MODIFIED', 'ON_QA', 'VERIFIED', 'RELEASE_PENDING', 'CLOSED']

errata_url = "https://errata.devel.redhat.com"

# 1965 => (RHBA; Active; Product: RHOSE; Devel Group: ENG OpenShift
#          Enterprise; sorted by newest)
# https://errata.devel.redhat.com/filter/1965
errata_default_filter = '1965'
# 1991 => (Active; Product: RHOSE; Devel Group: ENG OpenShift
#          Enterprise; sorted by newest)
# https://errata.devel.redhat.com/filter/1991
errata_live_advisory_filter = '1991'
# 2051 => (RHBA; State REL PREP, PUSH READY, IN PUSH, SHIPPED;
#          Product: RHOSE; Devel Group: ENG OpenShift Enterprise;
#          sorted by newest)
# https://errata.devel.redhat.com/filter/2051
errata_immutable_advisory_filter = '2051'

errata_active_advisory_labels = [
    "NEW_FILES",
    "QE",
    "REL_PREP",
    "PUSH_READY",
    "IN_PUSH"
]

errata_inactive_advisory_labels = [
    "SHIPPED_LIVE",
    "DROPPED_NO_SHIP"
]

errata_valid_impetus = [
    'standard',
    'cve',
    'ga',
    'test'
]

######################################################################
# API endpoints with string formatting placeholders as
# necessary. Index of all available endpoints is available in the
# online documentation.
#
# https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-index-by-url
errata_add_bug_url = errata_url + "/api/v1/erratum/{id}/add_bug"
errata_add_build_url = errata_url + "/api/v1/erratum/{id}/add_build"
errata_add_builds_url = errata_url + "/api/v1/erratum/{id}/add_builds"
errata_add_comment_url = errata_url + "/api/v1/erratum/{id}/add_comment"
errata_bug_refresh_url = errata_url + "/api/v1/bug/refresh"
errata_change_state_url = errata_url + "/api/v1/erratum/{id}/change_state"
errata_filter_list_url = errata_url + "/filter/{id}.json"
errata_get_build_url = errata_url + "/api/v1/build/{id}"
errata_get_builds_url = errata_url + "/api/v1/erratum/{id}/builds"
errata_get_comment_url = errata_url + "/api/v1/comments/{id}"
errata_get_comments_url = errata_url + "/api/v1/comments"
errata_get_erratum_url = errata_url + "/api/v1/erratum/{id}"
errata_post_erratum_url = errata_url + "/api/v1/erratum"

######################################################################
# Scaffolding for creating a new advisory. See the online
# documentation for a description of all allowed fields, including
# which are required and which are optional
#
# https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-post-apiv1erratum
errata_new_object = {
    'product': None,
    'release': None,
    'advisory': {
        'assigned_to_email': None,  # Provided as input
        'description': None,
        'errata_type': 'RHBA',
        'idsfixed': '',
        'manager_email': None,  # Provided as input
        'package_owner_email': None,  # Provided as input
        'publish_date_override': None,
        'quality_responsibility_name': None,
        'security_impact': 'None',
        'solution': None,
        'synopsis': None,
        'topic': None,
    }
}

bugzilla_invalid_transition_comment = """There is a potential issue with this bug that may prevent it from being processed by our automation.

For more information on proper bug management visit:
https://mojo.redhat.com/docs/DOC-1178565#jive_content_id_How_do_I_get_my_Bugzilla_Bug_to_VERIFIED
"""

DISTGIT_MAX_FILESIZE = 50000000
