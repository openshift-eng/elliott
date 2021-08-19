import unittest
import mock
import flexmock
from bugzilla import Bugzilla
from errata_tool import Erratum
from elliottlib.runtime import Runtime
from click.testing import CliRunner
from elliottlib.cli.common import cli
from elliottlib.cli import attach_cve_flaws_cli


class TestAttachCVEFlawsCLI(unittest.TestCase):
    def test_attach_cve_flaws_cli(self):
        runner = CliRunner()
        # mock Runtime obj
        runtime = flexmock(initialize=lambda: None, gitdata=flexmock(bz_server_url=lambda: "bz"))
        flexmock(Runtime, __new__=runtime)

        # mock bugzilla obj
        bzapi = flexmock()
        flexmock(Bugzilla, __new__=bzapi)

        # mock Errata obj
        errata = flexmock()
        flexmock(Erratum, __new__=errata)

        result = runner.invoke(cli, ['--group=openshift-17.44', 'attach-cve-flaws', '-a', 'foobar'])
        #self.assertEqual('', result.stderr)
        self.assertEqual('', result.exception)
        self.assertEqual("hello", result.stdout)
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
