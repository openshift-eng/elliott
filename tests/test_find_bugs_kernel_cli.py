from io import StringIO
from unittest import IsolatedAsyncioTestCase
from unittest.mock import ANY, MagicMock, Mock, patch

import koji
from bugzilla import Bugzilla
from bugzilla.bug import Bug
from jira import JIRA, Issue

from elliottlib.assembly import AssemblyTypes
from elliottlib.cli.find_bugs_kernel_cli import FindBugsKernelCli
from elliottlib.config_model import KernelBugSweepConfig
from elliottlib.runtime import Runtime
from elliottlib.bzutil import JIRABugTracker


class TestFindBugsKernelCli(IsolatedAsyncioTestCase):
    def test_find_kmaint_trackers(self):
        jira_client = MagicMock(spec=JIRA)
        issues = [MagicMock(key="FOO-1"), MagicMock(key="FOO-1")]
        jira_client.search_issues.return_value = issues
        actual = FindBugsKernelCli._find_kmaint_trackers(jira_client, "FOO", ["label1", "label2"])
        self.assertEqual(actual, issues)
        expected_jql = 'project = FOO AND status != Closed AND labels = "label1" AND labels = "label2" ORDER BY created DESC'
        jira_client.search_issues.assert_called_once_with(expected_jql, maxResults=50)

    def test_get_and_filter_bugs(self):
        runtime = MagicMock()
        cli = FindBugsKernelCli(
            runtime=runtime, trackers=[], clone=True, reconcile=True, comment=True, dry_run=False)
        bz_client = MagicMock(spec=Bugzilla)
        bz_client.getbugs.return_value = [
            MagicMock(spec=Bug, id=1, weburl="irrelevant", cf_zstream_target_release=None),
            MagicMock(spec=Bug, id=2, weburl="irrelevant", cf_zstream_target_release="8.6.0"),
            MagicMock(spec=Bug, id=3, weburl="irrelevant", cf_zstream_target_release="9.2.0"),
            MagicMock(spec=Bug, id=4, weburl="irrelevant", cf_zstream_target_release="8.6.0"),
        ]
        bug_ids = [1, 2, 3, 4]
        bz_target_releases = ["8.6.0"]
        actual = cli._get_and_filter_bugs(bz_client, bug_ids, bz_target_releases)
        self.assertEqual([b.id for b in actual], [2, 4])
        bz_client.getbugs.assert_called_once_with(bug_ids)

    @patch("elliottlib.cli.find_bugs_kernel_cli.FindBugsKernelCli._get_and_filter_bugs")
    def test_find_bugs(self, _get_and_filter_bugs: Mock):
        runtime = MagicMock()
        cli = FindBugsKernelCli(
            runtime=runtime, trackers=[], clone=True, reconcile=True, comment=True, dry_run=False)
        bz_client = MagicMock(spec=Bugzilla)
        tracker = MagicMock(spec=Issue, key="TRACKER-1", fields=MagicMock(
            summary="foo-1.0.1-1.el8_6 and bar-1.0.1-1.el8_6 early delivery via OCP",
            description="Fixes bugzilla.redhat.com/show_bug.cgi?id=5 and bz6.",
        ))
        jira_client = MagicMock(spec=JIRA)
        jira_client.remote_links.return_value = [
            MagicMock(object=MagicMock(title="bz1", url="http://bugzilla.redhat.com/1")),
            MagicMock(object=MagicMock(title="fake2", url="https://bugzilla.redhat.com/2")),
            MagicMock(object=MagicMock(title="fake3", url="https://bugzilla.redhat.com/show_bug.cgi?id=3")),
            MagicMock(object=MagicMock(title="fake4", url="https://example.com/show_bug.cgi?id=4")),
        ]
        expected_bug_ids = [1, 2, 3, 5, 6]
        _get_and_filter_bugs.return_value = [
            MagicMock(spec=Bug, id=bug_id, cf_zstream_target_release="8.6.0")
            for bug_id in expected_bug_ids
        ]
        bz_target_releases = ["8.6.0"]
        actual = cli._find_bugs(jira_client, tracker, bz_client, bz_target_releases)
        self.assertEqual([b.id for b in actual], expected_bug_ids)
        _get_and_filter_bugs.assert_called_once_with(bz_client, expected_bug_ids, bz_target_releases)

    def test_clone_bugs1(self):
        # Test cloning a bug that has not already been cloned
        runtime = MagicMock()
        cli = FindBugsKernelCli(
            runtime=runtime, trackers=[], clone=True, reconcile=True, comment=True, dry_run=False)
        jira_client = MagicMock(spec=JIRA)
        bugs = [
            MagicMock(spec=Bug, id=1, weburl="https://example.com/1",
                      groups=["private"], priority="high",
                      summary="fake summary 1", description="fake description 1"),
        ]
        conf = KernelBugSweepConfig.TargetJiraConfig(
            project="TARGET-PROJECT",
            component="Target Component",
            version="4.14", target_release="4.14.z",
            candidate_brew_tag="fake-candidate", prod_brew_tag="fake-prod")
        jira_client.search_issues.return_value = []
        tracker = MagicMock(spec=Issue, key="TRACKER-1", fields=MagicMock(
            summary="foo-1.0.1-1.el8_6 and bar-1.0.1-1.el8_6 early delivery via OCP",
            description="Fixes bugzilla.redhat.com/show_bug.cgi?id=5 and bz6.",
        ))
        cli._tracker_map = {
            bug_id: tracker for bug_id in range(5)
        }
        actual = cli._clone_bugs(jira_client, bugs, conf)
        expected_fields = {
            "project": {"key": "TARGET-PROJECT"},
            "components": [{"name": "Target Component"}],
            "security": {'name': 'Red Hat Employee'},
            "priority": {"name": "Major"},
            "summary": "kernel[-rt]: fake summary 1 [rhocp-4.14.z]",
            "description": "Cloned from https://example.com/1 by OpenShift ART Team:\n----\nfake description 1",
            "issuetype": {"name": "Bug"},
            "versions": [{"name": "4.14"}],
            f"{JIRABugTracker.FIELD_TARGET_VERSION}": [{"name": "4.14.z"}],
            "labels": ["art:cloned-kernel-bug", "art:bz#1", "art:kmaint:TRACKER-1"]
        }
        jira_client.create_issue.assert_called_once_with(expected_fields)
        self.assertEqual([b for b in actual], [1])

    def test_clone_bugs2(self):
        # Test cloning a bug that has already been cloned
        runtime = MagicMock()
        cli = FindBugsKernelCli(
            runtime=runtime, trackers=[], clone=True, reconcile=True, comment=True, dry_run=False)
        jira_client = MagicMock(spec=JIRA)
        bugs = [
            MagicMock(spec=Bug, id=1, weburl="https://example.com/1",
                      groups=["private"], priority="high",
                      summary="fake summary 1", description="fake description 1"),
        ]
        conf = KernelBugSweepConfig.TargetJiraConfig(
            project="TARGET-PROJECT",
            component="Target Component",
            version="4.14", target_release="4.14.z",
            candidate_brew_tag="fake-candidate", prod_brew_tag="fake-prod")
        found_issues = [
            MagicMock(spec=Issue, **{"key": "BUG-1", "fields": MagicMock(), "fields.status.name": "New"}),
        ]
        jira_client.search_issues.return_value = found_issues
        tracker = MagicMock(spec=Issue, key="TRACKER-1", fields=MagicMock(
            summary="foo-1.0.1-1.el8_6 and bar-1.0.1-1.el8_6 early delivery via OCP",
            description="Fixes bugzilla.redhat.com/show_bug.cgi?id=5 and bz6.",
        ))
        cli._tracker_map = {
            bug_id: tracker for bug_id in range(5)
        }
        actual = cli._clone_bugs(jira_client, bugs, conf)
        expected_fields = {
            "project": {"key": "TARGET-PROJECT"},
            "components": [{"name": "Target Component"}],
            "security": {'name': 'Red Hat Employee'},
            "priority": {"name": "Major"},
            "summary": "kernel[-rt]: fake summary 1 [rhocp-4.14.z]",
            "description": "Cloned from https://example.com/1 by OpenShift ART Team:\n----\nfake description 1",
            "issuetype": {"name": "Bug"},
            "versions": [{"name": "4.14"}],
            f"{JIRABugTracker.FIELD_TARGET_VERSION}": [{"name": "4.14.z"}],
            "labels": ["art:cloned-kernel-bug", "art:bz#1", "art:kmaint:TRACKER-1"]
        }
        found_issues[0].update.assert_called_once_with(expected_fields)
        self.assertEqual([b for b in actual], [1])

    def test_print_report(self):
        report = {
            "kernel_bugs": [
                {"id": 2, "summary": "test bug 2", "status": "Verified", "tracker": "TRACKER-1"},
                {"id": 1, "summary": "test bug 1", "status": "Verified", "tracker": "TRACKER-1"},
            ],
            "clones": {
                1: ["BUG-1"],
            }
        }
        out = StringIO()
        FindBugsKernelCli._print_report(report, out=out)
        self.assertEqual(out.getvalue().strip(), """
TRACKER-1	1	BUG-1	Verified	test bug 1
TRACKER-1	2	N/A	Verified	test bug 2
""".strip())

    @patch("elliottlib.brew.get_builds_tags")
    def test_comment_on_tracker(self, get_builds_tags: Mock):
        runtime = MagicMock()
        cli = FindBugsKernelCli(
            runtime=runtime, trackers=[], clone=True, reconcile=True, comment=True, dry_run=False)
        jira_client = MagicMock(spec=JIRA)
        conf = KernelBugSweepConfig.TargetJiraConfig(
            project="TARGET-PROJECT",
            component="Target Component",
            version="4.14", target_release="4.14.z",
            candidate_brew_tag="fake-candidate", prod_brew_tag="fake-prod")
        tracker = MagicMock(spec=Issue, key="TRACKER-1", fields=MagicMock(
            summary="kernel-1.0.1-1.fake and kernel-rt-1.0.1-1.fake early delivery via OCP",
            description="Fixes bugzilla.redhat.com/show_bug.cgi?id=5 and bz6.",
        ))
        koji_api = MagicMock(spec=koji.ClientSession)
        get_builds_tags.return_value = [
            [{"name": "irrelevant-1"}, {"name": "fake-candidate"}],
            [{"name": "irrelevant-2"}, {"name": "fake-candidate"}],
        ]
        jira_client.comments.return_value = []

        # Test 1: making a comment
        cli._comment_on_tracker(jira_client, tracker, koji_api, conf)
        jira_client.add_comment.assert_called_once_with("TRACKER-1", "Build(s) ['kernel-1.0.1-1.fake', 'kernel-rt-1.0.1-1.fake'] was/were already tagged into fake-candidate.")

        # Test 2: not making a comment because a comment has been made
        jira_client.comments.return_value = [
            MagicMock(body="irrelevant 1"),
            MagicMock(body="Build(s) ['kernel-1.0.1-1.fake', 'kernel-rt-1.0.1-1.fake'] was/were already tagged into fake-candidate."),
            MagicMock(body="irrelevant 2"),
        ]
        jira_client.add_comment.reset_mock()
        cli._comment_on_tracker(jira_client, tracker, koji_api, conf)
        jira_client.add_comment.assert_not_called()

    def test_new_jira_fields_from_bug(self):
        bug = MagicMock(spec=Bug, id=12345, cf_zstream_target_release="8.6.0",
                        weburl="https://example.com/12345",
                        groups=[], priority="high",
                        summary="fake summary 12345", description="fake description 12345")
        tracker = MagicMock(spec=Issue, key="TRACKER-1", fields=MagicMock(
            summary="kernel-1.0.1-1.fake and kernel-rt-1.0.1-1.fake early delivery via OCP",
            description="Fixes bugzilla.redhat.com/show_bug.cgi?id=5 and bz6.",
        ))
        conf = KernelBugSweepConfig.TargetJiraConfig(
            project="TARGET-PROJECT",
            component="Target Component",
            version="4.14", target_release="4.14.z",
            candidate_brew_tag="fake-candidate", prod_brew_tag="fake-prod")

        # Test 1: new jira fields for a public bug
        actual = FindBugsKernelCli._new_jira_fields_from_bug(bug, "4.12.z", tracker.key, conf)
        expected = {
            "project": {"key": "TARGET-PROJECT"},
            "components": [{"name": "Target Component"}],
            "security": None,
            "priority": {"name": "Major"},
            "summary": "kernel[-rt]: fake summary 12345 [rhocp-4.12.z]",
            "description": "Cloned from https://example.com/12345 by OpenShift ART Team:\n----\nfake description 12345",
            "issuetype": {"name": "Bug"},
            "versions": [{"name": "4.12"}],
            f"{JIRABugTracker.FIELD_TARGET_VERSION}": [{"name": "4.12.z"}],
            "labels": ["art:cloned-kernel-bug", "art:bz#12345", "art:kmaint:TRACKER-1"],
        }
        self.assertEqual(actual, expected)

        # Test 2: new jira fields for a private bug
        bug.groups = ["private"]
        actual = FindBugsKernelCli._new_jira_fields_from_bug(bug, "4.12.z", tracker.key, conf)
        self.assertEqual(actual["security"], {'name': 'Red Hat Employee'})

    @patch("elliottlib.cli.find_bugs_kernel_cli.FindBugsKernelCli._print_report")
    @patch("elliottlib.cli.find_bugs_kernel_cli.FindBugsKernelCli._clone_bugs")
    @patch("elliottlib.cli.find_bugs_kernel_cli.FindBugsKernelCli._comment_on_tracker")
    @patch("elliottlib.cli.find_bugs_kernel_cli.FindBugsKernelCli._find_bugs")
    @patch("elliottlib.cli.find_bugs_kernel_cli.FindBugsKernelCli._find_kmaint_trackers")
    async def test_run_without_specified_trackers(
            self, _find_kmaint_trackers: Mock, _find_bugs: Mock, _comment_on_tracker: Mock,
            _clone_bugs: Mock, _print_report: Mock):
        runtime = MagicMock(
            autospec=Runtime, assembly_type=AssemblyTypes.STREAM,
        )
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
        _find_kmaint_trackers.return_value = [
            MagicMock(spec=Issue, key="TRACKER-1", fields=MagicMock(
                summary="kernel-1.0.1-1.fake and kernel-rt-1.0.1-1.fake early delivery via OCP",
                description="Fixes bugzilla.redhat.com/show_bug.cgi?id=5 and bz6.",
            ))
        ]
        _find_bugs.return_value = [
            MagicMock(spec=Bug, id=10001, cf_zstream_target_release="9.2.0", status="on_qa",
                      weburl="https://example.com/10001",
                      groups=[], priority="high",
                      summary="fake summary 10001", description="fake description 10001"),
            MagicMock(spec=Bug, id=10002, cf_zstream_target_release="9.2.0", status="on_qa",
                      weburl="https://example.com/10002",
                      groups=["private"], priority="high",
                      summary="fake summary 10002", description="fake description 10002"),
            MagicMock(spec=Bug, id=10003, cf_zstream_target_release="9.2.0", status="on_qa",
                      weburl="https://example.com/10003",
                      groups=["private"], priority="high",
                      summary="fake summary 10003", description="fake description 10003"),
        ]
        cli = FindBugsKernelCli(
            runtime=runtime, trackers=[], clone=True, reconcile=True, comment=True, dry_run=False)
        await cli.run()
        _comment_on_tracker.assert_called_once_with(ANY, _find_kmaint_trackers.return_value[0], ANY, ANY)
        _clone_bugs.assert_called_once_with(ANY, _find_bugs.return_value, ANY)

    @patch("elliottlib.cli.find_bugs_kernel_cli.FindBugsKernelCli._print_report")
    @patch("elliottlib.cli.find_bugs_kernel_cli.FindBugsKernelCli._clone_bugs")
    @patch("elliottlib.cli.find_bugs_kernel_cli.FindBugsKernelCli._comment_on_tracker")
    @patch("elliottlib.cli.find_bugs_kernel_cli.FindBugsKernelCli._find_bugs")
    @patch("elliottlib.cli.find_bugs_kernel_cli.FindBugsKernelCli._find_kmaint_trackers")
    async def test_run_with_specified_trackers(
            self, _find_kmaint_trackers: Mock, _find_bugs: Mock, _comment_on_tracker: Mock,
            _clone_bugs: Mock, _print_report: Mock):
        runtime = MagicMock(
            autospec=Runtime, assembly_type=AssemblyTypes.STREAM,
        )
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
        jira_client.issue.return_value = \
            MagicMock(spec=Issue, key="TRACKER-999", fields=MagicMock(
                summary="kernel-1.0.1-1.fake and kernel-rt-1.0.1-1.fake early delivery via OCP",
                description="Fixes bugzilla.redhat.com/show_bug.cgi?id=5 and bz6.",
            ))
        _find_bugs.return_value = [
            MagicMock(spec=Bug, id=10001, cf_zstream_target_release="9.2.0", status="on_qa",
                      weburl="https://example.com/10001",
                      groups=[], priority="high",
                      summary="fake summary 10001", description="fake description 10001"),
            MagicMock(spec=Bug, id=10002, cf_zstream_target_release="9.2.0", status="on_qa",
                      weburl="https://example.com/10002",
                      groups=["private"], priority="high",
                      summary="fake summary 10002", description="fake description 10002"),
            MagicMock(spec=Bug, id=10003, cf_zstream_target_release="9.2.0", status="on_qa",
                      weburl="https://example.com/10003",
                      groups=["private"], priority="high",
                      summary="fake summary 10003", description="fake description 10003"),
        ]
        cli = FindBugsKernelCli(
            runtime=runtime, trackers=["TRACKER-999"], clone=True, reconcile=True, comment=True, dry_run=False)
        await cli.run()
        _comment_on_tracker.assert_called_once_with(ANY, jira_client.issue.return_value, ANY, ANY)
        _clone_bugs.assert_called_once_with(ANY, _find_bugs.return_value, ANY)
        _find_kmaint_trackers.assert_not_called()
