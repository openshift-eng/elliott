"""
Test errata models/controllers
"""
import datetime
import mock
import json
from contextlib import nested
import flexmock
from errata_tool import ErrataException
import bugzilla

import unittest
from . import test_structures
from elliottlib import errata, constants, brew, exceptions


class TestErrata(unittest.TestCase):

    def test_parse_date(self):
        """Verify we can parse the date string returned from Errata Tool"""
        d_expected = '2018-03-02 15:19:08'
        d_out = datetime.datetime.strptime(test_structures.example_erratum['errata']['rhba']['created_at'], '%Y-%m-%dT%H:%M:%SZ')
        self.assertEqual(str(d_out), d_expected)

    def test_get_filtered_list(self):
        """Ensure we can generate an Erratum List"""
        flexmock(errata).should_receive("Erratum").and_return(None)

        response = flexmock(status_code=200)
        response.should_receive("json").and_return(test_structures.example_erratum_filtered_list)

        flexmock(errata.requests).should_receive("get").and_return(response)

        res = errata.get_filtered_list()
        self.assertEqual(2, len(res))

    def test_get_filtered_list_limit(self):
        """Ensure we can generate a trimmed Erratum List"""
        flexmock(errata).should_receive("Erratum").and_return(None)

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
    def test_get_advisory_images_ocp_4(self):
        mocked_response = {
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
            'jenkins-slave-base-rhel7-container-v3.11.154-1': {
                'docker': {
                    'target': {
                        'repos': {
                            'redhat-openshift3-jenkins-slave-base-rhel7': {
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
        errata.errata_xmlrpc.get_advisory_cdn_docker_file_list = lambda *_: mocked_response

        expected = """#########
openshift3/jenkins-slave-base-rhel7:v3.11.154-1
openshift3/ose-kube-rbac-proxy:v3.11.154-1
openshift3/ose-pod:v3.11.154-1
#########"""
        actual = errata.get_advisory_images('_irrelevant_')
        self.assertEqual(actual, expected)

    def test_get_advisory_images_ocp_4(self):
        mocked_response = {
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
        errata.errata_xmlrpc.get_advisory_cdn_docker_file_list = lambda *_: mocked_response

        expected = """#########
openshift4/ose-cluster-autoscaler:v4.2.5-201911121709
openshift4/ose-cluster-monitoring-operator:v4.2.5-201911121709
openshift4/ose-cluster-node-tuning-operator:v4.2.5-201911121709
openshift4/ose-oauth-proxy:v4.2.5-201911121709
#########"""
        actual = errata.get_advisory_images('_irrelevant_')
        self.assertEqual(actual, expected)


class testErratum:
    def __init__(self, rt, ntt):
        self.retry_times = rt
        self.none_throw_threshold = ntt

    def commit(self):
        if self.retry_times <= self.none_throw_threshold:
            self.retry_times = self.retry_times + 1
            raise ErrataException("this is an exception from testErratum")
        else:
            pass

    def addBugs(self, buglist):
        pass


if __name__ == '__main__':
    unittest.main()
