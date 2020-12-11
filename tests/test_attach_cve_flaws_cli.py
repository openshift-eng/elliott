import unittest
from flexmock import flexmock
from click.testing import CliRunner
import elliottlib.cli.attach_cve_flaws_cli as attach_module
from elliottlib.cli.attach_cve_flaws_cli import attach_cve_flaws_cli
from bugzilla import Bugzilla


class TestAttachCVEFlawsCli(unittest.TestCase):
    def test_attach_cve_flaws_with_advisory(self):
        # mock runtime config object
        runner = CliRunner()
        mock_runtime = flexmock(
            initialize=lambda: None,
            gitdata=flexmock(bz_server_url=lambda: 'url', bz_target_release=lambda: '4.5'),
            logger=flexmock(info= lambda *_: None)
        )

        # mock bugzilla object
        mock_bzapi = flexmock(
            getbugs=lambda: []
        )
        flexmock(Bugzilla).should_receive("__new__").and_return(mock_bzapi)

        # mock all external function calls
        flexmock(attach_module).should_receive("get_attached_tracker_bugs").and_return([])
        flexmock(attach_module).should_receive("get_corresponding_flaw_bugs").and_return([])

        # TODO: don't mock all external function calls
        # instead stub data that you expect
        # so that this can act like an integration test more or less

        # invoke command
        result = runner.invoke(attach_cve_flaws_cli, ['--advisory', '123'
                                                      'image',
                                                      '--dry-run'], obj=mock_runtime)

        # assert result.exit_code == 0
        # assert result.output == "output"
        print(result.exit_code, result.output)


if __name__ == "__main__":
    unittest.main()
