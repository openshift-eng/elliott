from __future__ import unicode_literals
import unittest
from elliottlib.cli.find_builds_cli import _filter_out_inviable_builds
from elliottlib.brew import Build
import elliottlib
import flexmock, json, mock


class TestFindBuildsCli(unittest.TestCase):
    """
    Test elliott find-builds command and internal functions
    """

    def test_attached_errata_failed(self):
        """
        Test the internal wrapper function _attached_to_open_erratum_with_correct_product_version
        attached_to_open_erratum = True, product_version is also the same:
            _attached_to_open_erratum_with_correct_product_version() should return []
        """
        metadata_json_list = []
        metadata = json.loads('''{"release": "4.1", "kind": "rpm", "impetus": "cve"}''')
        metadata_json_list.append(metadata)

        fake_errata = flexmock(model=elliottlib.errata, get_metadata_comments_json=lambda: 1234)
        fake_errata.should_receive("get_metadata_comments_json").and_return(metadata_json_list)

        builds = flexmock(Build(nvr="test-1.1.1", product_version="RHEL-7-OSE-4.1"))
        builds.should_receive("all_errata").and_return([{"id": 12345}])

        # expect return empty list []
        self.assertEqual([], _filter_out_inviable_builds("image", [builds], fake_errata))

    def test_attached_errata_succeed(self):
        """
        Test the internal wrapper function _attached_to_open_erratum_with_correct_product_version
        attached_to_open_erratum = True but product_version is not same:
            _attached_to_open_erratum_with_correct_product_version() should return [Build("test-1.1.1")]
        """
        metadata_json_list = []
        metadata = json.loads('''{"release": "4.1", "kind": "rpm", "impetus": "cve"}''')
        metadata_json_list.append(metadata)

        fake_errata = flexmock(model=elliottlib.errata, get_metadata_comments_json=lambda: 1234)
        fake_errata.should_receive("get_metadata_comments_json").and_return(metadata_json_list)

        builds = flexmock(Build(nvr="test-1.1.1", product_version="RHEL-7-OSE-4.5"))
        builds.should_receive("all_errata").and_return([{"id": 12345}])

        # expect return list with one build
        self.assertEqual([Build("test-1.1.1")], _filter_out_inviable_builds("image", [builds], fake_errata))


if __name__ == "__main__":
    unittest.main()
