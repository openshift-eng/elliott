import unittest
import mock
import flexmock
from bugzilla import Bugzilla
from errata_tool import Erratum
from elliottlib.runtime import Runtime
from click.testing import CliRunner
from elliottlib.cli.common import cli
from elliottlib.cli import attach_cve_flaws_cli
from elliottlib import attach_cve_flaws
from elliottlib import constants, util
from elliottlib import errata as erratalib


class TestAttachCVEFlawsCLI(unittest.TestCase):
    def test_attach_cve_flaws_cli_z(self):
        runner = CliRunner()
        # mock Runtime obj
        runtime = flexmock(
            initialize=lambda: None,
            gitdata=flexmock(bz_server_url=lambda: "bz"),
            logger=flexmock(
                info=lambda x: print(x),
                error=lambda x: print(x),
                debug=lambda x: print(x))
        )
        flexmock(Runtime, __new__=runtime)

        # mock bugzilla obj
        bzapi = flexmock()
        flexmock(Bugzilla, __new__=bzapi)

        # mock Errata obj
        errata = flexmock()
        flexmock(Erratum, __new__=errata)

        tracker_bugs = [
            flexmock(id=123, keywords=constants.TRACKER_BUG_KEYWORDS)
        ]
        flaw_bugs = [
            flexmock(id=1), flexmock(id=2)
        ]

        flexmock(attach_cve_flaws).\
            should_receive("get_tracker_bugs").\
            and_return(tracker_bugs)
        flexmock(util).\
            should_receive("get_target_release").\
            with_args(tracker_bugs).\
            and_return(('4.8.z', False))
        flexmock(attach_cve_flaws).\
            should_receive("get_corresponding_flaw_bugs").\
            and_return(flaw_bugs)
        flexmock(erratalib). \
            should_receive("filter_advisory_bugs"). \
            and_return(flaw_bugs)
        flexmock(attach_cve_flaws_cli).\
            should_receive("get_boilerplate").\
            and_return(None)
        flexmock(attach_cve_flaws_cli). \
            should_receive("get_updated_advisory_rhsa"). \
            and_return(None)
        flexmock(erratalib). \
            should_receive("add_bugs"). \
            and_return(None)

        result = runner.invoke(cli, ['--group=openshift-17.44', 'attach-cve-flaws', '-a', '123'])
        expected_output = '''found 1 tracker bugs attached to the advisory: [123]
current_target_release: 4.8.z
found 2 corresponding flaw bugs: [1, 2]
detected z-stream target release, every flaw bug is considered first-fix
2 out of 2 flaw bugs considered "first-fix"
'''
        self.assertEqual(expected_output, result.stdout)
        self.assertEqual(0, result.exit_code)

    def test_get_updated_advisory_rhsa(self):
        boilerplate = {
            'security_reviewer': 'some reviewer',
            'synopsis': 'some synopsis',
            'description': 'some description',
            'topic': "some topic {IMPACT}",
            'solution': 'some solution'
        }
        advisory = mock.Mock(
            errata_type="RHBA",
            cve_names="something",
            update=mock.Mock(),
            topic='some topic'
        )

        flaw_bugs = [
            mock.Mock(alias=['CVE-123'], severity='urgent'),
            mock.Mock(alias=['CVE-456'], severity='high')
        ]

        attach_cve_flaws_cli.get_updated_advisory_rhsa(
            mock.Mock(),
            boilerplate,
            advisory,
            flaw_bugs
        )

        advisory.update.assert_any_call(
            errata_type='RHSA',
            security_reviewer=boilerplate['security_reviewer'],
            synopsis=boilerplate['synopsis'],
            description=boilerplate['description'],
            topic=boilerplate['topic'].format(IMPACT="Low"),
            solution=boilerplate['solution'],
            security_impact='Low',
        )

        impact = 'Critical'
        advisory.update.assert_any_call(
            topic=boilerplate['topic'].format(IMPACT=impact)
        )
        advisory.update.assert_any_call(
            cve_names='something CVE-123 CVE-456'
        )
        advisory.update.assert_any_call(
            security_impact=impact
        )
