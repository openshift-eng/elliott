"""
Test errata models/controllers
"""

import datetime
import mock
import json
from contextlib import nested
import flexmock
from errata_tool import ErrataException

# Import the right version for your python
import platform
(major, minor, patch) = platform.python_version_tuple()
if int(major) == 2 and int(minor) < 7:
    import unittest2 as unittest
else:
    import unittest

import errata
import constants
from elliottlib import errata
import bugzilla
import brew
import test_structures
from elliottlib import exceptions


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

    # def test_add_bugs_with_retry(self):
    #     advs = testErratum(rt=2, ntt=2)
    #
    #     # adding bugs [1,2] but 1 is already attached to another advisory, it will retry
    #     # and add [2] again.
    #     flexmock(errata.Erratum).should_receive('addBugs').and_return([1,2]).and_return([2])
    #     flexmock(errata.Erratum).should_receive('commit').and_raise(ErrataException).and_return('')
    #     try:
    #         errata.add_bugs_with_retry(advs, [1, 2], False)
    #     except exceptions.ElliottFatalError:
    #         self.fail("raised ElliottFatalError unexpectedly!")
    #
    #     advs = testErratum(rt=0, ntt=2)
    #     with self.assertRaises(exceptions.ElliottFatalError) as cm:
    #         errata.add_bugs_with_retry(advs, [1, 2], True)
    #     self.assertEqual(str(cm.exception), "this is an exception from testErratum")

    def test_parse_exception_error_message(self):
        self.assertEqual([1685398], errata.parse_exception_error_message('Bug #1685398 The bug is filed already in RHBA-2019:1589.'))

        self.assertEqual([], errata.parse_exception_error_message('invalid format'))

        self.assertEqual([1685398, 1685399], errata.parse_exception_error_message('''Bug #1685398 The bug is filed already in RHBA-2019:1589.
        Bug #1685399 The bug is filed already in RHBA-2019:1589.'''))


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
