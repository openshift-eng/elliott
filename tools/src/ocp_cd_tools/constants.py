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

# For Bugzilla searches
BUGZILLA_SERVER = "bugzilla.redhat.com"
DEFAULT_VERSIONS = (
    "3.0.0",
    "3.1.0", "3.1.1",
    "3.2.0", "3.2.1",
    "3.3.0", "3.3.1",
    "3.4.0", "3.4.1",
    "3.5.0", "3.5.1",
    "3.6.0", "3.6.1",
    "3.7.0", "3.7.1",
    "3.8.0", "3.8.1",
    "3.9.0", "3.9.1",
    "3.10.0", "3.10.1",
    "3.11.0", "3.11.1",
    "unspecified"
)
VALID_BUG_STATES = ['NEW', 'ASSIGNED', 'POST', 'MODIFED', 'ON_QA', 'VERIFIED', 'RELEASE_PENDING', 'CLOSED']

errata_url = "https://errata.devel.redhat.com"
bugzilla_query_url = 'https://bugzilla.redhat.com/buglist.cgi?bug_status=MODIFIED&classification=Red%20Hat&f1=component&f2=component&f3=component&f4=cf_verified&keywords=UpcomingRelease&keywords_type=nowords&known_name=All%203.x%20MODIFIED%20Bugs&list_id=8111122&o1=notequals&o2=notequals&o3=notequals&o4=notequals&product=OpenShift%20Container%20Platform&query_format=advanced&short_desc=%5C%5Bfork%5C%5D&short_desc_type=notregexp&{0}&v1=RFE&v2=Documentation&v3=Security&v4=FailedQA&version=3.0.0&version=3.1.0&version=3.1.1&version=3.2.0&version=3.2.1&version=3.3.0&version=3.3.1&version=3.4.0&version=3.4.1&version=3.5.0&version=3.5.1&version=3.6.0&version=3.6.1&version=3.7.0&version=3.7.1&version=3.8.0&version=3.8.1&version=3.9.0&version=3.9.1&version=3.10.0&version=3.10.1&version=3.11.0&version=3.11.1&version=unspecified'

# For new errata
errata_solution = """Before applying this update, make sure all previously released errata relevant to your system have been applied.

For OpenShift Container Platform 3.{Y} see the following documentation, which will be updated shortly for release 3.{Y}.z, for important instructions on how to upgrade your cluster and fully apply this asynchronous errata update:

https://docs.openshift.com/container-platform/3.{Y}/release_notes/ocp_3_{Y}_release_notes.html

This update is available via the Red Hat Network. Details on how to use the Red Hat Network to apply this update are available at https://access.redhat.com/articles/11258."""
errata_description = """Red Hat OpenShift Container Platform is Red Hat's cloud computing Kubernetes application platform solution designed for on-premise or private cloud deployments.

This advisory contains the RPM packages for Red Hat OpenShift Container Platform 3.{Y}.z. See the following advisory for the container images for this release:

https://access.redhat.com/errata/RHBA-2018:0114

Space precludes documenting all of the bug fixes and enhancements in this advisory. See the following Release Notes documentation, which will be updated shortly for this release, for details about these changes:

https://docs.openshift.com/container-platform/3.{Y}/release_notes/ocp_3_{Y}_release_notes.html

All OpenShift Container Platform 3.{Y} users are advised to upgrade to these updated packages and images."""

# QE Group name
errata_quality_responsibility_name = 'OpenShift QE'
errata_synopsis = {
    'rpm': 'OpenShift Container Platform 3.{Y} bug fix and enhancement update',
    'image': 'OpenShift Container Platform 3.{Y} images update'
}
errata_topic = 'Red Hat OpenShift Container Platform releases 3.{Y}.z are now available with updates to packages and images that fix several bugs and add enhancements.'
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
    'product': 'RHOSE',
    'release': 'RHOSE ASYNC',
    'advisory': {
        'assigned_to_email': None,  # Provided as input
        'description': errata_description,
        'errata_type': 'RHBA',
        'idsfixed': '',
        'manager_email': None,  # Provided as input
        'package_owner_email': None,  # Provided as input
        'publish_date_override': None,
        'quality_responsibility_name': errata_quality_responsibility_name,
        'security_impact': 'None',
        'solution': errata_solution,
        'synopsis': None,
        'topic': errata_topic,
    }
}
######################################################################
# We ship updates for various architectures. Images are
# architecture-agnostic
errata_shipped_arches = {
    'rpm': ['--arch=x86_64', '--arch=noarch'],
    'image': [''],
}
# Do not include these in tag results (carried over legacy behavior
# from update-errata-with-diffs.sh
errata_package_excludes = ["cockpit", "atomic-openshift-clients-redistributable",
                           "python-jsonschema", "python-ruamel-yaml", "python-wheel",
                           "python-typing", "python-ruamel-ordereddict", "ansible"]

bugzilla_invalid_transition_comment = """There is a potential issue with this bug that may prevent it from being processed by our automation.

For more information on proper bug management visit:
https://mojo.redhat.com/docs/DOC-1178565#jive_content_id_How_do_I_get_my_Bugzilla_Bug_to_VERIFIED
"""

DISTGIT_MAX_FILESIZE = 50000000
