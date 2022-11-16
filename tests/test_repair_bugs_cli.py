import traceback
import unittest
from click.testing import CliRunner
from elliottlib.cli.common import cli, Runtime
import elliottlib.cli.repair_bugs_cli
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from elliottlib.errata import Advisory
from flexmock import flexmock


class RepairBugsTestCase(unittest.TestCase):
    def test_repair_bugs(self):
        runner = CliRunner()
        bz_bug = flexmock(id=1, status="MODIFIED", summary="")
        jira_bug = flexmock(id="OCPBUGS-1", status="MODIFIED", summary="")
        flexmock(Runtime).should_receive("initialize")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_bug").with_args(1).and_return(bz_bug)
        flexmock(BugzillaBugTracker).should_receive("update_bug_status").once()

        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(JIRABugTracker).should_receive("get_bug").with_args("OCPBUGS-1").and_return(jira_bug)
        flexmock(JIRABugTracker).should_receive("update_bug_status").once()

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'repair-bugs', '--id', '1', '--id', 'OCPBUGS-1', '--to',
                                     'ON_QA', '-a', '99999'])
        self.assertEqual(result.exit_code, 0)

    def test_repair_placeholder_jira_bug(self):
        runner = CliRunner()
        bug = flexmock(id="OCPBUGS-1", status="MODIFIED", summary="Placeholder")
        flexmock(Runtime).should_receive("initialize")
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(JIRABugTracker).should_receive("get_bug").with_args("OCPBUGS-1").and_return(bug)
        flexmock(JIRABugTracker).should_receive("update_bug_status").once()
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'repair-bugs', '--close-placeholder', '--id', 'OCPBUGS-1',
                                     '--to', 'ON_QA', '-a', '99999'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)
        self.assertIn("1 bugs successfully modified", result.output)
        self.assertEqual(result.exit_code, 0)

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

    def test_repair_auto(self):
        runner = CliRunner()
        bug = flexmock(id=1, status="MODIFIED", summary="")
        jira_bug = flexmock(id="OCPBUGS-1", status="MODIFIED", summary="")

        flexmock(Runtime).should_receive("initialize")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("get_bug").with_args(1).and_return(bug)
        flexmock(BugzillaBugTracker).should_receive("update_bug_status").once()
        flexmock(BugzillaBugTracker).should_receive("add_comment").once()

        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(JIRABugTracker).should_receive("get_bug").with_args("OCPBUGS-1").and_return(jira_bug)
        flexmock(JIRABugTracker).should_receive("update_bug_status").once()
        flexmock(JIRABugTracker).should_receive("add_comment").once()

        advisory = flexmock(errata_bugs=[1], jira_issues=["OCPBUGS-1"])
        flexmock(Advisory).new_instances(advisory)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'repair-bugs', '--auto', '--to', 'ON_QA', '--comment',
                                     'close bug', '-a', '99999'])
        self.assertIn("1 bugs successfully modified", result.output)
        self.assertEqual(result.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
