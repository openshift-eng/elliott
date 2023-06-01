import unittest

from unittest.mock import MagicMock, Mock
from unittest.mock import patch

from elliottlib.model import Model
from elliottlib.build_finder import BuildFinder


class TestPlashetBuilder(unittest.TestCase):
    @patch("elliottlib.build_finder.get_build_objects")
    def test_get_builds(self, get_build_objects: Mock):
        finder = BuildFinder(MagicMock())
        finder._build_cache = {
            1: {"id": 1, "build_id": 1, "nvr": "fake1-1.2.3-1.el8"},
            "bar-1.2.3-1.el8": {"id": 3, "build_id": 3, "nvr": "bar-1.2.3-1.el8"},
        }
        get_build_objects.return_value = [
            {"id": 2, "build_id": 2, "nvr": "fake2-1.2.3-1.el8"},
            {"id": 4, "build_id": 4, "nvr": "foo-1.2.3-1.el8", "epoch": "2"},
        ]
        actual = finder._get_builds([1, 2, "foo-1.2.3-1.el8:2", "bar-1.2.3-1.el8"])
        get_build_objects.assert_called_once()
        self.assertListEqual([b["id"] for b in actual], [1, 2, 4, 3])

    def test_cache_build(self):
        finder = BuildFinder(MagicMock())
        finder._build_cache = {
            1: {"id": 1, "build_id": 1, "nvr": "fake1-1.2.3-1.el8"},
            "bar-1.2.3-1.el8": {"id": 3, "build_id": 3, "nvr": "bar-1.2.3-1.el8"},
        }
        finder._cache_build({"id": 4, "build_id": 4, "nvr": "foo-1.2.3-1.el8", "epoch": "2"})
        self.assertEqual(set(finder._build_cache.keys()), {1, "bar-1.2.3-1.el8", 4, "foo-1.2.3-1.el8", "foo-1.2.3-1.el8:2"})

    def test_from_tag_with_assembly_disabled(self):
        koji_api = MagicMock()
        koji_api.listTagged.return_value = [
            {"id": 1, "build_id": 1, "nvr": "fake2-1.2.4-1.assembly.stream.el8", "name": "fake2", "release": "1.assembly.stream.el8", "tag_name": "fake-rhel-8-candidate"},
            {"id": 4, "build_id": 4, "nvr": "foo-1.2.3-1.assembly.stream.el8", "epoch": "2", "name": "foo", "release": "1.assembly.stream.el8", "tag_name": "fake-rhel-8-candidate"},
        ]
        finder = BuildFinder(koji_api)
        actual = finder.from_tag("fake-rhel-8-candidate", True, None, None)
        expected = {1, 4}
        self.assertEqual({b["id"] for b in actual.values()}, expected)

    def test_from_tag_with_assembly_enabled(self):
        koji_api = MagicMock()
        koji_api.listTagged.return_value = [
            {"id": 1, "build_id": 1, "nvr": "fake2-1.2.4-1.assembly.stream.el8", "name": "fake2", "release": "1.assembly.stream.el8", "tag_name": "fake-rhel-8-candidate"},
            {"id": 2, "build_id": 2, "nvr": "fake2-1.2.3-1.assembly.art1.el8", "name": "fake2", "release": "1.assembly.art1.el8", "tag_name": "fake-rhel-8-candidate"},
            {"id": 4, "build_id": 4, "nvr": "foo-1.2.3-1.assembly.stream.el8", "epoch": "2", "name": "foo", "release": "1.assembly.stream.el8", "tag_name": "fake-rhel-8-candidate"},
        ]
        finder = BuildFinder(koji_api)
        actual = finder.from_tag("fake-rhel-8-candidate", True, "art1", None)
        expected = {2, 4}
        self.assertEqual({b["id"] for b in actual.values()}, expected)

    def test_from_group_deps(self):
        finder = BuildFinder(MagicMock())
        group_config = Model({
            "dependencies": {
                "rpms": [
                    {"el8": "fake1-1.2.3-1.el8"},
                    {"el8": "fake2-1.2.3-1.el8"},
                    {"el7": "fake2-1.2.3-1.el7"},
                    {"el7": "fake2-1.2.3-1.el7"},
                ]
            }
        })
        finder._get_builds = MagicMock(return_value=[
            {"id": 1, "build_id": 1, "name": "fake1", "nvr": "fake1-1.2.3-1.el8"},
            {"id": 2, "build_id": 2, "name": "fake2", "nvr": "fake2-1.2.3-1.el8"},
        ])
        actual = finder.from_group_deps(8, group_config, {})
        self.assertEqual([b["nvr"] for b in actual.values()], ["fake1-1.2.3-1.el8", "fake2-1.2.3-1.el8"])
        finder._get_builds.assert_called_once()

    def test_from_group_deps_with_art_managed_rpms(self):
        finder = BuildFinder(MagicMock())
        group_config = Model({
            "dependencies": {
                "rpms": [
                    {"el8": "fake1-1.2.3-1.el8"},
                    {"el8": "fake2-1.2.3-1.el8"},
                    {"el8": "fake3-1.2.3-1.el8"},
                    {"el7": "fake2-1.2.3-1.el7"},
                    {"el7": "fake2-1.2.3-1.el7"},
                ]
            }
        })
        finder._get_builds = MagicMock(return_value=[
            {"id": 1, "build_id": 1, "name": "fake1", "nvr": "fake1-1.2.3-1.el8"},
            {"id": 2, "build_id": 2, "name": "fake2", "nvr": "fake2-1.2.3-1.el8"},
            {"id": 3, "build_id": 3, "name": "fake3", "nvr": "fake3-1.2.3-1.el8"},
        ])
        with self.assertRaises(ValueError) as ex:
            finder.from_group_deps(8, group_config, {"fake3": MagicMock(rpm_name="fake3")})
        self.assertIn("Group dependencies cannot have ART managed RPMs", str(ex.exception))
        finder._get_builds.assert_called_once()

    @patch("elliottlib.build_finder.assembly_metadata_config")
    def test_from_pinned_by_is(self, assembly_metadata_config: Mock):
        finder = BuildFinder(MagicMock())
        releases_config = Model()
        rpm_metas = {
            "fake1": MagicMock(rpm_name="fake1"),
            "fake2": MagicMock(rpm_name="fake2"),
        }
        meta_configs = {
            "fake1": Model({
                "is": {
                    "el8": "fake1-1.2.3-1.el8"
                }
            }),
            "fake2": Model({
                "is": {
                    "el8": "fake2-1.2.3-1.el8"
                }
            }),
        }
        finder._get_builds = MagicMock(return_value=[
            {"id": 1, "build_id": 1, "name": "fake1", "nvr": "fake1-1.2.3-1.el8"},
            {"id": 2, "build_id": 2, "name": "fake2", "nvr": "fake2-1.2.3-1.el8"},
        ])
        assembly_metadata_config.side_effect = lambda *args: meta_configs[args[3]]
        actual = finder.from_pinned_by_is(8, "art1", releases_config, rpm_metas)
        self.assertEqual([b["nvr"] for b in actual.values()], ["fake1-1.2.3-1.el8", "fake2-1.2.3-1.el8"])
        finder._get_builds.assert_called_once()

    @patch("elliottlib.build_finder.assembly_metadata_config")
    def test_from_image_member_deps(self, assembly_metadata_config: Mock):
        finder = BuildFinder(MagicMock())

        finder._get_builds = MagicMock(return_value=[
            {"id": 1, "build_id": 1, "name": "fake1", "nvr": "fake1-1.2.3-1.el8"},
            {"id": 2, "build_id": 2, "name": "fake2", "nvr": "fake2-1.2.3-1.el8"},
            {"id": 3, "build_id": 3, "name": "fake3", "nvr": "fake3-1.2.3-1.el8"},
        ])
        assembly_metadata_config.return_value = Model({
            "dependencies": {
                "rpms": [
                    {"el8": "fake1-1.2.3-1.el8"},
                    {"el8": "fake2-1.2.3-1.el8"},
                    {"el8": "fake3-1.2.3-1.el8"},
                    {"el7": "fake2-1.2.3-1.el7"},
                    {"el7": "fake2-1.2.3-1.el7"},
                ]
            }
        })
        image_meta = Model({
            "distgit_key": "fake-image",
        })
        actual = finder.from_image_member_deps(8, "art1", Model(), image_meta, {})
        self.assertEqual([b["nvr"] for b in actual.values()], ["fake1-1.2.3-1.el8", "fake2-1.2.3-1.el8", "fake3-1.2.3-1.el8"])
        finder._get_builds.assert_called_once_with(["fake1-1.2.3-1.el8", "fake2-1.2.3-1.el8", "fake3-1.2.3-1.el8"])
        assembly_metadata_config.assert_called_once()

    @patch("elliottlib.build_finder.assembly_rhcos_config")
    def test_from_rhcos_deps(self, assembly_rhcos_config: Mock):
        finder = BuildFinder(MagicMock())

        finder._get_builds = MagicMock(return_value=[
            {"id": 1, "build_id": 1, "name": "fake1", "nvr": "fake1-1.2.3-1.el8"},
            {"id": 2, "build_id": 2, "name": "fake2", "nvr": "fake2-1.2.3-1.el8"},
            {"id": 3, "build_id": 3, "name": "fake3", "nvr": "fake3-1.2.3-1.el8"},
        ])
        assembly_rhcos_config.return_value = Model({
            "dependencies": {
                "rpms": [
                    {"el8": "fake1-1.2.3-1.el8"},
                    {"el8": "fake2-1.2.3-1.el8"},
                    {"el8": "fake3-1.2.3-1.el8"},
                    {"el7": "fake2-1.2.3-1.el7"},
                    {"el7": "fake2-1.2.3-1.el7"},
                ]
            }
        })
        actual = finder.from_rhcos_deps(8, "art1", Model(), {})
        self.assertEqual([b["nvr"] for b in actual.values()], ["fake1-1.2.3-1.el8", "fake2-1.2.3-1.el8", "fake3-1.2.3-1.el8"])
        finder._get_builds.assert_called_once_with(["fake1-1.2.3-1.el8", "fake2-1.2.3-1.el8", "fake3-1.2.3-1.el8"])
        assembly_rhcos_config.assert_called_once()


if __name__ == '__main__':
    unittest.main()
