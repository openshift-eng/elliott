import unittest
from elliottlib.bzutil import BugzillaBugTracker
from flexmock import flexmock


class BugzillaBugTrackerUpdateBugStatus(unittest.TestCase):
    def test_update_bug_status_same(self):
        bug = flexmock(id=123, status="status1")
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)

        bz = BugzillaBugTracker({})
        bz.update_bug_status(bug, target_status='status1')

    def test_update_bug_status(self):
        bug = flexmock(id=123, status="status1")
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        client = flexmock()
        mock_arg = 1
        client.should_receive("build_update").with_args(status='status2').ordered().and_return(mock_arg)
        client.should_receive("update_bugs").with_args([123], mock_arg).ordered()

        bz = BugzillaBugTracker({})
        bz._client = client
        bz.update_bug_status(bug, target_status='status2', log_comment=False)

    def test_update_bug_status_with_comment(self):
        bug = flexmock(id=123, status="status1")
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        client = flexmock()
        client.should_receive("build_update").ordered()
        client.should_receive("update_bugs").ordered()
        comment = 'Elliott changed bug status from status1 to status2.\ncomment'
        flexmock(BugzillaBugTracker).should_receive("add_comment").with_args(
            bug.id, comment, private=True, noop=False
        )

        bz = BugzillaBugTracker({})
        bz._client = client
        bz.update_bug_status(bug, target_status='status2', comment='comment')


class BugzillaBugTrackerUpdateAddComment(unittest.TestCase):
    def test_add_comment(self):
        bug = flexmock(id=123)
        flexmock(BugzillaBugTracker).should_receive("login").and_return(None)
        client = flexmock()
        mock_arg = 1
        client.should_receive("build_update").with_args(comment='comment', comment_private=True)\
            .ordered().and_return(mock_arg)
        client.should_receive("update_bugs").with_args([123], mock_arg).ordered()

        bz = BugzillaBugTracker({})
        bz._client = client
        bz.add_comment(bug.id, 'comment', private=True)


if __name__ == '__main__':
    unittest.main()
