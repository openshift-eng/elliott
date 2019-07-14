"""
Test errata models/controllers
"""

import datetime
import flexmock

# Import the right version for your python
import platform
(major, minor, patch) = platform.python_version_tuple()
if int(major) == 2 and int(minor) < 7:
    import unittest2 as unittest
else:
    import unittest

import errata
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


if __name__ == '__main__':
    unittest.main()
