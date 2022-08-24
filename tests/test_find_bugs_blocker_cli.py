import unittest
import traceback
from click.testing import CliRunner
import elliottlib.cli.find_bugs_blocker_cli
from elliottlib.cli.common import cli, Runtime
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from flexmock import flexmock


class FindBugsBlockerTestCase(unittest.TestCase):
    def test_find_bugs_blocker(self):
        # mock init
        runner = CliRunner()
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login").and_return(None)

        bz_bug = flexmock(
            id=1, created_days_ago=lambda: 33,
            cf_pm_score='score', component='OLM',
            status='ON_DEV', summary='summary'
        )

        jira_bug = flexmock(
            id='OCPBUGS-1', created_days_ago=lambda: 34,
            cf_pm_score='score', component='OLM',
            status='ON_QA', summary='summary'
        )

        flexmock(JIRABugTracker).should_receive("blocker_search").and_return([jira_bug])
        flexmock(BugzillaBugTracker).should_receive("blocker_search").and_return([bz_bug])
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:blocker'])

        bz_output = '1             OLM                       ON_DEV       score   33  days   summary'
        jira_output = 'OCPBUGS-1     OLM                       ON_QA        score   34  days   summary'
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)
        self.assertEqual(result.exit_code, 0)
        self.assertIn(bz_output, result.output)
        self.assertIn(jira_output, result.output)


if __name__ == '__main__':
    unittest.main()
