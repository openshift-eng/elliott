import unittest
from flexmock import flexmock
from elliottlib.cli import get_golang_versions_cli
from elliottlib import errata as erratalib
from elliottlib import util as utillib
from elliottlib.cli.common import cli, Runtime
from click.testing import CliRunner


class TestGetGolangVersionsCli(unittest.TestCase):
    def test_get_golang_versions_advisory(self):
        runner = CliRunner()
        advisory_id = 123
        content_type = 'not docker'
        flexmock(Runtime).should_receive("initialize").and_return(None)
        nvrs = [('foo', 'v1', 'r'), ('bar', 'v1', 'r'), ('runc', 'v1', 'r'), ('podman', 'v1', 'r')]
        go_nvr_map = 'foobar'
        logger = get_golang_versions_cli._LOGGER
        flexmock(erratalib). \
            should_receive("get_all_advisory_nvrs"). \
            with_args(advisory_id). \
            and_return(nvrs)
        flexmock(erratalib). \
            should_receive("get_erratum_content_type"). \
            with_args(advisory_id). \
            and_return(content_type)
        flexmock(utillib). \
            should_receive("get_golang_rpm_nvrs"). \
            with_args([('runc', 'v1', 'r'), ('podman', 'v1', 'r')], logger).and_return(go_nvr_map)
        flexmock(utillib). \
            should_receive("pretty_print_nvrs_go").with_args(go_nvr_map)

        result = runner.invoke(cli, ['go', '--advisory', advisory_id, '--components', 'runc,podman'])
        self.assertEqual(result.exit_code, 0)

    def test_get_golang_versions_nvrs(self):
        runner = CliRunner()
        flexmock(Runtime).should_receive("initialize").and_return(None)
        go_nvr_map = 'foobar'
        logger = get_golang_versions_cli._LOGGER
        flexmock(utillib). \
            should_receive("get_golang_rpm_nvrs"). \
            with_args([('podman', '1.9.3', '3.rhaos4.6.el8')], logger).and_return(go_nvr_map)
        flexmock(utillib). \
            should_receive("get_golang_container_nvrs"). \
            with_args([('podman-container', '3.0.1', '6.el8')], logger).and_return(go_nvr_map)
        flexmock(utillib). \
            should_receive("pretty_print_nvrs_go").once()

        result = runner.invoke(cli, ['go', '--nvrs', 'podman-container-3.0.1-6.el8,podman-1.9.3-3.rhaos4.6.el8'])
        self.assertEqual(result.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
