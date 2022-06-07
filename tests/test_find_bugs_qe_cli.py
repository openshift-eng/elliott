import unittest
import os
from click.testing import CliRunner
from elliottlib.cli.common import cli, Runtime
from elliottlib.cli.find_bugs_qe_cli import FindBugsQE
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from flexmock import flexmock


class FindBugsQETestCase(unittest.TestCase):
    def test_find_bugs_qe_bz(self):
        runner = CliRunner()
        bug = flexmock(id=123, status="MODIFIED")
        bugs = [bug]
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({
            'target_release': ['4.6.z'], 'server': "bugzilla.redhat.com"
        })
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(FindBugsQE).should_receive("search").and_return(bugs)
        expected_comment = 'This bug is expected to ship in the next 4.6 release.'
        flexmock(BugzillaBugTracker).should_receive("update_bug_status").with_args(
            bug, 'ON_QA', comment=expected_comment, noop=True
        )

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:qe', '--noop'])
        search_string1 = 'Searching for bugs with status MODIFIED and target release(s): 4.6.z'
        search_string2 = 'Found 1 bugs: 123'
        self.assertIn(search_string1, result.output)
        self.assertIn(search_string2, result.output)
        self.assertEqual(result.exit_code, 0)

    def test_find_bugs_qe_jira(self):
        runner = CliRunner()
        bug = flexmock(id='OCPBUGS-123', status="MODIFIED")
        bugs = [bug]
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(JIRABugTracker).should_receive("get_config").and_return({
            'target_release': ['4.6.z'], 'server': "server"
        })
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        flexmock(FindBugsQE).should_receive("search").and_return(bugs)
        expected_comment = 'This bug is expected to ship in the next 4.6 release.'
        flexmock(JIRABugTracker).should_receive("update_bug_status").with_args(
            bug, 'ON_QA', comment=expected_comment, noop=True
        )

        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({
            'target_release': ['4.6.z'], 'server': "bugzilla.redhat.com"
        })
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(FindBugsQE).should_receive("search").and_return(bugs)
        flexmock(BugzillaBugTracker).should_receive("update_bug_status").with_args(
            bug, 'ON_QA', comment=expected_comment, noop=True
        )
        os.environ['USEJIRA'] = "True"
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:qe', '--noop'])
        search_string1 = 'Searching for bugs with status MODIFIED and target release(s): 4.6.z'
        search_string2 = 'Found 1 bugs: OCPBUGS-123'
        self.assertIn(search_string1, result.output)
        self.assertIn(search_string2, result.output)
        self.assertEqual(result.exit_code, 0)
        del(os.environ['USEJIRA'])


if __name__ == '__main__':
    unittest.main()
