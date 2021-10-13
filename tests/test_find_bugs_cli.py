import unittest
from flexmock import flexmock
import elliottlib.errata as errata_module
from elliottlib import util
from elliottlib.cli.find_bugs_cli import mode_list, extras_bugs, filter_bugs


class TestFindBugsCli(unittest.TestCase):
    def test_mode_list(self):
        advisory = 'foo'
        bugs = [flexmock(bug_id='bar')]
        report = False
        flags = []
        noop = False

        flexmock(util).should_receive('green_prefix')
        flexmock(errata_module).\
            should_receive("add_bugs_with_retry").\
            once()

        mode_list(advisory, bugs, report, flags, noop)


class TestExtrasBugs(unittest.TestCase):
    def test_payload_bug(self):
        bugs = [flexmock(bug_id='123', component='Payload Component', subcomponent='Subcomponent')]
        self.assertEqual(len(extras_bugs(bugs)), 0)

    def test_extras_bug(self):
        bugs = [flexmock(bug_id='123', component='Metering Operator', subcomponent='Subcomponent')]
        self.assertEqual(len(extras_bugs(bugs)), 1)

    def test_subcomponent_bug(self):
        bugs = [flexmock(bug_id='123', component='Networking', subcomponent='SR-IOV')]
        self.assertEqual(len(extras_bugs(bugs)), 1)

    def test_subcomponent_bug(self):
        bugs = [flexmock(bug_id='123', component='Networking', subcomponent='Not SR-IOV')]
        self.assertEqual(len(extras_bugs(bugs)), 0)


if __name__ == '__main__':
    unittest.main()
