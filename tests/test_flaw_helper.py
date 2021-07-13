import unittest
from flexmock import flexmock
from elliottlib import flaw_helper, constants


class TestFlawHelper(unittest.TestCase):
    def test_is_tracker_bug(self):
        bug = flexmock(keywords=constants.TRACKER_BUG_KEYWORDS)
        expected = True
        actual = flaw_helper.is_tracker_bug(bug)
        assert expected == actual

    def test_is_tracker_bug_fail(self):
        bug = flexmock(keywords=['SomeOtherKeyword'])
        expected = False
        actual = flaw_helper.is_tracker_bug(bug)
        assert expected == actual

    def test_get_tracker_bugs(self):
        bugs = [123, 456]
        valid_tracker = flexmock(keywords=constants.TRACKER_BUG_KEYWORDS)
        bug_objs = [
            valid_tracker,
            flexmock(keywords=[])
        ]

        advisory = flexmock(errata_bugs=bugs)
        bzapi = flexmock()
        (bzapi
         .should_receive("getbugs")
         .with_args(bugs, permissive=False)
         .and_return(bug_objs))

        expected = [valid_tracker]
        actual = flaw_helper.get_tracker_bugs(bzapi, advisory)
        assert expected == actual


if __name__ == "main":
    unittest.main()
