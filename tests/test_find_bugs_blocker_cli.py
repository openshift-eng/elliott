import unittest
from click.testing import CliRunner
import elliottlib.cli.find_bugs_blocker_cli
from elliottlib.cli.common import cli, Runtime
from elliottlib.bzutil import BugzillaBugTracker
from flexmock import flexmock


class FindBugsBlockerTestCase(unittest.TestCase):
    def test_find_bugs_blocker(self):
        # mock init
        runner = CliRunner()
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)

        bugs = [
            flexmock(
                id='BZ1',
                created_days_ago=lambda: 33,
                cf_pm_score='score',
                component='OLM',
                status='ON_DEV',
                summary='summary'
            )
        ]

        flexmock(BugzillaBugTracker).should_receive("blocker_search")\
            .with_args({'NEW', 'ASSIGNED', 'POST', 'MODIFIED', 'ON_DEV', 'RELEASE_PENDING'}, verbose=False)\
            .and_return(bugs)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:blocker', '--exclude-status=ON_QA',
                                     '--include-status=RELEASE_PENDING'])

        expected_output = 'BZ1           OLM                       ON_DEV       score   33  days   summary'
        self.assertEqual(result.exit_code, 0)
        self.assertIn(expected_output, result.output)


if __name__ == '__main__':
    unittest.main()
