import unittest
import os
import traceback
from mock import patch
from click.testing import CliRunner
from elliottlib import errata
from elliottlib.cli import common
from elliottlib.cli.common import cli, Runtime
import elliottlib.cli.remove_bugs_cli
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from flexmock import flexmock


class RemoveBugsTestCase(unittest.TestCase):
    def test_remove_bugzilla_bug(self):
        runner = CliRunner()

        flexmock(Runtime).should_receive("initialize")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        advisory = flexmock(errata_bugs=[1, 2, 3])
        flexmock(errata).should_receive("Advisory").and_return(advisory)
        flexmock(BugzillaBugTracker).should_receive("remove_bugs").with_args(advisory, [1, 2], False)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'remove-bugs', '1', '2', '-a', '99999'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)
        self.assertIn("Found 2 bugs", result.output)
        self.assertIn("Removing bugs from advisory 99999", result.output)

    @patch.dict(os.environ, {"USEJIRA": "True"})
    def test_remove_jira_bug(self):
        runner = CliRunner()

        flexmock(Runtime).should_receive("initialize")
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        advisory = flexmock(jira_issues=['OCPBUGS-3', 'OCPBUGS-4', 'OCPBUGS-5'])
        flexmock(errata).should_receive("Advisory").and_return(advisory)
        flexmock(JIRABugTracker).should_receive("remove_bugs").with_args(advisory, ['OCPBUGS-3', 'OCPBUGS-4'], False)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'remove-bugs', 'OCPBUGS-3', 'OCPBUGS-4', '-a', '99999'])
        self.assertIn("Found 2 bugs", result.output)
        self.assertIn("Removing bugs from advisory 99999", result.output)
        self.assertEqual(result.exit_code, 0)

    def test_remove_all_bugzilla(self):
        runner = CliRunner()

        flexmock(Runtime).should_receive("initialize")
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        advisory = flexmock(errata_bugs=[1, 2, 3])
        flexmock(errata).should_receive("Advisory").and_return(advisory)
        flexmock(BugzillaBugTracker).should_receive("remove_bugs").with_args(advisory, [1, 2, 3], False)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'remove-bugs', '--all', '-a', '99999'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)
        self.assertIn("Found 3 bugs", result.output)
        self.assertIn("Removing bugs from advisory 99999", result.output)


if __name__ == '__main__':
    unittest.main()
