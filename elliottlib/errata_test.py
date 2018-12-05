"""
Test errata models/controllers
"""

import datetime
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

import exceptions
import constants
import errata
import bugzilla
import brew
import test_structures

from requests_kerberos import HTTPKerberosAuth


class TestBrew(unittest.TestCase):

    def test_parse_date(self):
        """Verify we can parse the date string returned from Errata Tool"""
        d_expected = '2018-03-02 15:19:08'
        d_out = datetime.datetime.strptime(test_structures.example_erratum['errata']['rhba']['created_at'], '%Y-%m-%dT%H:%M:%SZ')
        self.assertEqual(str(d_out), d_expected)


    def test_get_filtered_list(self):
        """Ensure we can generate an Erratum List"""
        with mock.patch('errata.requests.get') as get:
            response = mock.MagicMock(status_code=200)
            response.json.return_value = test_structures.example_erratum_filtered_list
            get.return_value = response
            res = errata.get_filtered_list()
            self.assertEqual(2, len(res))

    def test_get_filtered_list_limit(self):
        """Ensure we can generate a trimmed Erratum List"""
        with mock.patch('errata.requests.get') as get:
            response = mock.MagicMock(status_code=200)
            response.json.return_value = test_structures.example_erratum_filtered_list
            get.return_value = response
            res = errata.get_filtered_list(limit=1)
            self.assertEqual(1, len(res))

    def test_get_filtered_list_fail(self):
        """Ensure we notice invalid erratum lists"""
        with mock.patch('errata.requests.get') as get:
            response = mock.MagicMock(status_code=404)
            response.json.return_value = test_structures.example_erratum_filtered_list
            get.return_value = response
            with self.assertRaises(exceptions.ErrataToolError):
                errata.get_filtered_list()


if __name__ == '__main__':
    unittest.main()
