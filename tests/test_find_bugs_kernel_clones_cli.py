from io import StringIO
from unittest import IsolatedAsyncioTestCase
from unittest.mock import ANY, MagicMock, Mock, patch

import koji
from jira import JIRA, Issue

from elliottlib.assembly import AssemblyTypes
from elliottlib.cli.find_bugs_kernel_clones_cli import FindBugsKernelClonesCli
from elliottlib.config_model import KernelBugSweepConfig
from elliottlib.bzutil import JIRABugTracker


class TestFindBugsKernelClonesCli(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._config = KernelBugSweepConfig.parse_obj({
            "tracker_jira": {
                "project": "KMAINT",
                "labels": ["early-kernel-track"],
            },
            "bugzilla": {
                "target_releases": ["9.2.0"],
            },
            "target_jira": {
                "project": "OCPBUGS",
                "component": "RHCOS",
                "version": "4.14",
                "target_release": "4.14.0",
                "candidate_brew_tag": "rhaos-4.14-rhel-9-candidate",
                "prod_brew_tag": "rhaos-4.14-rhel-9",
            },
        })

    def test_get_jira_issues(self):
        runtime = MagicMock()
        cli = FindBugsKernelClonesCli(
            runtime=runtime, trackers=[], issues=[], move=True, comment=True, dry_run=False)
        jira_client = MagicMock(spec=JIRA)
        component = MagicMock()
        component.configure_mock(name="RHCOS")
        target_release = MagicMock()
        target_release.configure_mock(name="4.14.0")
        jira_client.issue.side_effect = lambda key: MagicMock(spec=Issue, **{
            "key": key,
            "fields": MagicMock(),
            "fields.labels": ["art:cloned-kernel-bug"],
            "fields.project.key": "OCPBUGS",
            "fields.components": [component],
            f"fields.{JIRABugTracker.FIELD_TARGET_VERSION}": [target_release],
        })
        actual = cli._get_jira_issues(jira_client, ["FOO-1", "FOO-2", "FOO-3"], self._config)
        self.assertEqual([issue.key for issue in actual], ["FOO-1", "FOO-2", "FOO-3"])

    def test_search_for_jira_issues(self):
        jira_client = MagicMock(spec=JIRA)
        trackers = ["TRACKER-1", "TRACKER-2"]
        jira_client.search_issues.return_value = [
            MagicMock(key="FOO-1"),
            MagicMock(key="FOO-2"),
            MagicMock(key="FOO-3"),
        ]
        actual = FindBugsKernelClonesCli._search_for_jira_issues(jira_client, trackers, self._config)
        expected_jql = 'labels = art:cloned-kernel-bug AND project = OCPBUGS AND component = RHCOS AND "Target Version" = "4.14.0" AND (labels = art:kmaint:TRACKER-1 OR labels = art:kmaint:TRACKER-2) order by created DESC'
        jira_client.search_issues.assert_called_once_with(expected_jql, maxResults=0)
        self.assertEqual([issue.key for issue in actual], ["FOO-1", "FOO-2", "FOO-3"])

    @patch("elliottlib.cli.find_bugs_kernel_clones_cli.FindBugsKernelClonesCli._move_jira")
    @patch("elliottlib.brew.get_builds_tags")
    def test_update_jira_issues(self, get_builds_tags: Mock, _move_jira: Mock):
        runtime = MagicMock()
        jira_client = MagicMock(spec=JIRA)
        jira_client.issue.return_value = MagicMock(spec=Issue, ** {
            "key": "KMAINT-1",
            "fields": MagicMock(),
            "fields.project.key": "KMAINT",
            "fields.labels": ['early-kernel-track'],
            "fields.summary": "kernel-1.0.1-1.fake and kernel-rt-1.0.1-1.fake early delivery via OCP",
            "fields.description": "Fixes bugzilla.redhat.com/show_bug.cgi?id=5 and bz6.",
        })
        cli = FindBugsKernelClonesCli(
            runtime=runtime, trackers=[], issues=[], move=True, comment=True, dry_run=False)
        issues = [
            MagicMock(spec=Issue, **{
                "key": "FOO-1", "fields": MagicMock(),
                "fields.labels": ["art:bz#1", "art:kmaint:KMAINT-1"],
                "fields.status.name": "New",
            }),
            MagicMock(spec=Issue, **{
                "key": "FOO-2", "fields": MagicMock(),
                "fields.labels": ["art:bz#2", "art:kmaint:KMAINT-1"],
                "fields.status.name": "Assigned",
            }),
            MagicMock(spec=Issue, **{
                "key": "FOO-3", "fields": MagicMock(),
                "fields.labels": ["art:bz#3", "art:kmaint:KMAINT-1"],
                "fields.status.name": "ON_QA",
            }),
        ]
        koji_api = MagicMock(spec=koji.ClientSession)

        get_builds_tags.return_value = [
            [{"name": "irrelevant-1"}, {"name": "rhaos-4.14-rhel-9-candidate"}],
            [{"name": "irrelevant-2"}, {"name": "rhaos-4.14-rhel-9-candidate"}],
        ]
        cli._update_jira_issues(jira_client, issues, koji_api, self._config)
        _move_jira.assert_any_call(jira_client, issues[0], "MODIFIED", ANY)
        _move_jira.assert_any_call(jira_client, issues[1], "MODIFIED", ANY)

    def test_move_jira(self):
        runtime = MagicMock()
        jira_client = MagicMock(spec=JIRA)
        cli = FindBugsKernelClonesCli(
            runtime=runtime, trackers=[], issues=[], move=True, comment=True, dry_run=False)
        comment = "Test message"
        issue = MagicMock(spec=Issue, **{
            "key": "FOO-1", "fields": MagicMock(),
            "fields.labels": ["art:bz#1", "art:kmaint:KMAINT-1"],
            "fields.status.name": "New",
        })
        jira_client.current_user.return_value = "fake-user"
        cli._move_jira(jira_client, issue, "MODIFIED", comment)
        jira_client.assign_issue.assert_called_once_with("FOO-1", "fake-user")
        jira_client.transition_issue.assert_called_once_with("FOO-1", "MODIFIED")

    def test_print_report(self):
        report = {
            "jira_issues": [
                {"key": "FOO-1", "summary": "test bug 1", "status": "Verified"},
                {"key": "FOO-2", "summary": "test bug 2", "status": "ON_QA"},
            ]
        }
        out = StringIO()
        FindBugsKernelClonesCli._print_report(report, out=out)
        self.assertEqual(out.getvalue().strip(), """
FOO-1	Verified	test bug 1
FOO-2	ON_QA	test bug 2
""".strip())

    @patch("elliottlib.cli.find_bugs_kernel_clones_cli.FindBugsKernelClonesCli._print_report")
    @patch("elliottlib.cli.find_bugs_kernel_clones_cli.FindBugsKernelClonesCli._get_jira_issues")
    @patch("elliottlib.cli.find_bugs_kernel_clones_cli.FindBugsKernelClonesCli._update_jira_issues")
    @patch("elliottlib.cli.find_bugs_kernel_clones_cli.FindBugsKernelClonesCli._search_for_jira_issues")
    async def test_run_without_specified_issues(self, _search_for_jira_issues: Mock, _update_jira_issues: Mock,
                                                _get_jira_issues: Mock, _print_report: Mock):
        runtime = MagicMock(assembly_type=AssemblyTypes.STREAM)
        runtime.gitdata.load_data.return_value = MagicMock(
            data={
                "kernel_bug_sweep": {
                    "tracker_jira": {
                        "project": "KMAINT",
                        "labels": ["early-kernel-track"],
                    },
                    "bugzilla": {
                        "target_releases": ["9.2.0"],
                    },
                    "target_jira": {
                        "project": "OCPBUGS",
                        "version": "4.14",
                        "target_release": "4.14.0",
                        "candidate_brew_tag": "rhaos-4.14-rhel-9-candidate",
                        "prod_brew_tag": "rhaos-4.14-rhel-9",
                    },
                },
            }
        )
        jira_client = runtime.bug_trackers.return_value._client
        found_issues = [
            MagicMock(spec=Issue, **{
                "key": "FOO-1", "fields": MagicMock(),
                "fields.summary": "Fake bug 1",
                "fields.summary": "Fake bug 1",
                "fields.labels": ["art:bz#1", "art:kmaint:KMAINT-1"],
                "fields.status.name": "New",
            }),
            MagicMock(spec=Issue, **{
                "key": "FOO-2", "fields": MagicMock(),
                "fields.summary": "Fake bug 2",
                "fields.labels": ["art:bz#2", "art:kmaint:KMAINT-1"],
                "fields.status.name": "Assigned",
            }),
            MagicMock(spec=Issue, **{
                "key": "FOO-3", "fields": MagicMock(),
                "fields.summary": "Fake bug 3",
                "fields.labels": ["art:bz#3", "art:kmaint:KMAINT-1"],
                "fields.status.name": "ON_QA",
            }),
        ]
        _search_for_jira_issues.return_value = found_issues
        cli = FindBugsKernelClonesCli(
            runtime=runtime, trackers=[], issues=[], move=True, comment=True, dry_run=False)
        await cli.run()
        _update_jira_issues.assert_called_once_with(jira_client, found_issues, ANY, ANY)
        expected_report = {
            'jira_issues': [
                {'key': 'FOO-1', 'summary': 'Fake bug 1', 'status': 'New'},
                {'key': 'FOO-2', 'summary': 'Fake bug 2', 'status': 'Assigned'},
                {'key': 'FOO-3', 'summary': 'Fake bug 3', 'status': 'ON_QA'},
            ]
        }
        _print_report.assert_called_once_with(expected_report, ANY)

    @patch("elliottlib.cli.find_bugs_kernel_clones_cli.FindBugsKernelClonesCli._print_report")
    @patch("elliottlib.cli.find_bugs_kernel_clones_cli.FindBugsKernelClonesCli._get_jira_issues")
    @patch("elliottlib.cli.find_bugs_kernel_clones_cli.FindBugsKernelClonesCli._update_jira_issues")
    @patch("elliottlib.cli.find_bugs_kernel_clones_cli.FindBugsKernelClonesCli._search_for_jira_issues")
    async def test_run_with_specified_issues(self, _search_for_jira_issues: Mock, _update_jira_issues: Mock,
                                             _get_jira_issues: Mock, _print_report: Mock):
        runtime = MagicMock(assembly_type=AssemblyTypes.STREAM)
        runtime.gitdata.load_data.return_value = MagicMock(
            data={
                "kernel_bug_sweep": {
                    "tracker_jira": {
                        "project": "KMAINT",
                        "labels": ["early-kernel-track"],
                    },
                    "bugzilla": {
                        "target_releases": ["9.2.0"],
                    },
                    "target_jira": {
                        "project": "OCPBUGS",
                        "version": "4.14",
                        "target_release": "4.14.0",
                        "candidate_brew_tag": "rhaos-4.14-rhel-9-candidate",
                        "prod_brew_tag": "rhaos-4.14-rhel-9",
                    },
                },
            }
        )
        jira_client = runtime.bug_trackers.return_value._client
        found_issues = [
            MagicMock(spec=Issue, **{
                "key": "FOO-1", "fields": MagicMock(),
                "fields.summary": "Fake bug 1",
                "fields.summary": "Fake bug 1",
                "fields.labels": ["art:bz#1", "art:kmaint:KMAINT-1"],
                "fields.status.name": "New",
            }),
            MagicMock(spec=Issue, **{
                "key": "FOO-2", "fields": MagicMock(),
                "fields.summary": "Fake bug 2",
                "fields.labels": ["art:bz#2", "art:kmaint:KMAINT-1"],
                "fields.status.name": "Assigned",
            }),
            MagicMock(spec=Issue, **{
                "key": "FOO-3", "fields": MagicMock(),
                "fields.summary": "Fake bug 3",
                "fields.labels": ["art:bz#3", "art:kmaint:KMAINT-1"],
                "fields.status.name": "ON_QA",
            }),
        ]
        _get_jira_issues.return_value = found_issues
        cli = FindBugsKernelClonesCli(
            runtime=runtime, trackers=[], issues=["FOO-1", "FOO-2", "FOO-3"], move=True, comment=True, dry_run=False)
        await cli.run()
        _update_jira_issues.assert_called_once_with(jira_client, found_issues, ANY, ANY)
        expected_report = {
            'jira_issues': [
                {'key': 'FOO-1', 'summary': 'Fake bug 1', 'status': 'New'},
                {'key': 'FOO-2', 'summary': 'Fake bug 2', 'status': 'Assigned'},
                {'key': 'FOO-3', 'summary': 'Fake bug 3', 'status': 'ON_QA'},
            ]
        }
        _print_report.assert_called_once_with(expected_report, ANY)
