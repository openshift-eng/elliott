import logging
import unittest
import xmlrpc.client
from datetime import datetime, timezone

from unittest import mock
import requests
from flexmock import flexmock

from elliottlib import bzutil, constants, exceptions
from elliottlib.bzutil import Bug, JIRABugTracker, BugzillaBugTracker, BugzillaBug, JIRABug, BugTracker

hostname = "bugzilla.redhat.com"


class TestBug(unittest.TestCase):
    def test_bug(self):
        bug_obj = flexmock(id=2)
        self.assertEqual(Bug(bug_obj).bug.id, bug_obj.id)

    def test_is_invalid_tracker_bug(self):
        bug_true = flexmock(id=1, summary="CVE-2022-0001", keywords=[], whiteboard_component=None)
        self.assertEqual(BugzillaBug(bug_true).is_invalid_tracker_bug(), True)


class TestBugTracker(unittest.TestCase):
    def test_get_corresponding_flaw_bugs(self):
        flaw_a = flexmock(id=1)
        flaw_b = flexmock(id=2)
        flaw_c = flexmock(id=3)
        valid_flaw_bugs = [flaw_a, flaw_b]

        tracker_bugs = [
            flexmock(corresponding_flaw_bug_ids=[flaw_a.id, flaw_b.id], id=10, whiteboard_component='component:foo'),
            flexmock(corresponding_flaw_bug_ids=[flaw_b.id, flaw_c.id], id=11, whiteboard_component='component:bar'),
            flexmock(corresponding_flaw_bug_ids=[flaw_b.id], id=12, whiteboard_component=None),
            flexmock(corresponding_flaw_bug_ids=[flaw_c.id], id=13, whiteboard_component='component:foobar'),
        ]

        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_flaw_bugs").and_return(valid_flaw_bugs)
        expected = (
            {10: [flaw_a.id, flaw_b.id], 11: [flaw_b.id]},
            {
                flaw_a.id: {'bug': flaw_a, 'trackers': [tracker_bugs[0]]},
                flaw_b.id: {'bug': flaw_b, 'trackers': [tracker_bugs[0], tracker_bugs[1]]}
            }
        )
        brew_api = flexmock()
        brew_api.should_receive("getPackageID").and_return(True)
        actual = BugTracker.get_corresponding_flaw_bugs(tracker_bugs, BugzillaBugTracker({}), brew_api, strict=False)
        self.assertEqual(expected, actual)

    def test_get_corresponding_flaw_bugs_strict(self):
        flaw_a = flexmock(id=1)
        flaw_b = flexmock(id=2)
        flaw_c = flexmock(id=3)
        valid_flaw_bugs = [flaw_a, flaw_b]

        tracker_bugs = [
            flexmock(corresponding_flaw_bug_ids=[flaw_a.id, flaw_b.id], id=10, whiteboard_component='component:foo'),
            flexmock(corresponding_flaw_bug_ids=[flaw_b.id, flaw_c.id], id=11, whiteboard_component='component:bar'),
            flexmock(corresponding_flaw_bug_ids=[flaw_b.id], id=12, whiteboard_component=None),
            flexmock(corresponding_flaw_bug_ids=[flaw_c.id], id=13, whiteboard_component='component:foobar'),
        ]

        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_flaw_bugs").and_return(valid_flaw_bugs)

        brew_api = flexmock()
        brew_api.should_receive("getPackageID").and_return(True)
        self.assertRaises(
            exceptions.ElliottFatalError,
            BugTracker.get_corresponding_flaw_bugs, tracker_bugs, BugzillaBugTracker({}), brew_api, strict=True)


class TestJIRABugTracker(unittest.TestCase):
    def test_get_config(self):
        config = {'foo': 1, 'jira_config': {'bar': 2}}
        runtime = flexmock(
            gitdata=flexmock(load_data=flexmock(data=config)),
            get_major_minor=lambda: (4, 9)
        )
        actual = JIRABugTracker.get_config(runtime)
        expected = {'foo': 1, 'bar': 2}
        self.assertEqual(actual, expected)


class TestBugzillaBugTracker(unittest.TestCase):
    def test_get_config(self):
        config = {'foo': 1, 'bugzilla_config': {'bar': 2}}
        runtime = flexmock(
            gitdata=flexmock(load_data=flexmock(data=config)),
            get_major_minor=lambda: (4, 9)
        )
        actual = BugzillaBugTracker.get_config(runtime)
        expected = {'foo': 1, 'bar': 2}
        self.assertEqual(actual, expected)


