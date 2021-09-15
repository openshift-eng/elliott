import unittest
from flexmock import flexmock
import elliottlib.errata as errata_module
from elliottlib.cli.find_bugs_cli import mode_list, extras_bugs, filter_bugs
from click.testing import CliRunner
from elliottlib.cli.common import cli
from elliottlib.runtime import Runtime
from bugzilla import Bugzilla
from errata_tool import Erratum
from elliottlib import bzutil


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

    def test_find_bugs(self):
        runner = CliRunner()
        # mock Runtime obj
        runtime = flexmock(
            initialize=lambda mode: None,
            branch='rhaos-17.44',
            gitdata=flexmock(
                bz=flexmock(data={'target_release': ['4.8.0']}),
            ),
            logger=flexmock(
                info=lambda x: print(x),
                error=lambda x: print(x),
                debug=lambda x: print(x)),
            debug=True
        )
        flexmock(Runtime, __new__=runtime)

        bzapi = flexmock()
        flexmock(bzutil). \
            should_receive("get_bzapi"). \
            and_return(bzapi)

        result = runner.invoke(cli, ['--group=openshift-17.44', 'find-bugs', '--mode=sweep', '--cve-trackers',
                                     '--into-default-advisories'])
        expected_output = ''
        self.assertEqual('', result.exception)
        self.assertEqual(expected_output, result.stdout)
        # self.assertEqual(0, result.exit_code)


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
