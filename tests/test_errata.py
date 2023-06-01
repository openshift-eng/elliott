"""
Test errata models/controllers
"""
import datetime
from unittest import mock
import json
from flexmock import flexmock
import errata_tool
import bugzilla

import unittest
from unittest.mock import MagicMock, patch, Mock
from tests import test_structures
from elliottlib import errata, constants, brew, exceptions

unshipped_builds = [
    Mock(product_version='OSE-4.7-RHEL-8', build='image1-container-123', nvr='image1-container-123', file_types=['tar']),
    Mock(product_version='OSE-4.7-RHEL-8', build='image2-container-456', nvr='image2-container-456', file_types=['tar']),
    Mock(product_version='ANOTHER_PV', build='image3-container-789', nvr='image3-container-789', file_types=['tar'])]


class TestAdvisory(unittest.TestCase):
    def new_init(self, **kwargs):
        for key in kwargs:
            setattr(self, key, kwargs[key])

    errata_tool.Erratum.__init__ = new_init

    def test_ensure_state_valid_advisory_state(self):
        """Verify error is raised if desired state is not a recognized state"""
        advisory = errata.Advisory(errata_id=123, errata_state='invalid_errata_status')
        with self.assertRaises(ValueError) as context:
            advisory.ensure_state('UnknownState')
        self.assertTrue('UnknownState' in context.exception.__str__())

    @patch('elliottlib.errata.Advisory.setState')
    def test_ensure_state_untouched_if_not_necessary(self, setState):
        """Verify that advisory is untouched if desired state equals current state"""
        advisory = errata.Advisory(errata_id=123, errata_state='QE')
        advisory.ensure_state('QE')
        setState.assert_not_called()

    @patch('elliottlib.errata.Advisory.setState')
    @patch('errata_tool.Erratum.commit')
    def test_ensure_state_change_if_needed(self, setState, commit):
        """Verify attempt is made to set advisory state"""
        advisory = errata.Advisory(errata_id=123, errata_state='QE')
        advisory.ensure_state('NEW_FILES')
        setState.assert_called()

    @patch('click.echo')
    def test_attach_builds_verifies_valid_state(self, echo):
        """Verify error is raised when requesting unknown kind"""
        advisory = errata.Advisory(errata_id=123)
        with self.assertRaises(ValueError) as context:
            advisory.attach_builds(['build-1-123'], 'unkown_build_type')
        self.assertTrue("should be one of 'rpm' or 'image'" in context.exception.__str__())

    @patch('elliottlib.errata.green_print')
    @patch('click.echo')
    @patch('elliottlib.errata.Advisory.addBuilds')
    def test_attach_builds(self, addBuilds, echo, green_print):
        advisory = errata.Advisory(errata_id=123)
        advisory.attach_builds(unshipped_builds, 'image')

        self.assertEqual(addBuilds.call_count, 2)

        addBuilds.assert_any_call(buildlist=['image1-container-123', 'image2-container-456'], file_types={'image1-container-123': ['tar'], 'image2-container-456': ['tar']}, release='OSE-4.7-RHEL-8')
        addBuilds.assert_any_call(buildlist=['image3-container-789'], file_types={'image3-container-789': ['tar']}, release='ANOTHER_PV')


