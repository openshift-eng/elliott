"""
This file contains constants that are used to manage OCP Image and RPM builds
"""

BREW_HUB = "https://brewhub.engineering.redhat.com/brewhub"
CGIT_URL = "http://pkgs.devel.redhat.com/cgit"

VALID_BUG_STATES = ['NEW', 'ASSIGNED', 'POST', 'MODIFIED', 'ON_QA', 'VERIFIED', 'RELEASE_PENDING', 'CLOSED']

BUG_SEVERITY_NUMBER_MAP = {
    "unspecified": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "urgent": 4,
}

# When severity isn't set on all tracking and flaw bugs, default to "Low"
# https://jira.coreos.com/browse/ART-1192
SECURITY_IMPACT = ["Low", "Low", "Moderate", "Important", "Critical"]

errata_url = "https://errata.devel.redhat.com"

# 1965 => (RHBA; Active; Product: RHOSE; Devel Group: ENG OpenShift
#          Enterprise; sorted by newest)
# https://errata.devel.redhat.com/filter/1965
errata_default_filter = '1965'
# 1991 => (Active; Product: RHOSE; Devel Group: ENG OpenShift
#          Enterprise; sorted by newest)
# https://errata.devel.redhat.com/filter/1991
errata_live_advisory_filter = '1991'
# https://errata.devel.redhat.com/filter/2507
errata_puddle_advisory_filter = '2507'
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
    'test',
    'extras',
    'metadata',
]

# These are the types of advisories that may have definitions in group.yml
# TODO: this should probably be user-definable in some way
standard_advisory_types = [
    'rpm',
    'image',
    'extras',
    'metadata',
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
errata_get_advisories_for_bug_url = errata_url + "/bugs/{id}/advisories.json"

DISTGIT_MAX_FILESIZE = 50000000
