from datetime import datetime, timezone
import logging
import unittest
import xmlrpc.client

from flexmock import flexmock
import mock
from elliottlib.bzutil import JIRABugTracker, BugzillaBugTracker, BugzillaBug, JIRABug
from elliottlib import bzutil, constants

hostname = "bugzilla.redhat.com"


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


class TestBZUtil(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_whiteboard_component_bz(self):
        bug = BugzillaBug(mock.MagicMock(id=1, whiteboard="foo"))
        self.assertIsNone(bug.whiteboard_component)

        bug = BugzillaBug(mock.MagicMock(id=2, whiteboard="component: "))
        self.assertIsNone(bug.whiteboard_component)

        for expected in ["something", "openvswitch2.15", "trailing_blank 	"]:
            bug = BugzillaBug(mock.MagicMock(whiteboard=f"component: {expected}"))
            expected = expected.strip()
            actual = bug.whiteboard_component
            self.assertEqual(actual, expected.strip())

    def test_whiteboard_component_jira(self):
        bug = JIRABug(mock.MagicMock(id=1, fields=mock.MagicMock(labels=["foo"])))
        self.assertIsNone(bug.whiteboard_component)

        bug = JIRABug(mock.MagicMock(id=1, fields=mock.MagicMock(labels=["component: "])))
        self.assertIsNone(bug.whiteboard_component)

        for expected in ["something", "openvswitch2.15", "trailing_blank 	"]:
            bug = JIRABug(mock.MagicMock(id=1, fields=mock.MagicMock(labels=[f"component: {expected}"])))
            expected = expected.strip()
            actual = bug.whiteboard_component
            self.assertEqual(actual, expected.strip())

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

    def test_approximate_cutoff_timestamp(self):
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
        actual = bzutil.approximate_cutoff_timestamp(mock.ANY, koji_api, metas)
        self.assertEqual(datetime(2021, 7, 2, 2, 0, 0, 0, tzinfo=timezone.utc).timestamp(), actual)

        koji_api.getEvent.return_value = {"ts": datetime(2021, 7, 1, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp()}
        actual = bzutil.approximate_cutoff_timestamp(mock.ANY, koji_api, metas)
        self.assertEqual(datetime(2021, 7, 1, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp(), actual)

        koji_api.getEvent.return_value = {"ts": datetime(2021, 7, 4, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp()}
        actual = bzutil.approximate_cutoff_timestamp(mock.ANY, koji_api, [])
        self.assertEqual(datetime(2021, 7, 4, 0, 0, 0, 0, tzinfo=timezone.utc).timestamp(), actual)


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
