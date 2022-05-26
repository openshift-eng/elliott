import unittest
import os
from flexmock import flexmock
from mock import patch, MagicMock
from datetime import datetime, timezone
from click.testing import CliRunner
from elliottlib.cli.find_bugs_sweep_cli import FindBugsMode
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from elliottlib.cli.find_bugs_sweep_cli import extras_bugs
from elliottlib.cli.common import cli, Runtime
import xmlrpc.client
import elliottlib.cli.find_bugs_sweep_cli as sweep_cli
import elliottlib.bzutil as bzutil
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
        bugs = [
            flexmock(
                id='BZ1',
                creation_time=xmlrpc.client.DateTime("20210630T12:29:00"),
                target_release=['4.6.z'],
                cf_pm_score='score',
                component='OLM',
                status='ON_QA',
                summary='summary',
                keywords=''
            )
        ]
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        client = flexmock()
        flexmock(BugzillaBugTracker).should_receive("login").and_return(client)
        client.should_receive("url_to_query").and_return({})
        client.should_receive("query").and_return(bugs)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(bzutil).should_receive("datetime_now").and_return(datetime(2022, 1, 21, tzinfo=timezone.utc))

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--report'])
        search_string1 = 'Searching for bugs with status MODIFIED ON_QA VERIFIED and target release(s): 4.6.z'
        search_string2 = 'Found 1 bugs: BZ1'
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)
        self.assertIn(search_string1, result.output)
        self.assertIn(search_string2, result.output)

    def test_find_bugs_sweep_brew_event(self):
        runner = CliRunner()
        bugs = [flexmock(id='BZ1', status='ON_QA')]
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("search").and_return(bugs)
        ts = datetime(2021, 6, 30, 12, 30, 00, 0, tzinfo=timezone.utc).timestamp()
        flexmock(sweep_cli).should_receive("get_sweep_cutoff_timestamp").and_return(ts)
        flexmock(BugzillaBugTracker).should_receive("filter_bugs_by_cutoff_event").and_return([])
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())

        result = runner.invoke(cli, ['-g', 'openshift-4.6', '--assembly', '4.6.52', 'find-bugs:sweep'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)

    def test_find_bugs_sweep_advisory(self):
        runner = CliRunner()
        bugs = [flexmock(id='BZ1')]
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("search").and_return(bugs)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(BugzillaBugTracker).should_receive("attach_bugs").with_args(123, [b.id for b in bugs], noop=False)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--add', '123'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)

    def test_find_bugs_sweep_advisory_type(self):
        runner = CliRunner()
        bugs = [flexmock(id='BZ1')]
        flexmock(Runtime).should_receive("initialize")
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("search").and_return(bugs)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(sweep_cli).should_receive("categorize_bugs_by_type").and_return({"image": set(bugs)})
        flexmock(common).should_receive("find_default_advisory").and_return(123)
        flexmock(BugzillaBugTracker).should_receive("attach_bugs").with_args(123, ['BZ1'], noop=False)

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
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("search").and_return(image_bugs + rpm_bugs + extras_bugs)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(sweep_cli).should_receive("categorize_bugs_by_type").and_return({
            "image": set(image_bugs),
            "rpm": set(rpm_bugs),
            "extras": set(extras_bugs)
        })
        flexmock(common).should_receive("find_default_advisory").times(3).and_return(123)
        flexmock(BugzillaBugTracker).should_receive("attach_bugs").times(3)

        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--into-default-advisories'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)

    def test_find_bugs_sweep_report_jira(self):
        runner = CliRunner()
        jirabugs = [
            flexmock(
                key='OCPBUGS-1',
                fields=flexmock(
                    components=[flexmock(name='OLM')],
                    status=flexmock(name='ON_QA'),
                    summary='summary',
                    created='2021-12-23T19:49:49.328+0000'
                )
            )
        ]
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        client = flexmock()
        flexmock(JIRABugTracker).should_receive("login").and_return(client)
        client.should_receive("search_issues").and_return(jirabugs)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(bzutil).should_receive("datetime_now").and_return(datetime(2022, 1, 21, tzinfo=timezone.utc))

        bzbugs = [
            flexmock(
                id='BZ1',
                creation_time=xmlrpc.client.DateTime("20210630T12:29:00"),
                target_release=['4.6.z'],
                cf_pm_score='score',
                component='OLM',
                status='ON_QA',
                summary='summary'
            )
        ]
        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(client)
        client.should_receive("url_to_query").and_return({})
        client.should_receive("query").and_return(bzbugs)
        os.environ['USEJIRA'] = "True"
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--report'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)
        search_string = 'Found 1 bugs: OCPBUGS-1'
        self.assertIn(search_string, result.output)
        del(os.environ['USEJIRA'])

    def test_find_bugs_sweep_brew_event_jira(self):
        runner = CliRunner()
        bugs = [flexmock(id='BZ1', status='ON_QA')]
        flexmock(Runtime).should_receive("initialize").and_return(None)
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(JIRABugTracker).should_receive("search").and_return(bugs)
        ts = datetime(2021, 6, 30, 12, 30, 00, 0, tzinfo=timezone.utc).timestamp()
        flexmock(sweep_cli).should_receive("get_sweep_cutoff_timestamp").and_return(ts)
        flexmock(JIRABugTracker).should_receive("filter_bugs_by_cutoff_event").and_return([])
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())

        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("search").and_return(bugs)
        flexmock(BugzillaBugTracker).should_receive("filter_bugs_by_cutoff_event").and_return([])
        os.environ['USEJIRA'] = "True"

        result = runner.invoke(cli, ['-g', 'openshift-4.6', '--assembly', '4.6.52', 'find-bugs:sweep'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)
        del(os.environ['USEJIRA'])

    def test_find_bugs_sweep_advisory_jira(self):
        runner = CliRunner()
        bugs = [flexmock(id='BZ1')]
        flexmock(Runtime).should_receive("initialize")
        flexmock(Runtime).should_receive("get_major_minor").and_return(4, 6)
        flexmock(JIRABugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(JIRABugTracker).should_receive("login")
        flexmock(JIRABugTracker).should_receive("search").and_return(bugs)
        flexmock(sweep_cli).should_receive("get_assembly_bug_ids").and_return(set(), set())
        flexmock(JIRABugTracker).should_receive("attach_bugs").with_args(123, [b.id for b in bugs], noop=False)

        flexmock(BugzillaBugTracker).should_receive("get_config").and_return({'target_release': ['4.6.z']})
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        flexmock(BugzillaBugTracker).should_receive("search").and_return(bugs)
        flexmock(BugzillaBugTracker).should_receive("attach_bugs").with_args(123, [b.id for b in bugs], noop=False)
        os.environ['USEJIRA'] = "True"
        result = runner.invoke(cli, ['-g', 'openshift-4.6', 'find-bugs:sweep', '--add', '123'])
        if result.exit_code != 0:
            exc_type, exc_value, exc_traceback = result.exc_info
            t = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.fail(t)
        del(os.environ['USEJIRA'])


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