class TestJIRABug(unittest.TestCase):
    def test_blocked_by_bz(self):
        bug_id = 123456
        bug = flexmock(key='OCPBUGS-1',
                       fields=flexmock(customfield_12322152=f'bugzilla.com/id={bug_id}'))
        self.assertEqual(JIRABug(bug).blocked_by_bz, bug_id)

    def test_depends_on(self):
        bug = flexmock(key='OCPBUGS-1')
        flexmock(JIRABug).should_receive("_get_depends").and_return(['foo'])
        flexmock(JIRABug).should_receive("blocked_by_bz").and_return('bar')
        self.assertEqual(JIRABug(bug).depends_on, ['foo', 'bar'])

    def test_is_placeholder_bug(self):
        bug1 = flexmock(key='OCPBUGS-1',
                        fields=flexmock(
                            summary='Placeholder',
                            components=[flexmock(name='Release')],
                            labels=['Automation']))
        self.assertEqual(JIRABug(bug1).is_placeholder_bug(), True)

        bug2 = flexmock(key='OCPBUGS-2',
                        fields=flexmock(
                            summary='Placeholder',
                            components=[flexmock(name='Foo')],
                            labels=['Bar']))
        self.assertEqual(JIRABug(bug2).is_placeholder_bug(), False)

    def test_is_ocp_bug(self):
        bug1 = flexmock(key='OCPBUGS-1', fields=flexmock(project=flexmock(key='foo')))
        self.assertEqual(JIRABug(bug1).is_ocp_bug(), False)

        bug2 = flexmock(key='OCPBUGS-1', fields=flexmock(project=flexmock(key='OCPBUGS')))
        flexmock(JIRABug).should_receive("is_placeholder_bug").and_return(True)
        self.assertEqual(JIRABug(bug2).is_ocp_bug(), False)

        bug2 = flexmock(key='OCPBUGS-1', fields=flexmock(project=flexmock(key='OCPBUGS')))
        flexmock(JIRABug).should_receive("is_placeholder_bug").and_return(False)
        self.assertEqual(JIRABug(bug2).is_ocp_bug(), True)

    def test_is_tracker_bug(self):
        bug = flexmock(
            key='OCPBUGS1',
            fields=flexmock(labels=constants.TRACKER_BUG_KEYWORDS + ['somethingelse', 'pscomponent:my-image', 'flaw:bz#123']))
        expected = True
        actual = JIRABug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_is_tracker_bug_missing_keywords(self):
        bug = flexmock(
            key='OCPBUGS1',
            fields=flexmock(labels=['somethingelse', 'pscomponent:my-image', 'flaw:bz#123']))
        expected = False
        actual = JIRABug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_is_tracker_bug_missing_pscomponent(self):
        bug = flexmock(
            key='OCPBUGS1',
            fields=flexmock(labels=constants.TRACKER_BUG_KEYWORDS + ['somethingelse', 'flaw:bz#123']))
        expected = False
        actual = JIRABug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_is_tracker_bug_missing_flaw(self):
        bug = flexmock(
            key='OCPBUGS1',
            fields=flexmock(labels=constants.TRACKER_BUG_KEYWORDS + ['somethingelse', 'pscomponent:my-image']))
        expected = False
        actual = JIRABug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_component_sub_component(self):
        bug = JIRABug(flexmock(
            key="OCPBUGS-43",
            fields=flexmock(components=[flexmock(name="foo / bar")]))
        )
        actual = (bug.component, bug.sub_component)
        expected = ("foo", "bar")
        self.assertEqual(actual, expected)

    def test_component_sub_component_no_whitespace(self):
        bug = JIRABug(flexmock(
            key="OCPBUGS-43",
            fields=flexmock(components=[flexmock(name="foo/bar")]))
        )
        actual = (bug.component, bug.sub_component)
        expected = ("foo", "bar")
        self.assertEqual(actual, expected)

    def test_corresponding_flaw_bug_ids(self):
        bug = JIRABug(flexmock(
            key="OCPBUGS-43",
            fields=flexmock(labels=["foo", "flaw:123", "flaw:bz#456"]))
        )
        actual = bug.corresponding_flaw_bug_ids
        expected = [456]
        self.assertEqual(actual, expected)

    def test_whiteboard_component(self):
        bug = JIRABug(flexmock(key=1, fields=flexmock(labels=["foo"])))
        self.assertIsNone(bug.whiteboard_component)

        bug = JIRABug(flexmock(key=1, fields=flexmock(labels=["pscomponent: "])))
        self.assertIsNone(bug.whiteboard_component)

        for expected in ["something", "openvswitch2.15", "trailing_blank 	"]:
            bug = JIRABug(flexmock(key=1, fields=flexmock(labels=[f"pscomponent: {expected}"])))
            actual = bug.whiteboard_component
            self.assertEqual(actual, expected.strip())


