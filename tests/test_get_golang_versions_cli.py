import unittest, flexmock
from elliottlib.cli import get_golang_versions_cli
from elliottlib import errata


class TestGetGolangVersionsCli(unittest.TestCase):
    def test_get_advisory_golang_rpm(self):
        advisory_id = 123
        content_type = "rpm"
        nvrs = [
            ('openshift', 'v1.15', 'el8'),
            ('podman', 'v1.4', 'el7')
        ]
        flexmock(errata). \
            should_receive("get_all_advisory_nvrs"). \
            with_args(advisory_id). \
            and_return(nvrs)
        flexmock(errata). \
            should_receive("get_erratum_content_type"). \
            with_args(advisory_id). \
            and_return(content_type)

        get_golang_versions_cli.get_advisory_golang(advisory_id, "")
