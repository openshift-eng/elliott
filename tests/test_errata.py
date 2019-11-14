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