class TestErrata(unittest.TestCase):

    def test_parse_date(self):
        """Verify we can parse the date string returned from Errata Tool"""
        d_expected = '2018-03-02 15:19:08'
        d_out = datetime.datetime.strptime(test_structures.example_erratum['errata']['rhba']['created_at'], '%Y-%m-%dT%H:%M:%SZ')
        self.assertEqual(str(d_out), d_expected)

    def test_get_filtered_list(self):
        """Ensure we can generate an Erratum List"""
        flexmock(errata).should_receive("Advisory").and_return(None)

        response = flexmock(status_code=200)
        response.should_receive("json").and_return(test_structures.example_erratum_filtered_list)

        flexmock(errata.requests).should_receive("get").and_return(response)

        res = errata.get_filtered_list()
        self.assertEqual(2, len(res))

    def test_get_filtered_list_limit(self):
        """Ensure we can generate a trimmed Erratum List"""
        flexmock(errata).should_receive("Advisory").and_return(None)

        response = flexmock(status_code=200)
        response.should_receive("json").and_return(test_structures.example_erratum_filtered_list)

        flexmock(errata.requests).should_receive("get").and_return(response)

        res = errata.get_filtered_list(limit=1)
        self.assertEqual(1, len(res))

    def test_get_filtered_list_fail(self):
        """Ensure we notice invalid erratum lists"""
        (flexmock(errata.requests)
            .should_receive("get")
            .and_return(flexmock(status_code=404, text="_irrelevant_")))

        self.assertRaises(exceptions.ErrataToolError, errata.get_filtered_list)

    def test_parse_exception_error_message(self):
        self.assertEqual([1685398], errata.parse_exception_error_message('Bug #1685398 The bug is filed already in RHBA-2019:1589.'))

        self.assertEqual([], errata.parse_exception_error_message('invalid format'))

        self.assertEqual([1685398, 1685399], errata.parse_exception_error_message('''Bug #1685398 The bug is filed already in RHBA-2019:1589.
        Bug #1685399 The bug is filed already in RHBA-2019:1589.'''))

    def test_get_advisories_for_bug(self):
        bug = 123456
        advisories = [{"advisory_name": "RHBA-2019:3151", "status": "NEW_FILES", "type": "RHBA", "id": 47335, "revision": 3}]
        with mock.patch("requests.Session") as MockSession:
            session = MockSession()
            response = session.get.return_value
            response.json.return_value = advisories
            actual = errata.get_advisories_for_bug(bug, session)
            self.assertEqual(actual, advisories)

    def test_parse_product_version(self):
        product_version_map = {}
        product_version_json = """{
            "data":[
                {"id":964,"type":"product_versions","attributes":{"name":"OSE-4.1-RHEL-8","description":"Red Hat OpenShift Container Platform 4.1","default_brew_tag":"rhaos-4.1-rhel-8-candidate","allow_rhn_debuginfo":false,"is_oval_product":false,"is_rhel_addon":false,"is_server_only":true,"enabled":true},"brew_tags":["rhaos-4.1-rhel-8-candidate"],"relationships":{"rhel_release":{"id":87,"name":"RHEL-8"},"sig_key":{"id":8,"name":"redhatrelease2"}}}]
        }"""
        data = json.loads(product_version_json)
        for i in data['data']:
            if i['type'] == 'product_versions':
                for tags in i['brew_tags']:
                    product_version_map[tags] = i['attributes']['name']

        self.assertEqual(product_version_map, {'rhaos-4.1-rhel-8-candidate': 'OSE-4.1-RHEL-8'})

    def test_get_rpmdiff_runs(self):
        advisory_id = 12345
        responses = [
            {
                "data": [
                    {"id": 1},
                    {"id": 2},
                ]
            },
            {
                "data": [
                    {"id": 3},
                ]
            },
            {
                "data": []
            },
        ]
        session = mock.MagicMock()

        def mock_response(*args, **kwargs):
            page_number = kwargs["params"]["page[number]"]
            resp = mock.MagicMock()
            resp.json.return_value = responses[page_number - 1]
            return resp

        session.get.side_effect = mock_response
        actual = errata.get_rpmdiff_runs(advisory_id, None, session)
        self.assertEqual(len(list(actual)), 3)


