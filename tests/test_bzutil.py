from datetime import datetime, timezone
import logging
import unittest
import xmlrpc.client

import flexmock
import mock

from elliottlib import bzutil, constants

hostname = "bugzilla.redhat.com"


class TestBZUtil(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_is_flaw_bug(self):
        bug = mock.MagicMock(product="Security Response", component="vulnerability")
        self.assertTrue(bzutil.is_flaw_bug(bug))
        bug = mock.MagicMock(product="foo", component="bar")
        self.assertFalse(bzutil.is_flaw_bug(bug))

    def test_get_whiteboard_component(self):
        bug = mock.MagicMock(whiteboard="foo")
        self.assertFalse(bzutil.get_whiteboard_component(bug))

        bug = mock.MagicMock(whiteboard="component: ")
        self.assertFalse(bzutil.get_whiteboard_component(bug))

        expected = "something"
        bug = mock.MagicMock(whiteboard=f"component: {expected}")
        actual = bzutil.get_whiteboard_component(bug)
        self.assertEqual(actual, expected)

    def test_get_bugs(self):
        bug_ids = [1, 2]
        expected = {
            1: mock.MagicMock(id=1),
            2: mock.MagicMock(id=2),
        }
        bzapi = mock.MagicMock()
        bzapi.getbugs.return_value = [expected[bug_id] for bug_id in bug_ids]
        actual = bzutil.get_bugs(bzapi, bug_ids)
        self.assertEqual(expected, actual)

    def test_get_tracker_flaws_map(self):
        trackers = {
            1: mock.MagicMock(id=1, blocks=[11, 12]),
            2: mock.MagicMock(id=2, blocks=[21, 22]),
        }
        flaws_ids = [11, 12, 21, 22]
        flaws = {
            flaw_id: mock.MagicMock(id=flaw_id, product="Security Response", component="vulnerability")
            for flaw_id in flaws_ids
        }
        expected = {
            1: [flaws[11], flaws[12]],
            2: [flaws[21], flaws[22]],
        }
        with mock.patch("elliottlib.bzutil.get_bugs") as mock_get_bugs:
            mock_get_bugs.return_value = flaws
            actual = bzutil.get_tracker_flaws_map(None, trackers.values())
            self.assertEqual(expected, actual)

    def test_is_viable_bug(self):
        bug = mock.MagicMock()
        bug.status = "MODIFIED"
        self.assertTrue(bzutil.is_viable_bug(bug))
        bug.status = "ASSIGNED"
        self.assertFalse(bzutil.is_viable_bug(bug))

    def test_is_cve_tracker(self):
        bug = mock.MagicMock(keywords=[])
        self.assertFalse(bzutil.is_cve_tracker(bug))
        bug.keywords.append("Security")
        self.assertFalse(bzutil.is_cve_tracker(bug))
        bug.keywords.append("SecurityTracking")
        self.assertTrue(bzutil.is_cve_tracker(bug))

    def test_to_timestamp(self):
        dt = xmlrpc.client.DateTime("20210615T18:23:22")
        actual = bzutil.to_timestamp(dt)
        self.assertEqual(actual, 1623781402.0)

    def test_filter_bugs_by_cutoff_event(self):
        bzapi = mock.MagicMock()
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
        actual = bzutil.filter_bugs_by_cutoff_event(bzapi, bugs, desired_statuses, sweep_cutoff_timestamp)
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


class TestGetFlawBugs(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_get_flaw_bugs(self):
        t1 = flexmock(id='1', blocks=['b1', 'b2'])
        t2 = flexmock(id='2', blocks=['b3'])
        t3 = flexmock(id='3', blocks=[])
        flaw_bugs = bzutil.get_flaw_bugs([t1, t2, t3])
        for flaw in ['b1', 'b2', 'b3']:
            self.assertTrue(flaw in flaw_bugs)


class TestGetFlawAliases(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_get_flaw_aliases(self):
        CVE01 = flexmock(
            id='1',
            product='Security Response',
            component='vulnerability',
            alias=['CVE-0001-0001']
        )
        multiAlias = flexmock(
            id='2',
            product='Security Response',
            component='vulnerability',
            alias=['CVE-0001-0002', 'someOtherAlias']
        )
        multiAlias2 = flexmock(
            id='3',
            product='Security Response',
            component='vulnerability',
            alias=['someOtherAlias', 'CVE-0001-0003']
        )
        noAlias = flexmock(
            id='4',
            product='Security Response',
            component='vulnerability',
            alias=[]
        )
        nonFlaw = flexmock(
            id='5',
            product='Some Product',
            component='security',
            alias=['CVE-0001-0001', 'someOtherAlias']
        )
        flaws = [CVE01, multiAlias, multiAlias2, noAlias, nonFlaw]
        flaw_cve_map = bzutil.get_flaw_aliases(flaws)
        self.assertEqual(len(flaw_cve_map.keys()), 4)
        self.assertEqual(flaw_cve_map['4'], "")


if __name__ == "__main__":
    unittest.main()
