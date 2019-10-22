#!/usr/bin/env python

import unittest
import bzutil
import constants
import flexmock
import bugzilla
from elliottlib import exceptions

hostname = "bugzilla.redhat.com"


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
        bugs = []
        for x in xrange(4):
            bugs.append(flexmock(severity=constants.BUG_SEVERITY[x]))
        impact = bzutil.get_highest_impact(bugs)
        self.assertEquals(impact, constants.SECURITY_IMPACT[3])

    def test_single_impact(self):
        bugs = []
        bugs.append(flexmock(severity=constants.BUG_SEVERITY[1]))
        impact = bzutil.get_highest_impact(bugs)
        self.assertEquals(impact, constants.SECURITY_IMPACT[1])


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
    def test_get_flaw_bugs(self):
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
        bz = bugzilla.Bugzilla(None)
        bzapi = flexmock(bz)
        bzapi.should_receive('getbugs').once().and_return(flaws)
        flaw_cve_map = bzutil.get_flaw_aliases(bzapi, [1])
        self.assertEquals(len(flaw_cve_map.keys()), 4)
        self.assertEquals(flaw_cve_map['4'], "")


# class TestSearchURL(unittest.TestCase):

#     def test_searchurl(self):
#         """Verify SearchURL works as expected"""
#         t = bugzilla.SearchURL()

#         t.addFilter("component", "notequals", "RFE")
#         t.addFilter("component", "notequals", "Documentation")
#         t.addFilter("component", "notequals", "Security")
#         t.addFilter("cf_verified", "notequals", "FailedQA")
#         print "url = {}".format(t)
#         assert False


if __name__ == "__main__":
    unittest.main()