class TestBugzillaBug(unittest.TestCase):
    def test_is_tracker_bug(self):
        bug = flexmock(
            id='1',
            keywords=constants.TRACKER_BUG_KEYWORDS,
            whiteboard_component='my-image')
        expected = True
        actual = BugzillaBug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_is_tracker_bug_fail(self):
        bug = flexmock(id='1', keywords=['SomeOtherKeyword'], whiteboard_component='my-image')
        expected = False
        actual = BugzillaBug(bug).is_tracker_bug()
        self.assertEqual(expected, actual)

    def test_whiteboard_component(self):
        bug = BugzillaBug(flexmock(id=1, whiteboard="foo"))
        self.assertIsNone(bug.whiteboard_component)

        bug = BugzillaBug(flexmock(id=2, whiteboard="component: "))
        self.assertIsNone(bug.whiteboard_component)

        for expected in ["something", "openvswitch2.15", "trailing_blank 	"]:
            bug = BugzillaBug(flexmock(id=2, whiteboard=f"component: {expected}"))
            actual = bug.whiteboard_component
            self.assertEqual(actual, expected.strip())

    def test_filter_bugs_by_cutoff_event(self):
        bzapi = mock.MagicMock()
        with mock.patch("elliottlib.bzutil.BugzillaBugTracker.login") as mock_login:
            mock_login.return_value = bzapi
            bug_tracker = bzutil.BugzillaBugTracker({})
        desired_statuses = ["MODIFIED", "ON_QA", "VERIFIED"]
        sweep_cutoff_timestamp = datetime(2021, 6, 30, 12, 30, 00, 0, tzinfo=timezone.utc).timestamp()
        bugs = [
            mock.MagicMock(id=1, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T12:29:00")),
            mock.MagicMock(id=2, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T12:30:00")),
            mock.MagicMock(id=3, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T12:31:00")),
            mock.MagicMock(id=4, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T00:00:00")),
            mock.MagicMock(id=5, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T00:00:00")),
            mock.MagicMock(id=6, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T00:00:00")),
            mock.MagicMock(id=7, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T00:00:00")),
            mock.MagicMock(id=8, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T00:00:00")),
            mock.MagicMock(id=9, status="ON_QA", creation_time=xmlrpc.client.DateTime("20210630T00:00:00")),
        ]
        bzapi.bugs_history_raw.return_value = {
            "bugs": [
                {
                    "id": 1,
                    "history": [],
                },
                {
                    "id": 2,
                    "history": [],
                },
                {
                    "id": 4,
                    "history": [
                        {
                            "when": xmlrpc.client.DateTime("20210630T01:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T23:59:59"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                            ]
                        },
                    ],
                },
                {
                    "id": 5,
                    "history": [
                        {
                            "when": xmlrpc.client.DateTime("20210630T01:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "NEW", "added": "MODIFIED"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T23:59:59"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "MODIFIED", "added": "ON_QA"},
                            ]
                        },
                    ],
                },
                {
                    "id": 6,
                    "history": [
                        {
                            "when": xmlrpc.client.DateTime("20210630T01:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "NEW", "added": "ASSIGNED"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T23:59:59"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "ASSIGNED", "added": "ON_QA"},
                            ]
                        },
                    ],
                },
                {
                    "id": 7,
                    "history": [
                        {
                            "when": xmlrpc.client.DateTime("20210630T01:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "NEW", "added": "MODIFIED"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T23:59:59"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "MODIFIED", "added": "ON_QA"},
                            ]
                        },
                    ],
                },
                {
                    "id": 8,
                    "history": [
                        {
                            "when": xmlrpc.client.DateTime("20210630T01:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "NEW", "added": "MODIFIED"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T13:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "MODIFIED", "added": "ON_QA"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T23:59:59"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "ON_QA", "added": "VERIFIED"},
                            ]
                        },
                    ],
                },
                {
                    "id": 9,
                    "history": [
                        {
                            "when": xmlrpc.client.DateTime("20210630T01:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "NEW", "added": "MODIFIED"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T13:00:00"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "MODIFIED", "added": "ON_QA"},
                            ]
                        },
                        {
                            "when": xmlrpc.client.DateTime("20210630T23:59:59"),
                            "changes": [
                                {"field_name": "irelevant1", "removed": "foo", "added": "bar"},
                                {"field_name": "irelevant2", "removed": "bar", "added": "foo"},
                                {"field_name": "status", "removed": "ON_QA", "added": "ASSIGNED"},
                            ]
                        },
                    ],
                },
            ]
        }
        actual = bug_tracker.filter_bugs_by_cutoff_event(bugs, desired_statuses, sweep_cutoff_timestamp)
        self.assertListEqual([1, 2, 4, 5, 7, 8], [bug.id for bug in actual])


class TestBZUtil(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_is_viable_bug(self):
        bug = mock.MagicMock()
        bug.status = "MODIFIED"
        self.assertTrue(bzutil.is_viable_bug(bug))
        bug.status = "ASSIGNED"
        self.assertFalse(bzutil.is_viable_bug(bug))

    def test_to_timestamp(self):
        dt = xmlrpc.client.DateTime("20210615T18:23:22")
        actual = bzutil.to_timestamp(dt)
        self.assertEqual(actual, 1623781402.0)

    async def test_approximate_cutoff_timestamp(self):
        koji_api = mock.MagicMock()
        koji_api.getEvent.return_value = {"ts": datetime(2021, 7, 3, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp()}
        metas = [
            mock.MagicMock(),
            mock.MagicMock(),
            mock.MagicMock(),
        ]
        metas[0].get_latest_build.return_value = {"nvr": "a-4.9.0-202107020000.p0"}
        metas[1].get_latest_build.return_value = {"nvr": "b-4.9.0-202107020100.p0"}
        metas[2].get_latest_build.return_value = {"nvr": "c-4.9.0-202107020200.p0"}
        actual = await bzutil.approximate_cutoff_timestamp(mock.ANY, koji_api, metas)
        self.assertEqual(datetime(2021, 7, 2, 2, 0, 0, 0, tzinfo=timezone.utc).timestamp(), actual)

        koji_api.getEvent.return_value = {"ts": datetime(2021, 7, 1, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp()}
        actual = await bzutil.approximate_cutoff_timestamp(mock.ANY, koji_api, metas)
        self.assertEqual(datetime(2021, 7, 1, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp(), actual)

        koji_api.getEvent.return_value = {"ts": datetime(2021, 7, 4, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp()}
        actual = await bzutil.approximate_cutoff_timestamp(mock.ANY, koji_api, [])
        self.assertEqual(datetime(2021, 7, 4, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp(), actual)

    def test_sort_cve_bugs(self):
        flaw_bugs = [
            flexmock(alias=['CVE-2022-123'], severity='Low'),
            flexmock(alias=['CVE-2022-9'], severity='urgent'),
            flexmock(alias=['CVE-2022-10'], severity='urgent'),
            flexmock(alias=['CVE-2021-789'], severity='medium'),
            flexmock(alias=['CVE-2021-100'], severity='medium')
        ]
        sort_list = [b.alias[0] for b in bzutil.sort_cve_bugs(flaw_bugs)]

        self.assertEqual('CVE-2022-9', sort_list[0])
        self.assertEqual('CVE-2022-10', sort_list[1])
        self.assertEqual('CVE-2021-100', sort_list[2])
        self.assertEqual('CVE-2021-789', sort_list[3])
        self.assertEqual('CVE-2022-123', sort_list[4])

    def test_is_first_fix_any_validate(self):
        tr = '4.8.z'
        expected = True
        actual = bzutil.is_first_fix_any(None, [], tr)
        self.assertEqual(expected, actual)

        # should raise error when no tracker bugs are found
        tr = '4.8.0'
        self.assertRaisesRegex(
            ValueError,
            r'does not seem to have trackers',
            bzutil.is_first_fix_any, BugzillaBug(flexmock(id=1)), [], tr)

        # should raise error when flaw alias isn't present
        tr = '4.8.0'
        self.assertRaisesRegex(
            ValueError,
            r'does not have an alias',
            bzutil.is_first_fix_any, BugzillaBug(flexmock(id=1)), ['foobar'], tr)

    def test_is_first_fix_any(self):
        hydra_data = {
            'package_state': [
                {
                    'product_name': "Red Hat Advanced Cluster Management for Kubernetes 2",
                    'fix_state': "Affected",
                    'package_name': "rhacm2/agent-service-rhel8"
                },
                {
                    'product_name': "Red Hat OpenShift Container Platform 4",
                    'fix_state': "Affected",
                    'package_name': "openshift-clients"
                },
                {
                    'product_name': "Red Hat OpenShift Container Platform 4",
                    'fix_state': "Some other status",
                    'package_name': "openshift4/some-image"
                },
                {
                    'product_name': "Red Hat OpenShift Container Platform 3",
                    'fix_state': "Affected",
                    'package_name': "openshift3/some-image"
                }
            ]
        }
        flexmock(requests).should_receive('get')\
            .and_return(flexmock(json=lambda: hydra_data, raise_for_status=lambda: None))\
            .ordered()

        pyxis_data = {'data': [{'brew': {'package': 'some-image'}}]}
        flexmock(requests).should_receive('get')\
            .and_return(flexmock(status_code=200, json=lambda: pyxis_data))\
            .ordered()

        tr = '4.8.0'
        flaw_bug = BugzillaBug(flexmock(id=1, alias=['CVE-123']))
        tracker_bugs = [flexmock(id=2, whiteboard_component='openshift-clients')]
        expected = True
        actual = bzutil.is_first_fix_any(flaw_bug, tracker_bugs, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_missing_package_state(self):
        hydra_data = {}
        flexmock(requests).should_receive('get')\
            .and_return(flexmock(json=lambda: hydra_data, raise_for_status=lambda: None))\

        tr = '4.8.0'
        flaw_bug = BugzillaBug(flexmock(id=1, alias=['CVE-123']))
        tracker_bugs = [flexmock(id=2, whiteboard_component='openshift-clients')]
        expected = False
        actual = bzutil.is_first_fix_any(flaw_bug, tracker_bugs, tr)
        self.assertEqual(expected, actual)

    def test_is_first_fix_any_fail(self):
        hydra_data = {
            'package_state': [
                {
                    'product_name': "Red Hat Advanced Cluster Management for Kubernetes 2",
                    'fix_state': "Affected",
                    'package_name': "rhacm2/agent-service-rhel8"
                },
                {
                    'product_name': "Red Hat OpenShift Container Platform 4",
                    'fix_state': "Affected",
                    'package_name': "openshift-clients"
                },
                {
                    'product_name': "Red Hat OpenShift Container Platform 4",
                    'fix_state': "Some other status",
                    'package_name': "openshift4/some-image"
                },
                {
                    'product_name': "Red Hat OpenShift Container Platform 3",
                    'fix_state': "Affected",
                    'package_name': "openshift3/some-image"
                }
            ]
        }
        flexmock(requests).should_receive('get')\
            .and_return(flexmock(json=lambda: hydra_data, raise_for_status=lambda: None))\
            .ordered()

        pyxis_data = {'data': [{'brew': {'package': 'some-image'}}]}
        flexmock(requests).should_receive('get')\
            .and_return(flexmock(status_code=200, json=lambda: pyxis_data))\
            .ordered()

        tr = '4.8.0'
        flaw_bug = BugzillaBug(flexmock(id=1, alias=['CVE-123']))
        tracker_bugs = [flexmock(id=2, whiteboard_component='openshift')]
        expected = False
        actual = bzutil.is_first_fix_any(flaw_bug, tracker_bugs, tr)
        self.assertEqual(expected, actual)


class TestSearchFilter(unittest.TestCase):
    def test_search_filter(self):
        """Verify the bugzilla SearchFilter works as expected"""
        field_name = "component"
        operator = "notequals"
        value = "RFE"
        expected = "&f1=component&o1=notequals&v1=RFE"

        sf = bzutil.SearchFilter(field_name, operator, value)
        self.assertEqual(sf.tostring(1), expected)


class TestGetHigestImpact(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_lowest_to_highest_impact(self):
        trackers = [flexmock(id=index, severity=severity)
                    for index, severity in enumerate(constants.BUG_SEVERITY_NUMBER_MAP.keys())]
        tracker_flaws_map = {
            tracker.id: [] for tracker in trackers
        }
        impact = bzutil.get_highest_impact(trackers, tracker_flaws_map)
        self.assertEqual(impact, constants.SECURITY_IMPACT[4])

    def test_single_impact(self):
        bugs = []
        severity = "high"
        bugs.append(flexmock(severity=severity))
        impact = bzutil.get_highest_impact(bugs, None)
        self.assertEqual(impact, constants.SECURITY_IMPACT[constants.BUG_SEVERITY_NUMBER_MAP[severity]])

    def test_impact_for_tracker_with_unspecified_severity(self):
        bugs = []
        severity = "unspecified"
        bugs.append(flexmock(id=123, severity=severity))
        tracker_flaws_map = {
            123: [flexmock(id=123, severity="medium")],
        }
        impact = bzutil.get_highest_impact(bugs, tracker_flaws_map)
        self.assertEqual(impact, "Moderate")
        tracker_flaws_map = {
            123: [flexmock(id=123, severity="unspecified")],
        }
        impact = bzutil.get_highest_impact(bugs, tracker_flaws_map)
        self.assertEqual(impact, "Low")


if __name__ == "__main__":
    unittest.main()
