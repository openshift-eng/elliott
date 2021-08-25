import unittest, flexmock
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
        logger = flexmock(debug=lambda x: print(x), info=lambda x: print(x))
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

        get_golang_versions_cli.get_advisory_golang(advisory_id, "", logger)