class TestAdvisoryImages(unittest.TestCase):

    mocked_ocp3_response = {
        'kube-rbac-proxy-container-v3.11.154-1': {
            'docker': {
                'target': {
                    'repos': {
                        'redhat-openshift3-ose-kube-rbac-proxy': {
                            'tags': ['latest', 'v3.11', 'v3.11.154', 'v3.11.154-1']
                        }
                    }
                }
            }
        },
        'jenkins-subordinate-base-rhel7-container-v3.11.154-1': {
            'docker': {
                'target': {
                    'repos': {
                        'redhat-openshift3-jenkins-subordinate-base-rhel7': {
                            'tags': ['v3.11', 'v3.11.154', 'v3.11.154-1']
                        }
                    }
                }
            }
        },
        'openshift-enterprise-pod-container-v3.11.154-1': {
            'docker': {
                'target': {
                    'repos': {
                        'redhat-openshift3-ose-pod': {
                            'tags': ['latest', 'v3.11', 'v3.11.154', 'v3.11.154-1']
                        }
                    }
                }
            }
        }
    }

    mocked_ocp4_response = {
        'atomic-openshift-cluster-autoscaler-container-v4.2.5-201911121709': {
            'docker': {
                'target': {
                    'repos': {
                        'redhat-openshift4-ose-cluster-autoscaler': {
                            'tags': ['4.2', 'latest', 'v4.2.5', 'v4.2.5-201911121709']
                        }
                    }
                }
            }
        },
        'cluster-monitoring-operator-container-v4.2.5-201911121709': {
            'docker': {
                'target': {
                    'repos': {
                        'redhat-openshift4-ose-cluster-monitoring-operator': {
                            'tags': ['4.2', 'latest', 'v4.2.5', 'v4.2.5-201911121709']
                        }
                    }
                }
            }
        },
        'cluster-node-tuning-operator-container-v4.2.5-201911121709': {
            'docker': {
                'target': {
                    'repos': {
                        'redhat-openshift4-ose-cluster-node-tuning-operator': {
                            'tags': ['4.2', 'latest', 'v4.2.5', 'v4.2.5-201911121709']
                        }
                    }
                }
            }
        },
        'golang-github-openshift-oauth-proxy-container-v4.2.5-201911121709': {
            'docker': {
                'target': {
                    'repos': {
                        'redhat-openshift4-ose-oauth-proxy': {
                            'tags': ['4.2', 'latest', 'v4.2.5', 'v4.2.5-201911121709']
                        }
                    }
                }
            }
        },
    }

    def test_get_doctored_advisory_images_ocp_3(self):
        errata.errata_xmlrpc.get_advisory_cdn_docker_file_list = lambda *_: self.mocked_ocp3_response

        expected = """#########
openshift3/jenkins-subordinate-base-rhel7:v3.11.154-1
openshift3/ose-kube-rbac-proxy:v3.11.154-1
openshift3/ose-pod:v3.11.154-1
#########"""
        actual = errata.get_advisory_images('_irrelevant_', False)
        self.assertEqual(actual, expected)

    def test_get_raw_advisory_images_ocp_3(self):
        errata.errata_xmlrpc.get_advisory_cdn_docker_file_list = lambda *_: self.mocked_ocp3_response

        expected = """kube-rbac-proxy-container-v3.11.154-1
jenkins-subordinate-base-rhel7-container-v3.11.154-1
openshift-enterprise-pod-container-v3.11.154-1"""
        actual = errata.get_advisory_images('_irrelevant_', True)
        self.assertEqual(actual, expected)

    def test_get_raw_advisory_images_ocp_4(self):
        errata.errata_xmlrpc.get_advisory_cdn_docker_file_list = lambda *_: self.mocked_ocp4_response

        expected = """atomic-openshift-cluster-autoscaler-container-v4.2.5-201911121709
cluster-monitoring-operator-container-v4.2.5-201911121709
cluster-node-tuning-operator-container-v4.2.5-201911121709
golang-github-openshift-oauth-proxy-container-v4.2.5-201911121709"""

        actual = errata.get_advisory_images('_irrelevant_', True)
        self.assertEqual(actual, expected)


class testErratum:
    def __init__(self, rt, ntt):
        self.retry_times = rt
        self.none_throw_threshold = ntt

    def commit(self):
        if self.retry_times <= self.none_throw_threshold:
            self.retry_times = self.retry_times + 1
            raise errata_tool.ErrataException("this is an exception from testErratum")
        else:
            pass

    def addBugs(self, buglist):
        pass


if __name__ == '__main__':
    unittest.main()
