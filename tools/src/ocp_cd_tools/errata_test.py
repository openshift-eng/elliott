"""
Test errata models/controllers
"""

import mock
import json
from contextlib import nested

# Import the right version for your python
import platform
(major, minor, patch) = platform.python_version_tuple()
if int(major) == 2 and int(minor) < 7:
    import unittest2 as unittest
else:
    import unittest

import ocp_cd_tools
import constants
import errata
import bugzilla
import brew

from requests_kerberos import HTTPKerberosAuth


class TestBrew(unittest.TestCase):

    def test_get_erratum_success(self):
        """Verify a 'good' erratum request is fulfilled"""
        with mock.patch('ocp_cd_tools.errata.requests.get') as get:
            # Create the requests.response object. The status code
            # here will change the path of execution to the not-found
            # branch of errata.get_erratum
            response = mock.MagicMock(status_code=200)
            # response's have a 'json' function that returns a dict of
            # the JSON response body ('example_erratum' defined below)
            response.json.return_value = example_erratum
            # Set the return value of the requests.get call to the
            # response we just created
            get.return_value = response
            e = errata.get_erratum(123456)
            self.assertIsInstance(e, ocp_cd_tools.errata.Erratum)

    def test_get_erratum_failure(self):
        """Verify a 'bad' erratum request returns False"""
        with mock.patch('ocp_cd_tools.errata.requests.get') as get:
            # Engage the not-found branch
            response = mock.MagicMock(status_code=404)
            response.json.return_value = example_erratum
            get.return_value = response
            e = errata.get_erratum(123456)
            self.assertFalse(e)

    def test_parse_date(self):
        """Verify we can parse the date string returned from Errata Tool"""
        d_expected = '2018-03-02 15:19:08'
        d_out = errata.parse_date(example_erratum['errata']['rhba']['created_at'])
        self.assertEqual(str(d_out), d_expected)

    def test_get_filtered_list(self):
        """Ensure we can generate an Erratum List"""
        with mock.patch('ocp_cd_tools.errata.requests.get') as get:
            response = mock.MagicMock(status_code=200)
            response.json.return_value = example_erratum_filtered_list
            get.return_value = response
            res = errata.get_filtered_list()
            self.assertEqual(2, len(res))

    def test_get_filtered_list_limit(self):
        """Ensure we can generate a trimmed Erratum List"""
        with mock.patch('ocp_cd_tools.errata.requests.get') as get:
            response = mock.MagicMock(status_code=200)
            response.json.return_value = example_erratum_filtered_list
            get.return_value = response
            res = errata.get_filtered_list(limit=1)
            self.assertEqual(1, len(res))

    def test_get_filtered_list_fail(self):
        """Ensure we notice invalid erratum lists"""
        with mock.patch('ocp_cd_tools.errata.requests.get') as get:
            response = mock.MagicMock(status_code=404)
            response.json.return_value = example_erratum_filtered_list
            get.return_value = response
            res = errata.get_filtered_list()
            # False when a list is not found in Errata Tool
            self.assertEqual(False, res)

    def test_working_erratum(self):
        """We can create an Erratum object with a known erratum from the API"""
        # If there is an error, it will raise on its own during parsing
        #
        # If the tool fails in the future due to a schema change in
        # the returned erratum object from the ET API then the
        # `example_erratum` in this test file will need to be updated.
        e = errata.Erratum(body=example_erratum)
        self.assertEqual(type(e), type(ocp_cd_tools.errata.Erratum()))

    def test_add_bug(self):
        """Verify Bugs are added the right way"""
        with nested(
                mock.patch('ocp_cd_tools.errata.requests.post'),
                # Mock the HTTPKerberosAuth object in the module
                mock.patch('ocp_cd_tools.errata.HTTPKerberosAuth')) as (post, kerb):
            response = mock.MagicMock(status_code=404)
            response.json.return_value = example_erratum_filtered_list
            post.return_value = response

            b = bugzilla.Bug(id=1337)

            # With the mocked HTTPKerberosAuth object we can now
            # create an erratum
            e = errata.Erratum(body=example_erratum)

            # When we make the method call, we will be using the same
            # mocked ('kerb') HTTPKerberosAuth object
            e.add_bug(b)

            post.assert_called_once_with(
                ocp_cd_tools.constants.errata_add_bug_url.format(id=example_erratum['content']['content']['errata_id']),
                auth=kerb(),
                json={'bug': b.id}
            )

    def test_add_builds_success(self):
        """Ensure legit builds are added correctly"""
        with nested(
                mock.patch('ocp_cd_tools.errata.requests.post'),
                mock.patch('ocp_cd_tools.errata.HTTPKerberosAuth')) as (post, kerb):
            response = mock.MagicMock(status_code=200)
            response.json.return_value = example_erratum_filtered_list
            post.return_value = response

            pv = 'rhaos-test-7'
            e = errata.Erratum(body=example_erratum)
            b1 = brew.Build(nvr='coreutils-8.22-21.el7',
                            body=rpm_build_attached_json,
                            product_version=pv)
            b2 = brew.Build(nvr='ansible-service-broker-1.0.21-1.el7',
                            body=rpm_build_unattached_json,
                            product_version=pv)
            builds = [b1, b2]

            result = e.add_builds(builds)

            # add_builds returns True on success
            self.assertTrue(result)
            # Even though we have multiple builds, the add_builds
            # endpoint allows us to make just one call, as it
            # accepts a list of builds in the request body
            self.assertEqual(post.call_count, 1)

            post.assert_called_once_with(
                ocp_cd_tools.constants.errata_add_builds_url.format(id=example_erratum['content']['content']['errata_id']),
                auth=kerb(),
                json=[b1.to_json(), b2.to_json()]
            )

    def test_add_builds_failure(self):
        """Ensure failing add_builds raises correctly on a known bad status code"""
        with nested(
                mock.patch('ocp_cd_tools.errata.requests.post'),
                mock.patch('ocp_cd_tools.errata.HTTPKerberosAuth')) as (post, kerb):
            # This triggers the failure code-branch
            response = mock.MagicMock(status_code=422)
            response.json.return_value = example_erratum_filtered_list
            post.return_value = response

            pv = 'rhaos-test-7'
            e = errata.Erratum(body=example_erratum)
            b1 = brew.Build(nvr='coreutils-8.22-21.el7',
                            body=rpm_build_attached_json,
                            product_version=pv)
            b2 = brew.Build(nvr='ansible-service-broker-1.0.21-1.el7',
                            body=rpm_build_unattached_json,
                            product_version=pv)
            builds = [b1, b2]

            with self.assertRaises(ocp_cd_tools.brew.BrewBuildException):
                result = e.add_builds(builds)

    # Commented out until we update add_builds to handle non-422 response codes
    # def test_add_builds_failure(self):
    #     """Ensure failing add_builds raises correctly on an unknown bad status code"""
    #     with mock.patch('ocp_cd_tools.errata.requests.post') as post:
    #         # This triggers the failure code-branch
    #         response = mock.MagicMock(status_code=500)
    #         response.json.return_value = example_erratum_filtered_list
    #         post.return_value = response
    #         with mock.patch('ocp_cd_tools.errata.HTTPKerberosAuth') as kerb:
    #             pv = 'rhaos-test-7'
    #             e = errata.Erratum(body=example_erratum)
    #             b1 = brew.Build(nvr='coreutils-8.22-21.el7',
    #                             body=rpm_build_attached_json,
    #                             product_version=pv)
    #             b2 = brew.Build(nvr='ansible-service-broker-1.0.21-1.el7',
    #                             body=rpm_build_unattached_json,
    #                             product_version=pv)
    #             builds = [b1, b2]

    #             with self.assertRaises(ocp_cd_tools.brew.BrewBuildException):
    #                 result = e.add_builds(builds)

