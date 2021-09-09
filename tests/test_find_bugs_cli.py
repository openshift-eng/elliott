import unittest
from flexmock import flexmock
import elliottlib.errata as errata_module
from elliottlib.cli.find_bugs_cli import mode_list, extras_bugs, filter_bugs


class TestFindBugsCli(unittest.TestCase):
    def test_mode_list(self):
        advisory = 'foo'
        bugs = [flexmock(bug_id='bar')]
        report = False
        flags = []
        noop = False
        bzapi = None

        flexmock(errata_module).\
            should_receive("filter_and_add_bugs").\
            once()

        mode_list(advisory, bugs, bzapi, report, flags, noop)


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


if __name__ == "main":
    unittest.main()
