import unittest
from elliottlib.bzutil import JIRABugTracker
from flexmock import flexmock
from datetime import datetime


class TestJIRABugTracker(unittest.TestCase):
    def test_update_bug_status_same(self):
        bug = flexmock(id=123, status="status1")
        flexmock(JIRABugTracker).should_receive("login").and_return(None)

        jira = JIRABugTracker({})
        jira.update_bug_status(bug, target_status='status1')

    def test_update_bug_status(self):
        bug = flexmock(id=123, status="status1")
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        client = flexmock()
        client.should_receive("transition_issue").with_args(bug.id, 'status2')

        jira = JIRABugTracker({})
        jira._client = client
        jira.update_bug_status(bug, target_status='status2', log_comment=False)

    def test_update_bug_status_with_comment(self):
        bug = flexmock(id=123, status="status1")
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        client = flexmock()
        client.should_receive("transition_issue").with_args(bug.id, 'status2')
        comment = 'Elliott changed bug status from status1 to status2.\ncomment'
        flexmock(JIRABugTracker).should_receive("add_comment").with_args(
            bug.id, comment, private=True, noop=False
        )

        jira = JIRABugTracker({})
        jira._client = client
        jira.update_bug_status(bug, target_status='status2', comment='comment')

    def test_add_comment_private(self):
        bug = flexmock(id=123)
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        client = flexmock()
        client.should_receive("add_comment").with_args(
            bug.id, 'comment', visibility={'type': 'group', 'value': 'Red Hat Employee'}
        )

        jira = JIRABugTracker({})
        jira._client = client
        jira.add_comment(bug.id, 'comment', private=True)

    def test_filter_bugs_by_cutoff_event(self):
        all_bugs = [flexmock(id='1'), flexmock(id='2')]
        desired_statuses = ["MODIFIED", "ON_QA", "VERIFIED"]
        sweep_cutoff_timestamp = datetime(2021, 6, 30, 12, 30, 00, 0, tzinfo=timezone.utc).timestamp()
        flexmock(JIRABugTracker).should_receive("login").and_return(None)
        client = flexmock()
        client.should_receive("add_comment")

        jira = JIRABugTracker({})
        jira._client = client
        bugs = jira.filter_bugs_by_cutoff_event()



if __name__ == '__main__':
    unittest.main()
