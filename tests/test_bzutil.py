import unittest
import mock
import flexmock
import bugzilla
from elliottlib import exceptions, constants, bzutil

hostname = "bugzilla.redhat.com"


class TestBZUtil(unittest.TestCase):
    def test_is_flaw_bug(self):
        bug = mock.MagicMock(product="Security Response", component="vulnerability")
        self.assertTrue(bzutil.is_flaw_bug(bug))
        bug = mock.MagicMock(product="foo", component="bar")
        self.assertFalse(bzutil.is_flaw_bug(bug))

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

    def test_lowest_to_highest_impact(self):
        trackers = [flexmock(id=index, severity=severity)
                    for index, severity in enumerate(constants.BUG_SEVERITY_NUMBER_MAP.keys())]
        tracker_flaws_map = {
            tracker.id: [] for tracker in trackers
        }
        impact = bzutil.get_highest_impact(trackers, tracker_flaws_map)
        self.assertEquals(impact, constants.SECURITY_IMPACT[4])

    def test_single_impact(self):
        bugs = []
        severity = "high"
        bugs.append(flexmock(severity=severity))
        impact = bzutil.get_highest_impact(bugs, None)
        self.assertEquals(impact, constants.SECURITY_IMPACT[constants.BUG_SEVERITY_NUMBER_MAP[severity]])

    def test_impact_for_tracker_with_unspecified_severity(self):
        bugs = []
        severity = "unspecified"
        bugs.append(flexmock(id=123, severity=severity))
        tracker_flaws_map = {
            123: [flexmock(id=123, severity="medium")],
        }
        impact = bzutil.get_highest_impact(bugs, tracker_flaws_map)
        self.assertEquals(impact, "Moderate")
        tracker_flaws_map = {
            123: [flexmock(id=123, severity="unspecified")],
        }
        impact = bzutil.get_highest_impact(bugs, tracker_flaws_map)
        self.assertEquals(impact, "Low")


class TestGetTrackerBugs(unittest.TestCase):

    def test_get_tracker_bugs_with_non_trackers(self):
        one = flexmock(
            id='1',
            keywords=['Security', 'SecurityTracking']
        )
        two = flexmock(
            id='2',
            keywords=[]
        )
        bugs = [one, two]
        bz = bugzilla.Bugzilla(None)
        bzapi = flexmock(bz)
        bzapi.should_receive('getbugs').once().and_return(bugs)
        trackers = bzutil.get_tracker_bugs(bzapi, [1])
        self.assertEquals(trackers, [one])

    def test_get_tracker_bugs_empty(self):
        bugs = [None]
        bz = bugzilla.Bugzilla(None)
        bzapi = flexmock(bz)
        bzapi.should_receive('getbugs').once().and_return(bugs)
        self.assertRaises(exceptions.BugzillaFatalError, bzutil.get_tracker_bugs, bzapi, [1])


class TestGetFlawBugs(unittest.TestCase):
    def test_get_flaw_bugs(self):
        t1 = flexmock(id='1', blocks=['b1', 'b2'])
        t2 = flexmock(id='2', blocks=['b3'])
        t3 = flexmock(id='3', blocks=[])
        flaw_bugs = bzutil.get_flaw_bugs([t1, t2, t3])
        for flaw in ['b1', 'b2', 'b3']:
            self.assertTrue(flaw in flaw_bugs)


class TestGetFlawAliases(unittest.TestCase):
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
        self.assertEquals(len(flaw_cve_map.keys()), 4)
        self.assertEquals(flaw_cve_map['4'], "")


if __name__ == "__main__":
    unittest.main()
