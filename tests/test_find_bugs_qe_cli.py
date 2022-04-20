import unittest
from click.testing import CliRunner
from elliottlib.cli.common import cli, Runtime
from elliottlib.cli.find_bugs_qe_cli import FindBugsQE
from elliottlib.bzutil import BugzillaBugTracker
from elliottlib import bzutil
from flexmock import flexmock


class FindBugsQETestCase(unittest.TestCase):
    def test_find_bugs_qe(self):
        runner = CliRunner()
        bugs = [flexmock(id=1, status="MODIFIED"), flexmock(id=2, status="MODIFIED")]
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z'], 'server': "bugzilla.redhat.com"})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("update_bug_status").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("target_release").and_return(["4.6.z"])
        flexmock(FindBugsQE).should_receive("search").and_return(bugs)
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:qe', '--noop'])
        search_string1 = 'Searching for bugs with status MODIFIED and target release(s): 4.6.z'
        search_string2 = 'Found 2 bugs: 1, 2'
        self.assertIn(search_string1, result.output)
        self.assertIn(search_string2, result.output)
        self.assertEqual(result.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
