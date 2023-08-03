from io import StringIO
from unittest import TestCase
from unittest.mock import ANY, MagicMock, Mock, patch

import koji
from jira import JIRA, Issue
from errata_tool import Erratum
from errata_tool.build import Build

from elliottlib.config_model import KernelBugSweepConfig
from elliottlib import early_kernel


class TestEarlyKernel(TestCase):
    @patch("elliottlib.brew.get_builds_tags")
    def test_get_tracker_builds_and_tags(self, get_builds_tags: Mock):
        logger = MagicMock()
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

        nvrs, candidate, shipped = early_kernel.get_tracker_builds_and_tags(logger, tracker, koji_api, conf)
        self.assertEqual(["kernel-1.0.1-1.fake", "kernel-rt-1.0.1-1.fake"], nvrs)
        self.assertEqual("fake-candidate", candidate)
        self.assertFalse(shipped)

    @patch("elliottlib.early_kernel._advisories_for_builds")
    @patch("elliottlib.early_kernel._link_tracker_advisories")
    @patch("elliottlib.early_kernel.comment_on_tracker")
    @patch("elliottlib.early_kernel.move_jira")
    def test_process_shipped_tracker(self, move_jira: Mock, comment_on_tracker: Mock,
                                     _link_tracker_advisories: Mock, _advisories_for_builds: Mock):
        logger = MagicMock()
        jira_client = MagicMock(spec=JIRA)
        tracker = MagicMock(spec=Issue, key="TRACKER-1", fields=MagicMock(
            summary="kernel-1.0.1-1.fake and kernel-rt-1.0.1-1.fake early delivery via OCP",
            description="Fixes bugzilla.redhat.com/show_bug.cgi?id=5 and bz6.",
            status=Mock(),  # need to set "name" but can't in a mock - set later
        ))
        nvrs = ["kernel-1.0.1-1.fake", "kernel-rt-1.0.1-1.fake"]
        advisory = MagicMock(spec=Erratum)
        _advisories_for_builds.return_value = [advisory]
        _link_tracker_advisories.return_value = ["comment"]

        setattr(tracker.fields.status, "name", "CLOSED")
        early_kernel.process_shipped_tracker(logger, False, jira_client, tracker, nvrs, "tag")
        comment_on_tracker.assert_not_called()
        move_jira.assert_not_called()

        setattr(tracker.fields.status, "name", "New")
        early_kernel.process_shipped_tracker(logger, False, jira_client, tracker, nvrs, "tag")
        comment_on_tracker.assert_called_once_with(logger, False, jira_client, tracker, ["comment"])
        move_jira.assert_called_once_with(logger, False, jira_client, tracker, "CLOSED")

    @patch("elliottlib.early_kernel.Erratum")
    @patch("elliottlib.early_kernel.Build")
    def test_advisories_for_builds(self, build_clz: Mock, erratum_clz: Mock):
        build_clz.return_value = MagicMock(spec=Build, all_errata_ids=[42])
        advisory = erratum_clz.return_value = MagicMock(spec=Erratum, errata_state="SHIPPED_LIVE")

        self.assertEqual([advisory], early_kernel._advisories_for_builds(nvrs=["nvr-1", "nvr-2"]))
        erratum_clz.assert_called_once_with(errata_id=42)

        advisory.errata_state = "QE"
        self.assertEqual([], early_kernel._advisories_for_builds(nvrs=["nvr-1", "nvr-2"]))

    def test_link_tracker_advisories(self):
        tracker = MagicMock(spec=Issue, id=42)
        advisory = MagicMock(spec=Erratum, errata_name="RHBA-42", synopsis="shipped some stuff")
        jira_client = MagicMock(spec=JIRA)
        jira_client.remote_links.return_value = [
            MagicMock(raw=dict(object=dict(url="http://example.com"))),
        ]

        # test adding an existing link does not happen
        advisory.url.return_value = "http://example.com"
        msgs = early_kernel._link_tracker_advisories(
            MagicMock(), False, jira_client, [advisory], ["nvrs"], tracker
        )
        jira_client.add_simple_link.assert_not_called()
        self.assertEqual([], msgs)

        # test adding a new link does happen
        advisory.url.return_value = "http://different.example.com"
        msgs = early_kernel._link_tracker_advisories(
            MagicMock(), False, jira_client, [advisory], ["nvrs"], tracker
        )
        jira_client.add_simple_link.assert_called_once_with(tracker, ANY)
        self.assertEqual(1, len(msgs))

    def test_move_jira(self):
        runtime = MagicMock()
        jira_client = MagicMock(spec=JIRA)
        comment = "Test message"
        issue = MagicMock(spec=Issue, **{
            "key": "FOO-1", "fields": MagicMock(),
            "fields.labels": ["art:bz#1", "art:kmaint:KMAINT-1"],
            "fields.status.name": "New",
        })
        jira_client.current_user.return_value = "fake-user"
        early_kernel.move_jira(runtime.logger(), False, jira_client, issue, "MODIFIED", comment)
        jira_client.assign_issue.assert_called_once_with("FOO-1", "fake-user")
        jira_client.transition_issue.assert_called_once_with("FOO-1", "MODIFIED")

    def test_comment_on_tracker(self):
        logger = MagicMock()
        jira_client = MagicMock(spec=JIRA)
        tracker = MagicMock(spec=Issue, key="TRACKER-1", fields=MagicMock(
            summary="kernel-1.0.1-1.fake and kernel-rt-1.0.1-1.fake early delivery via OCP",
            description="Fixes bugzilla.redhat.com/show_bug.cgi?id=5 and bz6.",
        ))
        comment1, comment2 = "Comment 1", "Comment 2"

        # Test 1: making a comment
        jira_client.comments.return_value = [MagicMock(body=comment1)]
        early_kernel.comment_on_tracker(logger, False, jira_client, tracker, [comment2])
        jira_client.add_comment.assert_called_once_with("TRACKER-1", comment2)

        # Test 2: not making a comment because a comment has been made
        jira_client.comments.return_value = [
            MagicMock(body=comment1),
            MagicMock(body=comment2),
        ]
        jira_client.add_comment.reset_mock()
        early_kernel.comment_on_tracker(logger, False, jira_client, tracker, [comment2, comment1])
        jira_client.add_comment.assert_not_called()
