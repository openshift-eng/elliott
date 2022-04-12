import unittest

from flexmock import flexmock
import elliottlib.errata as errata_module
from elliottlib import util
from elliottlib.cli.find_bugs_cli import extras_bugs
from mock import patch, MagicMock
from elliottlib.cli.find_bugs_cli import FindBugsMode
from elliottlib.bzutil import BugzillaBugTracker


class TestFindBugsCli(unittest.TestCase):
    @patch.object(BugzillaBugTracker, 'login', return_value=None, autospec=True)
    @patch.object(BugzillaBugTracker, 'search', return_value=[1, 2], autospec=True)
    def test_find_bugs_mode_search(self, mock_search: MagicMock, mock_login: MagicMock):
        config = {
            'target_release': ['4.3.0', '4.3.z'],
            'product': "product",
            'server': "server"
        }
        bug_tracker = BugzillaBugTracker(config)
        find_bugs = FindBugsMode(status=['foo', 'bar'])
        find_bugs.include_status(['alpha'])
        find_bugs.exclude_status(['foo'])
        bugs = find_bugs.search(bug_tracker_obj=bug_tracker)
        self.assertEqual([1, 2], bugs)
        mock_search.assert_called_once_with(bug_tracker, {'bar', 'alpha'}, verbose=False)


class TestExtrasBugs(unittest.TestCase):
    def test_payload_bug(self):
        bugs = [flexmock(id='123', component='Payload Component', subcomponent='Subcomponent')]
        self.assertEqual(len(extras_bugs(bugs)), 0)

    def test_extras_bug(self):
        bugs = [flexmock(id='123', component='Metering Operator', subcomponent='Subcomponent')]
        self.assertEqual(len(extras_bugs(bugs)), 1)

    def test_subcomponent_bug(self):
        bugs = [flexmock(id='123', component='Networking', subcomponent='SR-IOV')]
        self.assertEqual(len(extras_bugs(bugs)), 1)

    def test_subcomponent_bug(self):
        bugs = [flexmock(id='123', component='Networking', subcomponent='Not SR-IOV')]
        self.assertEqual(len(extras_bugs(bugs)), 0)


if __name__ == '__main__':
    unittest.main()