example_erratum_filtered_list = [
    {
        "id": 32964,
        "type": "RHBA",
        "text_only": False,
        "advisory_name": "RHBA-2018:0476",
        "synopsis": "Red Hat OpenShift Enterprise 3.7, 3.6, 3.5, 3.4, and 3.3 images update",
        "revision": 6,
        "status": "IN_PUSH",
        "security_impact": "None",
        "respin_count": 1,
        "pushcount": 0,
        "content_types": [
            "docker"
        ],
        "timestamps": {
            "issue_date": "2018-03-08T14:07:14Z",
            "update_date": "2018-03-08T14:07:14Z",
            "release_date": "2018-03-12T00:00:00Z",
            "status_time": "2018-03-13T14:17:34Z",
            "security_sla": None,
            "created_at": "2018-03-08T14:07:14Z",
            "updated_at": "2018-03-13T14:17:34Z"
        },
        "flags": {
            "text_ready": False,
            "mailed": False,
            "pushed": False,
            "published": False,
            "deleted": False,
            "qa_complete": True,
            "rhn_complete": False,
            "doc_complete": True,
            "rhnqa": True,
            "closed": False,
            "sign_requested": False,
            "embargo_undated": False
        },
        "product": {
            "id": 79,
            "name": "Red Hat OpenShift Enterprise",
            "short_name": "RHOSE"
        },
        "release": {
            "id": 436,
            "name": "RHOSE ASYNC"
        },
        "people": {
            "assigned_to": "dma@redhat.com",
            "reporter": "smunilla@redhat.com",
            "qe_group": "OpenShift QE",
            "docs_group": "Default",
            "doc_reviewer": "adellape@redhat.com",
            "devel_group": "Default",
            "package_owner": "smunilla@redhat.com"
        },
        "content": {
            "topic": "An update is now available for Red Hat OpenShift Container Platform 3.7, 3.6, 3.5, 3.4, and 3.3.",
            "description": "OpenShift Container Platform by Red Hat is the company's cloud computing Platform-as-a-Service (PaaS) solution designed for on-premise or private cloud deployments.\n\nThis advisory contains the container images for this release. See the following advisory for the RPM packages and full list of security fixes for this release:\n\nhttps://access.redhat.com/errata/RHSA-2018:0475\n\nThis update contains the following images:\n\nopenshift3/ose:v3.3.1.46.11-20\nopenshift3/node:v3.3.1.46.11-21\n\nopenshift3/ose:v3.4.1.44.38-20\nopenshift3/node:v3.4.1.44.38-21\n\nopenshift3/node:v3.5.5.31.48-20\n\nopenshift3/node:v3.6.173.0.96-20\n\nopenshift3/node:v3.7.23-21\n\nAll OpenShift Container Platform 3.7, 3.6, 3.5, 3.4, and 3.3 users are advised to upgrade to these updated images.",
            "solution": "For details on how to apply this update, which includes the changes described in this advisory, refer to:\n\nhttps://access.redhat.com/articles/11258",
            "keywords": ""
        }
    },
    {
        "id": 32916,
        "type": "RHBA",
        "text_only": False,
        "advisory_name": "RHBA-2018:32916",
        "synopsis": "TEST OpenShift Container Platform 3.5 bug fix and enhancement update",
        "revision": 1,
        "status": "NEW_FILES",
        "security_impact": "None",
        "respin_count": 0,
        "pushcount": 0,
        "content_types": [],
        "timestamps": {
            "issue_date": "2018-03-02T15:19:08Z",
            "update_date": "2018-03-02T15:19:08Z",
            "release_date": None,
            "status_time": "2018-03-02T15:19:08Z",
            "security_sla": None,
            "created_at": "2018-03-02T15:19:08Z",
            "updated_at": "2018-03-07T20:47:23Z"
        },
        "flags": {
            "text_ready": False,
            "mailed": False,
            "pushed": False,
            "published": False,
            "deleted": False,
            "qa_complete": False,
            "rhn_complete": False,
            "doc_complete": False,
            "rhnqa": False,
            "closed": False,
            "sign_requested": False,
            "embargo_undated": False
        },
        "product": {
            "id": 79,
            "name": "Red Hat OpenShift Enterprise",
            "short_name": "RHOSE"
        },
        "release": {
            "id": 436,
            "name": "RHOSE ASYNC"
        },
        "people": {
            "assigned_to": "wsun@redhat.com",
            "reporter": "tbielawa@redhat.com",
            "qe_group": "OpenShift QE",
            "docs_group": "Default",
            "doc_reviewer": "docs-errata-list@redhat.com",
            "devel_group": "Default",
            "package_owner": "smunilla@redhat.com"
        },
        "content": {
            "topic": "Red Hat OpenShift Container Platform releases 3.5.z are now available with updates to packages and images that fix several bugs and add enhancements.",
            "description": "Red Hat OpenShift Container Platform is the company's cloud computing Platform-as-a-Service (PaaS) solution designed for on-premise or private cloud deployments.\n\nThis advisory contains the RPM packages for Red Hat OpenShift Container Platform 3.5.z. See the following advisory for the container images for this release:\n\nhttps://access.redhat.com/errata/RHBA-2018:0114\n\nSpace precludes documenting all of the bug fixes and enhancements in this advisory. See the following Release Notes documentation, which will be updated shortly for this release, for details about these changes:\n\nhttps://docs.openshift.com/container-platform/3.5/release_notes/ocp_3_5_release_notes.html\n\nAll OpenShift Container Platform 3.5 users are advised to upgrade to these updated packages and images.",
            "solution": "Before applying this update, make sure all previously released errata relevant to your system have been applied.\n\nFor OpenShift Container Platform 3.5 see the following documentation, which will be updated shortly for release 3.5.z, for important instructions on how to upgrade your cluster and fully apply this asynchronous errata update:\n\nhttps://docs.openshift.com/container-platform/3.5/release_notes/ocp_3_5_release_notes.html\n\nThis update is available via the Red Hat Network. Details on how to use the Red Hat Network to apply this update are available at https://access.redhat.com/articles/11258.",
            "keywords": ""
        }
    }
]


