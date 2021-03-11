import unittest
from flexmock import flexmock
import elliottlib.errata as errata_module
from elliottlib.cli.find_bugs_cli import mode_list, filter_bugs


class TestFindBugsCli(unittest.TestCase):
    def test_mode_list(self):
        advisory = 'foo'
        bugs = [flexmock(bug_id='bar')]
        report = False
        flags = []
        noop = False

        flexmock(errata_module).\
            should_receive("add_bugs_with_retry").\
            once()

        mode_list(advisory, bugs, report, flags, noop)


if __name__ == "main":
    unittest.main()
