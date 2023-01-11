import unittest
from flexmock import flexmock
from mock import patch, MagicMock, Mock
from datetime import datetime, timezone
from click.testing import CliRunner
from elliottlib.cli.find_bugs_sweep_cli import FindBugsMode
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from elliottlib.cli.find_bugs_sweep_cli import extras_bugs, get_assembly_bug_ids, categorize_bugs_by_type
from elliottlib.cli.common import cli, Runtime
import xmlrpc.client
import elliottlib.cli.find_bugs_sweep_cli as sweep_cli
import elliottlib.bzutil as bzutil
from elliottlib import errata
from elliottlib.cli import common
import traceback


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

        # common mocks
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(Runtime).should_receive("get_default_advisories").and_return({})
        flexmock(sweep_cli).should_receive("categorize_bugs_by_type").and_return({})

        # jira mocks
        jira_bug = flexmock(
            id='OCPBUGS-1',
            component='OLM',
            status='ON_QA',
            summary='summary',
            created_days_ago=lambda: 7,
        )
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(JIRABugTracker).should_receive("search").and_return([jira_bug])

        # bz mocks
        bz_bug = flexmock(
            id='BZ1',
            created_days_ago=lambda: 8,
            cf_pm_score='score',
            component='OLM',
            status='ON_QA',
            summary='summary'
        )

        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("search").and_return([bz_bug])

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--report'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)
        self.assertIn('BZ1', result.output)
        self.assertIn('OCPBUGS-1', result.output)

    def test_find_bugs_sweep_brew_event(self):
        runner = CliRunner()
        bugs = [flexmock(id='BZ1', status='ON_QA')]
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)

        # jira mocks
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(JIRABugTracker).should_receive("search").and_return(bugs)
        flexmock(JIRABugTracker).should_receive("filter_bugs_by_cutoff_event").and_return([])

        # common mocks
        ts = datetime(2021, 6, 30, 12, 30, 00, 0, tzinfo=timezone.utc).timestamp()
        flexmock(sweep_cli).should_receive("get_sweep_cutoff_timestamp").and_return(ts)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(Runtime).should_receive("get_default_advisories").and_return({})

        # bz mocks
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("search").and_return(bugs)
        flexmock(BugzillaBugTracker).should_receive("filter_bugs_by_cutoff_event").and_return([])

        result = runner.invoke(cli, ['-g', 'openshift-4.6', '--assembly', '4.6.52', 'find-bugs:sweep'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)

    def test_find_bugs_sweep_advisory_jira(self):
        runner = CliRunner()
        bugs = [flexmock(id='BZ1', is_tracker_bug=lambda: False, component='whatever', sub_component='whatever')]
        advisory_id = 123

        # common mocks
        flexmock(Runtime).should_receive("initialize")
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(Runtime).should_receive("get_default_advisories").and_return({})

        # jira mocks
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(JIRABugTracker).should_receive("search").and_return(bugs)
        flexmock(JIRABugTracker).should_receive("attach_bugs").with_args(advisory_id, [b.id for b in bugs],
                                                                         noop=False, verbose=False)

        # bz mocks
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("search").and_return(bugs)
        flexmock(BugzillaBugTracker).should_receive("attach_bugs").with_args(advisory_id, [b.id for b in bugs],
                                                                             noop=False, verbose=False)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--add', str(advisory_id)])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)

    def test_find_bugs_sweep_advisory_type(self):
        runner = CliRunner()
        bugs = [flexmock(id='BZ1')]

        # common mocks
        flexmock(Runtime).should_receive("initialize")
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(Runtime).should_receive("get_default_advisories").and_return({'image': 123})
        flexmock(sweep_cli).should_receive("categorize_bugs_by_type").and_return({"image": set(bugs)})

        # jira mocks
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(JIRABugTracker).should_receive("search").and_return([])
        flexmock(JIRABugTracker).should_receive("advisory_bug_ids").and_return([])
        flexmock(JIRABugTracker).should_receive("attach_bugs").and_return()

        # bz mocks
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("search").and_return(bugs)
        flexmock(BugzillaBugTracker).should_receive("attach_bugs").with_args(123, ['BZ1'], noop=False, verbose=False)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--use-default-advisory', 'image'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)

    def test_find_bugs_sweep_default_advisories(self):
        runner = CliRunner()
        image_bugs = [flexmock(id=1), flexmock(id=2)]
        rpm_bugs = [flexmock(id=3), flexmock(id=4)]
        extras_bugs = [flexmock(id=5), flexmock(id=6)]

        # common mocks
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(sweep_cli).should_receive("categorize_bugs_by_type").and_return({
            "image": set(image_bugs),
            "rpm": set(rpm_bugs),
            "extras": set(extras_bugs)
        })
        flexmock(Runtime).should_receive("get_default_advisories").and_return({'image': 123, 'rpm': 123, 'extras': 123,
                                                                              'metadata': 123})

        # bz mocks
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login")
        flexmock(BugzillaBugTracker).should_receive("search").and_return(image_bugs + rpm_bugs + extras_bugs)
        flexmock(BugzillaBugTracker).should_receive("attach_bugs").times(3).and_return()

        # jira mocks
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(JIRABugTracker).should_receive("search").and_return([])
        flexmock(JIRABugTracker).should_receive("attach_bugs").times(3).and_return()

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--into-default-advisories'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)


class TestCategorizeBugsByType(unittest.TestCase):
    def test_categorize_bugs_by_type(self):
        advisory_id_map = {'image': 1, 'rpm': 2, 'extras': 3, 'microshift': 4}
        bugs = [
            flexmock(id='OCPBUGS-1', is_tracker_bug=lambda: True, is_cve_in_summary=lambda: True, whiteboard_component='foo', component=''),
            flexmock(id='OCPBUGS-2', is_tracker_bug=lambda: True, is_cve_in_summary=lambda: True, whiteboard_component='bar', component=''),
            flexmock(id='OCPBUGS-3', is_tracker_bug=lambda: True, is_cve_in_summary=lambda: True, whiteboard_component='buzz', component=''),
            flexmock(id='OCPBUGS-4', is_tracker_bug=lambda: False, is_cve_in_summary=lambda: True, component=''),
            flexmock(id='OCPBUGS-5', is_tracker_bug=lambda: False, is_cve_in_summary=lambda: True, component=''),
            flexmock(id='OCPBUGS-6', is_tracker_bug=lambda: False, is_cve_in_summary=lambda: True, component='MicroShift')
        ]
        builds_map = {
            'image': {bugs[2].whiteboard_component: None},
            'rpm': {bugs[1].whiteboard_component: None},
            'extras': {bugs[0].whiteboard_component: None},
            'microshift': set(),
        }

        flexmock(sweep_cli).should_receive("extras_bugs").and_return({bugs[3]})
        for kind in advisory_id_map.keys():
            flexmock(errata).should_receive("get_advisory_nvrs").with_args(advisory_id_map[kind]).and_return(
                builds_map[kind])
        expected = {
            'rpm': {bugs[1]},
            'image': {bugs[4], bugs[2]},
            'extras': {bugs[3], bugs[0]},
            'metadata': set(),
            'microshift': {bugs[5]},
        }

        actual = categorize_bugs_by_type(bugs, advisory_id_map, 4)
        self.assertEqual(expected, actual)


class TestGenAssemblyBugIDs(unittest.TestCase):
    @patch("elliottlib.cli.find_bugs_sweep_cli.assembly_issues_config")
    def test_gen_assembly_bug_ids_jira(self, assembly_issues_config: Mock):
        assembly_issues_config.return_value = flexmock(include=[{"id": 1}, {"id": 'OCPBUGS-2'}],
                                                       exclude=[{"id": "2"}, {"id": 'OCPBUGS-3'}])
        runtime = flexmock(get_releases_config=lambda: None, assembly='foo')
        expected = ({"OCPBUGS-2"}, {"OCPBUGS-3"})
        actual = get_assembly_bug_ids(runtime, 'jira')
        self.assertEqual(actual, expected)

    @patch("elliottlib.cli.find_bugs_sweep_cli.assembly_issues_config")
    def test_gen_assembly_bug_ids_bz(self, assembly_issues_config: Mock):
        assembly_issues_config.return_value = flexmock(include=[{"id": 1}, {"id": 'OCPBUGS-2'}],
                                                       exclude=[{"id": "2"}, {"id": 'OCPBUGS-3'}])
        runtime = flexmock(get_releases_config=lambda: None, assembly='foo')
        expected = ({1}, {"2"})
        actual = get_assembly_bug_ids(runtime, 'bugzilla')
        self.assertEqual(actual, expected)


class TestExtrasBugs(unittest.TestCase):
    def test_payload_bug(self):
        bugs = [flexmock(id='123', component='Payload Component', sub_component='Subcomponent')]
        self.assertEqual(len(extras_bugs(bugs)), 0)

    def test_extras_bug(self):
        bugs = [flexmock(id='123', component='Metering Operator', sub_component='Subcomponent')]
        self.assertEqual(len(extras_bugs(bugs)), 1)

    def test_subcomponent_bug(self):
        bugs = [flexmock(id='123', component='Networking', sub_component='SR-IOV')]
        self.assertEqual(len(extras_bugs(bugs)), 1)

    def test_nonsubcomponent_bug(self):
        bugs = [flexmock(id='123', component='Networking', sub_component='Not SR-IOV')]
        self.assertEqual(len(extras_bugs(bugs)), 0)


if __name__ == '__main__':
    unittest.main()
