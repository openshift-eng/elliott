import unittest
import os
from mock import patch
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
        search_string1 = 'Found 1 bugs: 123'
        self.assertIn(search_string1, result.output)
        self.assertEqual(result.exit_code, 0)

    @patch.dict(os.environ, {"USEJIRA": "True"})
    def test_find_bugs_qe_jira(self):
        runner = CliRunner()
        jira_bug = flexmock(id='OCPBUGS-123', status="MODIFIED")
        bz_bug = flexmock(id='BZ-123', status="MODIFIED")

        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(JIRABugTracker).should_receive("get_config").and_return({
            'target_release': ['4.6.z'], 'server': "server"
        })
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        flexmock(JIRABugTracker).should_receive("search").and_return([jira_bug])
        expected_comment = 'This bug is expected to ship in the next 4.6 release.'
        flexmock(JIRABugTracker).should_receive("update_bug_status").with_args(
            jira_bug, 'ON_QA', comment=expected_comment, noop=True
        )

        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({
            'target_release': ['4.6.z'], 'server': "bugzilla.redhat.com"
        })
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("search").and_return([bz_bug])
        flexmock(BugzillaBugTracker).should_receive("update_bug_status").with_args(
            bz_bug, 'ON_QA', comment=expected_comment, noop=True
        )
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:qe', '--noop'])
        search_string1 = 'Found 1 bugs: OCPBUGS-123'
        search_string2 = 'Found 1 bugs: BZ-123'
        self.assertIn(search_string1, result.output)
        self.assertIn(search_string2, result.output)
        self.assertEqual(result.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
