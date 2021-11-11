import unittest
from flexmock import flexmock
from elliottlib.cli import get_golang_versions_cli
from elliottlib import errata as erratalib
from elliottlib import util as utillib


class TestGetGolangVersionsCli(unittest.TestCase):
    def test_get_advisory_golang_rpm(self):
        advisory_id = 123
        content_type = "rpm"
        nvrs = [
            ('openshift', 'v1.15', 'el8'),
            ('podman', 'v1.4', 'el7')
        ]
        nvrs_with_go = {
            'openshift': {
                'nvr': ('openshift', 'v1.15', 'el8'), 'go': '1.16'
            },
            'podman': {
                'nvr': ('podman', 'v1.4', 'el7'), 'go': '1.15'
            }
        }
        logger = get_golang_versions_cli.logger
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
            with_args(nvrs, logger).and_return(nvrs_with_go)
        flexmock(utillib). \
            should_receive("pretty_print_nvrs_go")

        get_golang_versions_cli.get_advisory_golang(advisory_id, "", logger)

    def test_get_nvr_golang(self):
        openshift = {'nvr': ('openshift', 'v1.15', 'el8'), 'go': '1.16'}
        podman = {'nvr': ('podman-container', 'v1.4', 'el7'), 'go': '1.15'}
        nvrs_list = ['-'.join(x['nvr']) for x in [openshift, podman]]
        rpm_nvrs = [openshift['nvr']]
        container_nvrs = [podman['nvr']]
        rpm_nvrs_go = {'openshift': openshift}
        container_nvrs_go = {'podman-container': podman}
        rpm_container_nvrs_go = {
            'openshift': openshift,
            'podman-container': podman
        }
        logger = get_golang_versions_cli.logger
        flexmock(utillib). \
            should_receive("get_golang_rpm_nvrs"). \
            with_args(rpm_nvrs, logger).and_return(rpm_nvrs_go)
        flexmock(utillib). \
            should_receive("get_golang_container_nvrs"). \
            with_args(container_nvrs, logger).and_return(container_nvrs_go)
        flexmock(utillib). \
            should_receive("pretty_print_nvrs_go"). \
            with_args(rpm_container_nvrs_go)

        get_golang_versions_cli.get_nvrs_golang(nvrs_list, logger)


if __name__ == '__main__':
    unittest.main()
