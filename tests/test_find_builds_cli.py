import unittest
from elliottlib.cli.find_builds_cli import _filter_out_inviable_builds, _find_shipped_builds
from elliottlib.brew import Build
from elliottlib import errata as erratalib
from flexmock import flexmock
import json
from unittest import mock


class TestFindBuildsCli(unittest.TestCase):
    """
    Test elliott find-builds command and internal functions
    """

    def test_filter_out_inviable_builds_inviable(self):
        metadata = json.loads('''{"release": "4.1", "kind": "rpm", "impetus": "cve"}''')
        flexmock(erratalib).should_receive("get_metadata_comments_json").and_return([metadata])

        builds = flexmock(Build(nvr="test-1.1.1", product_version="RHEL-7-OSE-4.1"))
        builds.should_receive("all_errata").and_return([{"id": 12345}])

        self.assertEqual([], _filter_out_inviable_builds([builds]))

    def test_filter_out_inviable_builds_viable(self):
        metadata = json.loads('''{"release": "4.1", "kind": "rpm", "impetus": "cve"}''')
        flexmock(erratalib).should_receive("get_metadata_comments_json").and_return([metadata])

        builds = flexmock(Build(nvr="test-1.1.1", product_version="RHEL-7-OSE-4.5"))
        builds.should_receive("all_errata").and_return([{"id": 12345}])

        self.assertEqual([Build("test-1.1.1")], _filter_out_inviable_builds([builds]))

    @mock.patch("elliottlib.brew.get_builds_tags")
    def test_find_shipped_builds(self, get_builds_tags: mock.MagicMock):
        build_ids = [11, 12, 13, 14, 15]
        build_tags = [
            [{"name": "foo-candidate"}],
            [{"name": "bar-candidate"}, {"name": "bar-released"}],
            [{"name": "bar-candidate"}, {"name": "RHBA-2077:1001-released"}],
            [{"name": "bar-candidate"}, {"name": "RHSA-2077:1002-released"}],
            [],
        ]
        get_builds_tags.return_value = build_tags
        expected = {13, 14}
        actual = _find_shipped_builds(build_ids, mock.MagicMock())
        self.assertEqual(expected, actual)
        get_builds_tags.assert_called_once_with(build_ids, mock.ANY)


if __name__ == "__main__":
    unittest.main()
