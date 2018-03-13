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
import errata

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





if __name__ == '__main__':
    unittest.main()
