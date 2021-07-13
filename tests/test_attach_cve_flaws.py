import unittest
from flexmock import flexmock
from elliottlib import attach_cve_flaws, constants


class TestAttachCVEFlaws(unittest.TestCase):
    def test_is_tracker_bug(self):
        bug = flexmock(keywords=constants.TRACKER_BUG_KEYWORDS)
        expected = True
        actual = attach_cve_flaws.is_tracker_bug(bug)
        assert expected == actual

    def test_is_tracker_bug_fail(self):
        bug = flexmock(keywords=['SomeOtherKeyword'])
        expected = False
        actual = attach_cve_flaws.is_tracker_bug(bug)
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
        actual = attach_cve_flaws.get_tracker_bugs(bzapi, advisory)
        assert expected == actual


if __name__ == "main":
    unittest.main()
