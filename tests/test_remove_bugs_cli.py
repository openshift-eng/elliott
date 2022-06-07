import unittest
import os
from click.testing import CliRunner
from elliottlib import errata
from elliottlib.cli import common
from elliottlib.cli.common import cli, Runtime
import elliottlib.cli.remove_bugs_cli
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from elliottlib import bzutil
from flexmock import flexmock


class RemoveBugsTestCase(unittest.TestCase):
    def test_remove_bugzilla_bug(self):
        runner = CliRunner()
        bugs = [flexmock(id=1), flexmock(id=2)]
        flexmock(Runtime).should_receive("initialize")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        Advisory = flexmock(errata_bugs=[1, 2])
        flexmock(Advisory).should_receive("removeBugs")
        flexmock(Advisory).should_receive("commit")
        flexmock(errata).should_receive("Advisory").and_return(Advisory)
        flexmock(BugzillaBugTracker).should_receive("get_bug").with_args(1).and_return(bugs[0])
        flexmock(BugzillaBugTracker).should_receive("get_bug").with_args(2).and_return(bugs[1])
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'remove-bugs', '--id', '1', '--id', '2', '-a', '99999'])
        self.assertIn("Found 2 bugs", result.output)
        self.assertIn("Removing bugs from advisory 99999", result.output)
        self.assertEqual(result.exit_code, 0)

    def test_remove_jira_bug(self):
        runner = CliRunner()
        # bugs = [flexmock(id=1), flexmock(id=2)]
        issues = [flexmock(key="OCPBUGS-3", id="OCPBUGS-3"), flexmock(key="OCPBUGS-4", id="OCPBUGS-4")]
        flexmock(Runtime).should_receive("initialize")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        Advisory = flexmock(errata_bugs=[1, 2])
        flexmock(Advisory).should_receive("removeBugs")
        flexmock(Advisory).should_receive("commit")
        flexmock(errata).should_receive("Advisory").and_return(Advisory)
        # flexmock(BugzillaBugTracker).should_receive("get_bug").with_args(1).and_return(bugs[0])
        # flexmock(BugzillaBugTracker).should_receive("get_bug").with_args(2).and_return(bugs[1])
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(errata).should_receive("Advisory").and_return(Advisory)
        flexmock(errata).should_receive("remove_multi_jira_issues")
        flexmock(JIRABugTracker).should_receive("get_bug").with_args("OCPBUGS-3").and_return(issues[0])
        flexmock(JIRABugTracker).should_receive("get_bug").with_args("OCPBUGS-4").and_return(issues[1])
        os.environ['USEJIRA'] = "True"
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'remove-bugs', '--id', 'OCPBUGS-3', '--id', 'OCPBUGS-4', '-a',
                                     '99999'])
        self.assertIn("Found 2 bugs:", result.output)
        self.assertIn("Removing bugs from advisory 99999", result.output)
        self.assertEqual(result.exit_code, 0)
        del(os.environ['USEJIRA'])

    def test_remove_all(self):
        runner = CliRunner()
        issues = [flexmock(key=3, id=3), flexmock(key=4, id=4)]
        flexmock(Runtime).should_receive("initialize")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(common).should_receive("find_default_advisory")
        Advisory = flexmock(errata_bugs=[1, 2])
        flexmock(Advisory).should_receive("removeBugs")
        flexmock(Advisory).should_receive("commit")
        flexmock(errata).should_receive("Advisory").and_return(Advisory)
        flexmock(errata).should_receive("get_jira_issue").and_return(issues)
        flexmock(errata).should_receive("remove_multi_jira_issues")
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'remove-bugs', '--all', '-a', '99999'])
        self.assertIn("Found 2 bugs", result.output)
        self.assertIn("Removing bugs from advisory 99999", result.output)
        self.assertEqual(result.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
