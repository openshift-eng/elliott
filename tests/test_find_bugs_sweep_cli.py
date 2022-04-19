import unittest
from flexmock import flexmock
from mock import patch, MagicMock
from click.testing import CliRunner
from elliottlib.cli.find_bugs_sweep_cli import FindBugsMode
from elliottlib.bzutil import BugzillaBugTracker
from elliottlib.cli.find_bugs_sweep_cli import extras_bugs
from elliottlib.cli.common import cli, Runtime
from elliottlib.cli.find_bugs_sweep_cli import FindBugsSweep
import elliottlib.cli.find_bugs_sweep_cli as sweep_cli
from elliottlib.cli import common


class TestFindBugsMode(unittest.TestCase):
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


class FindBugsSweepTestCase(unittest.TestCase):
    def test_find_bugs_sweep_report(self):
        runner = CliRunner()
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
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(FindBugsSweep).should_receive("search").and_return(bugs)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--report'])

        search_string1 = 'Searching for bugs with status MODIFIED ON_QA VERIFIED and target release(s): 4.6.z'
        search_string2 = 'Found 1 bugs: BZ1'
        search_string3 = 'BZ1           OLM                       ON_DEV       score   33  days   summary'
        self.assertIn(search_string1, result.output)
        self.assertIn(search_string2, result.output)
        self.assertIn(search_string3, result.output)
        self.assertEqual(result.exit_code, 0)

    def test_find_bugs_sweep_advisory(self):
        runner = CliRunner()
        bugs = [flexmock(id='BZ1')]
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(FindBugsSweep).should_receive("search").and_return(bugs)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(BugzillaBugTracker).should_receive("attach_bugs").with_args(123, [b.id for b in bugs], noop=False)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--add', '123'])

        search_string1 = 'Searching for bugs with status MODIFIED ON_QA VERIFIED and target release(s): 4.6.z'
        search_string2 = 'Found 1 bugs: BZ1'
        self.assertIn(search_string1, result.output)
        self.assertIn(search_string2, result.output)
        self.assertEqual(result.exit_code, 0)

    def test_find_bugs_sweep_advisory_type(self):
        runner = CliRunner()
        bugs = [flexmock(id='BZ1')]
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(FindBugsSweep).should_receive("search").and_return(bugs)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(sweep_cli).should_receive("categorize_bugs_by_type").and_return({"image": set(bugs)})
        flexmock(common).should_receive("find_default_advisory").and_return(123)
        flexmock(BugzillaBugTracker).should_receive("attach_bugs").with_args(123, ['BZ1'], noop=False)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--use-default-advisory', 'image'])

        search_string1 = 'Searching for bugs with status MODIFIED ON_QA VERIFIED and target release(s): 4.6.z'
        search_string2 = 'Found 1 bugs: BZ1'
        self.assertIn(search_string1, result.output)
        self.assertIn(search_string2, result.output)
        self.assertEqual(result.exit_code, 0)

    def test_find_bugs_sweep_default_advisories(self):
        runner = CliRunner()
        image_bugs = [flexmock(id=1), flexmock(id=2)]
        rpm_bugs = [flexmock(id=3), flexmock(id=4)]
        extras_bugs = [flexmock(id=5), flexmock(id=6)]
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(FindBugsSweep).should_receive("search").and_return(image_bugs + rpm_bugs + extras_bugs)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(sweep_cli).should_receive("categorize_bugs_by_type").and_return({
            "image": set(image_bugs),
            "rpm": set(rpm_bugs),
            "extras": set(extras_bugs)
        })
        flexmock(common).should_receive("find_default_advisory").times(3).and_return(123)
        flexmock(BugzillaBugTracker).should_receive("attach_bugs").times(3)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--into-default-advisories'])

        search_string1 = 'Searching for bugs with status MODIFIED ON_QA VERIFIED and target release(s): 4.6.z'
        search_string2 = 'Found 6 bugs: 1, 2, 3, 4, 5, 6'
        self.assertIn(search_string1, result.output)
        self.assertIn(search_string2, result.output)
        self.assertEqual(result.exit_code, 0)


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