example_erratum = {
    "diffs": {},
    "jira_issues": {
        "jira_issues": [],
        "id_field": "key",
        "id_prefix": "jira:",
        "idsfixed": [],
        "to_fetch": [],
        "type": "jira_issues",
        "errata": {
            "rhba": {
                "rating": 0,
                "rhnqa": 0,
                "state_machine_rule_set_id": None,
                "current_tps_run": None,
                "updated_at": "2018-03-07T20:47:23Z",
                "current_state_index_id": 204419,
                "is_brew": 1,
                "pushed": 0,
                "devel_responsibility_id": 3,
                "docs_responsibility_id": 1,
                "rhn_complete": 0,
                "rhnqa_shadow": 0,
                "actual_ship_date": None,
                "sign_requested": 0,
                "id": 32916,
                "update_date": "2018-03-02T15:19:08Z",
                "is_batch_blocker": False,
                "qa_complete": 0,
                "severity": "normal",
                "supports_multiple_product_destinations": True,
                "status_updated_at": "2018-03-02T15:19:08Z",
                "published_shadow": 0,
                "priority": "normal",
                "is_valid": 1,
                "manager_id": 3001032,
                "closed": 0,
                "batch_id": None,
                "security_impact": "None",
                "revision": 1,
                "status": "NEW_FILES",
                "publish_date_override": "2019-01-01T00:00:00Z",
                "text_ready": 0,
                "errata_id": 32916,
                "deleted": 0,
                "request_rcm_push_comment_id": None,
                "issue_date": "2018-03-02T15:19:08Z",
                "pushcount": 0,
                "security_sla": None,
                "respin_count": 0,
                "mailed": 0,
                "security_approved": None,
                "reporter_id": 3003255,
                "quality_responsibility_id": 139,
                "doc_complete": 0,
                "old_advisory": None,
                "product_id": 79,
                "filelist_changed": 0,
                "old_delete_product": None,
                "created_at": "2018-03-02T15:19:08Z",
                "text_only": False,
                "request": 0,
                "assigned_to_id": 3002255,
                "contract": None,
                "content_types": [],
                "release_date": None,
                "synopsis": "TEST OpenShift Container Platform 3.5 bug fix and enhancement update",
                "package_owner_id": 3002860,
                "fulladvisory": "RHBA-2018:32916-01",
                "published": 0,
                "filelist_locked": 0,
                "group_id": 436,
                "resolution": "",
                "embargo_undated": False
            }
        }
    },
    "who": {
        "user": {
            "preferences": {
                "default_filter_id": "1",
                "full_width_layout": "1",
                "color_scheme": "pink"
            },
            "user_organization_id": 142,
            "receives_mail": True,
            "enabled": 1,
            "login_name": "tbielawa@redhat.com",
            "orgchart_id": None,
            "email_address": None,
            "id": 3003255,
            "realname": "Tim Bielawa"
        }
    },
    "bugs": {
        "idsfixed": [],
        "bugs": [],
        "id_field": "id",
        "id_prefix": "bz:",
        "to_fetch": [],
        "type": "bugs",
        "errata": {
            "rhba": {
                "rating": 0,
                "rhnqa": 0,
                "state_machine_rule_set_id": None,
                "current_tps_run": None,
                "updated_at": "2018-03-07T20:47:23Z",
                "current_state_index_id": 204419,
                "is_brew": 1,
                "pushed": 0,
                "devel_responsibility_id": 3,
                "docs_responsibility_id": 1,
                "rhn_complete": 0,
                "rhnqa_shadow": 0,
                "actual_ship_date": None,
                "sign_requested": 0,
                "id": 32916,
                "update_date": "2018-03-02T15:19:08Z",
                "is_batch_blocker": False,
                "qa_complete": 0,
                "severity": "normal",
                "supports_multiple_product_destinations": True,
                "status_updated_at": "2018-03-02T15:19:08Z",
                "published_shadow": 0,
                "priority": "normal",
                "is_valid": 1,
                "manager_id": 3001032,
                "closed": 0,
                "batch_id": None,
                "security_impact": "None",
                "revision": 1,
                "status": "NEW_FILES",
                "publish_date_override": "2019-01-01T00:00:00Z",
                "text_ready": 0,
                "errata_id": 32916,
                "deleted": 0,
                "request_rcm_push_comment_id": None,
                "issue_date": "2018-03-02T15:19:08Z",
                "pushcount": 0,
                "security_sla": None,
                "respin_count": 0,
                "mailed": 0,
                "security_approved": None,
                "reporter_id": 3003255,
                "quality_responsibility_id": 139,
                "doc_complete": 0,
                "old_advisory": None,
                "product_id": 79,
                "filelist_changed": 0,
                "old_delete_product": None,
                "created_at": "2018-03-02T15:19:08Z",
                "text_only": False,
                "request": 0,
                "assigned_to_id": 3002255,
                "contract": None,
                "content_types": [],
                "release_date": None,
                "synopsis": "TEST OpenShift Container Platform 3.5 bug fix and enhancement update",
                "package_owner_id": 3002860,
                "fulladvisory": "RHBA-2018:32916-01",
                "published": 0,
                "filelist_locked": 0,
                "group_id": 436,
                "resolution": "",
                "embargo_undated": False
            }
        }
    },
    "content": {
        "content": {
            "revision_count": 1,
            "packages": None,
            "errata_id": 32916,
            "description": "Red Hat OpenShift Container Platform is the company's cloud computing Platform-as-a-Service (PaaS) solution designed for on-premise or private cloud deployments.\n\nThis advisory contains the RPM packages for Red Hat OpenShift Container Platform 3.5.z. See the following advisory for the container images for this release:\n\nhttps://access.redhat.com/errata/RHBA-2018:0114\n\nSpace precludes documenting all of the bug fixes and enhancements in this advisory. See the following Release Notes documentation, which will be updated shortly for this release, for details about these changes:\n\nhttps://docs.openshift.com/container-platform/3.5/release_notes/ocp_3_5_release_notes.html\n\nAll OpenShift Container Platform 3.5 users are advised to upgrade to these updated packages and images.",
            "reference": "",
            "updated_at": "2018-03-02T15:19:08Z",
            "doc_review_due_at": None,
            "multilib": None,
            "solution": "Before applying this update, make sure all previously released errata relevant to your system have been applied.\n\nFor OpenShift Container Platform 3.5 see the following documentation, which will be updated shortly for release 3.5.z, for important instructions on how to upgrade your cluster and fully apply this asynchronous errata update:\n\nhttps://docs.openshift.com/container-platform/3.5/release_notes/ocp_3_5_release_notes.html\n\nThis update is available via the Red Hat Network. Details on how to use the Red Hat Network to apply this update are available at https://access.redhat.com/articles/11258.",
            "how_to_test": None,
            "doc_reviewer_id": 1,
            "topic": "Red Hat OpenShift Container Platform releases 3.5.z are now available with updates to packages and images that fix several bugs and add enhancements.",
            "obsoletes": "",
            "keywords": "",
            "text_only_cpe": None,
            "product_version_text": None,
            "cve": "",
            "id": 30494,
            "crossref": ""
        }
    },
    "params": {
        "action": "show",
        "controller": "api/v1/erratum",
        "id": "32916",
        "format": "json"
    },
    "errata": {
        "rhba": {
            "rating": 0,
            "rhnqa": 0,
            "state_machine_rule_set_id": None,
            "current_tps_run": None,
            "updated_at": "2018-03-07T20:47:23Z",
            "current_state_index_id": 204419,
            "is_brew": 1,
            "pushed": 0,
            "devel_responsibility_id": 3,
            "docs_responsibility_id": 1,
            "rhn_complete": 0,
            "rhnqa_shadow": 0,
            "actual_ship_date": None,
            "sign_requested": 0,
            "id": 32916,
            "update_date": "2018-03-02T15:19:08Z",
            "is_batch_blocker": False,
            "qa_complete": 0,
            "severity": "normal",
            "supports_multiple_product_destinations": True,
            "status_updated_at": "2018-03-02T15:19:08Z",
            "published_shadow": 0,
            "priority": "normal",
            "is_valid": 1,
            "manager_id": 3001032,
            "closed": 0,
            "batch_id": None,
            "security_impact": "None",
            "revision": 1,
            "status": "NEW_FILES",
            "publish_date_override": "2019-01-01T00:00:00Z",
            "text_ready": 0,
            "errata_id": 32916,
            "deleted": 0,
            "request_rcm_push_comment_id": None,
            "issue_date": "2018-03-02T15:19:08Z",
            "pushcount": 0,
            "security_sla": None,
            "respin_count": 0,
            "mailed": 0,
            "security_approved": None,
            "reporter_id": 3003255,
            "quality_responsibility_id": 139,
            "doc_complete": 0,
            "old_advisory": None,
            "product_id": 79,
            "filelist_changed": 0,
            "old_delete_product": None,
            "created_at": "2018-03-02T15:19:08Z",
            "text_only": False,
            "request": 0,
            "assigned_to_id": 3002255,
            "contract": None,
            "content_types": [],
            "release_date": None,
            "synopsis": "TEST OpenShift Container Platform 3.5 bug fix and enhancement update",
            "package_owner_id": 3002860,
            "fulladvisory": "RHBA-2018:32916-01",
            "published": 0,
            "filelist_locked": 0,
            "group_id": 436,
            "resolution": "",
            "embargo_undated": False
        }
    }
}


