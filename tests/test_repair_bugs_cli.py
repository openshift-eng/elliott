import unittest
import os
from click.testing import CliRunner
from elliottlib import errata
from elliottlib.cli import common
from elliottlib.cli.common import cli, Runtime
import elliottlib.cli.repair_bugs_cli
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from elliottlib import bzutil
from flexmock import flexmock


class RepairBugsTestCase(unittest.TestCase):
    def test_repair_bugzilla_bug(self):
        runner = CliRunner()
        bug = flexmock(id=1, status="MODIFIED", summary="")
        flexmock(Runtime).should_receive("initialize")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_bug").with_args(1).and_return(bug)
        flexmock(BugzillaBugTracker).should_receive("update_bug_status").once()
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'repair-bugs', '--id', '1', '--to', 'ON_QA', '-a', '99999'])
        self.assertIn("1 bugs successfully modified", result.output)
        self.assertEqual(result.exit_code, 0)

    def test_repair_jira_bug(self):
        runner = CliRunner()
        bug = flexmock(id=1, status="MODIFIED", summary="")
        flexmock(Runtime).should_receive("initialize")
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(JIRABugTracker).should_receive("get_bug").with_args(1).and_return(bug)
        flexmock(JIRABugTracker).should_receive("update_bug_status").once()
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_bug").with_args(1).and_return(bug)
        flexmock(BugzillaBugTracker).should_receive("update_bug_status").once()
        os.environ['USEJIRA'] = "True"
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'repair-bugs', '--id', '1', '--to', 'ON_QA', '-a', '99999'])
        self.assertIn("1 bugs successfully modified", result.output)
        self.assertEqual(result.exit_code, 0)
        del(os.environ['USEJIRA'])

    def test_repair_placeholder_jira_bug(self):
        runner = CliRunner()
        bug = flexmock(id=1, status="MODIFIED", summary="Placeholder")
        flexmock(Runtime).should_receive("initialize")
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(JIRABugTracker).should_receive("get_bug").with_args(1).and_return(bug)
        flexmock(JIRABugTracker).should_receive("update_bug_status").once()
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_bug").with_args(1).and_return(bug)
        flexmock(BugzillaBugTracker).should_receive("update_bug_status").once()
        os.environ['USEJIRA'] = "True"
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'repair-bugs', '--close-placeholder', '--id', '1', '--to', 'ON_QA', '-a', '99999'])
        self.assertIn("1 bugs successfully modified", result.output)
        self.assertEqual(result.exit_code, 0)
        del(os.environ['USEJIRA'])

    def test_repair_bugzilla_bug_with_comment(self):
        runner = CliRunner()
        bug = flexmock(id=1, status="MODIFIED", summary="")
        flexmock(Runtime).should_receive("initialize")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_bug").with_args(1).and_return(bug)
        flexmock(BugzillaBugTracker).should_receive("update_bug_status").once()
        flexmock(BugzillaBugTracker).should_receive("add_comment").once()
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'repair-bugs', '--id', '1', '--to', 'ON_QA', '--comment', 'close bug', '-a', '99999'])
        self.assertIn("1 bugs successfully modified", result.output)
        self.assertEqual(result.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
