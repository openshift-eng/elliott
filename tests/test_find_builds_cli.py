from __future__ import unicode_literals
import unittest
from elliottlib.cli.find_builds_cli import _filter_out_inviable_builds, _find_latest_builds, _find_shipped_builds
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

    def test_find_latest_builds(self):
        builds = [
            {"id": 13, "name": "a-container", "version": "v1.2.3", "release": "3.assembly.stream", "tag_name": "tag1"},
            {"id": 12, "name": "a-container", "version": "v1.2.3", "release": "2.assembly.hotfix_a", "tag_name": "tag1"},
            {"id": 11, "name": "a-container", "version": "v1.2.3", "release": "1.assembly.hotfix_a", "tag_name": "tag1"},
            {"id": 23, "name": "b-container", "version": "v1.2.3", "release": "3.assembly.test", "tag_name": "tag1"},
            {"id": 22, "name": "b-container", "version": "v1.2.3", "release": "2.assembly.hotfix_b", "tag_name": "tag1"},
            {"id": 21, "name": "b-container", "version": "v1.2.3", "release": "1.assembly.stream", "tag_name": "tag1"},
            {"id": 33, "name": "c-container", "version": "v1.2.3", "release": "3", "tag_name": "tag1"},
            {"id": 32, "name": "c-container", "version": "v1.2.3", "release": "2.assembly.hotfix_b", "tag_name": "tag1"},
            {"id": 31, "name": "c-container", "version": "v1.2.3", "release": "1", "tag_name": "tag1"},
        ]
        actual = _find_latest_builds(builds, "stream")
        self.assertEqual([13, 21, 33], [b["id"] for b in actual])

        actual = _find_latest_builds(builds, "hotfix_a")
        self.assertEqual([12, 21, 33], [b["id"] for b in actual])

        actual = _find_latest_builds(builds, "hotfix_b")
        self.assertEqual([13, 22, 32], [b["id"] for b in actual])

        actual = _find_latest_builds(builds, "test")
        self.assertEqual([13, 23, 33], [b["id"] for b in actual])

        actual = _find_latest_builds(builds, None)
        self.assertEqual([13, 23, 33], [b["id"] for b in actual])

    @mock.patch("elliottlib.brew.get_builds_tags")
    def test_find_shipped_builds(self, get_builds_tags: mock.MagicMock):
        build_ids = [11, 12, 13]
        build_tags = [
            [{"name": "foo-candidate"}],
            [{"name": "bar-candidate"}, {"name": "bar-released"}],
            [],
        ]
        get_builds_tags.return_value = build_tags
        expected = {12}
        actual = _find_shipped_builds(build_ids, mock.MagicMock())
        self.assertEqual(expected, actual)
        get_builds_tags.assert_called_once_with(build_ids, mock.ANY)


if __name__ == "__main__":
    unittest.main()