rpm_build_attached_json = {
    "id": 629986,
    "nvr": "coreutils-8.22-21.el7",
    "package": {
        "id": 87,
        "name": "coreutils"
    },
    "released_errata": None,
    "all_errata": [
        {
            "id": 30540,
            "name": "RHBA-2017:30540",
            "status": "REL_PREP"
        }
    ],
    "rpms_signed": True,
    "files": [
        {
            "id": 5256225,
            "path": "/mnt/redhat/brewroot/packages/coreutils/8.22/21.el7/data/signed/fd431d51/src/coreutils-8.22-21.el7.src.rpm",
            "type": "rpm",
            "arch": {
                "id": 24,
                "name": "SRPMS"
            }
        },
        {
            "id": 5256226,
            "path": "/mnt/redhat/brewroot/packages/coreutils/8.22/21.el7/data/signed/fd431d51/ppc/coreutils-8.22-21.el7.ppc.rpm",
            "type": "rpm",
            "arch": {
                "id": 17,
                "name": "ppc"
            }
        },
        {
            "id": 5256227,
            "path": "/mnt/redhat/brewroot/packages/coreutils/8.22/21.el7/data/signed/fd431d51/ppc/coreutils-debuginfo-8.22-21.el7.ppc.rpm",
            "type": "rpm",
            "arch": {
                "id": 17,
                "name": "ppc"
            }
        }
    ]
}

rpm_build_unattached_json = {
    "id": 653686,
    "nvr": "ansible-service-broker-1.0.21-1.el7",
    "package": {
        "id": 38747,
        "name": "ansible-service-broker"
    },
    "released_errata": None,
    "all_errata": [],
    "rpms_signed": False,
    "files": [
        {
            "id": 5446315,
            "path": "/mnt/redhat/brewroot/packages/ansible-service-broker/1.0.21/1.el7/src/ansible-service-broker-1.0.21-1.el7.src.rpm",
            "type": "rpm",
            "arch": {
                "id": 24,
                "name": "SRPMS"
            }
        },
        {
            "id": 5446316,
            "path": "/mnt/redhat/brewroot/packages/ansible-service-broker/1.0.21/1.el7/noarch/ansible-service-broker-selinux-1.0.21-1.el7.noarch.rpm",
            "type": "rpm",
            "arch": {
                "id": 8,
                "name": "noarch"
            }
        }
    ]
}


if __name__ == '__main__':
    unittest.main()
