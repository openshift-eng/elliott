from __future__ import unicode_literals
import unittest
from elliottlib.cli.find_builds_cli import _attached_to_open_erratum_with_correct_pv, _nvrs_to_builds, _get_product_version
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
        builds.should_receive("attached_to_open_erratum").and_return(True)
        builds.should_receive("open_errata_id").and_return([12345])

        # expect return empty list []
        self.assertEqual([], _attached_to_open_erratum_with_correct_pv("image", [builds], fake_errata))

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
        builds.should_receive("attached_to_open_erratum").and_return(True)
        builds.should_receive("open_errata_id").and_return([12345])

        # expect return list with one build
        self.assertEqual([Build("test-1.1.1")], _attached_to_open_erratum_with_correct_pv("image", [builds], fake_errata))

    def test_get_product_version(self):
        """
        Test get_product_version testing the product_version get from brew list tag and product_version map
        """

        nvr1 = "logging-fluentd-container-v4.1.14-201908291507"
        nvr2 = "ironic-container-v4.2.7-201911150432"

        product_version_map = {"rhaos-4.1-rhel-8-candidate": "OSE-4.1-RHEL-8",
                               "rhaos-4.2-rhel-8-candidate": "OSE-4.2-RHEL-8",
                               "rhaos-4.1-rhel-7-candidate": "RHEL-7-OSE-4.1",
                               "rhaos-4.2-rhel-7-candidate": "RHEL-7-OSE-4.2",
                               "rhaos-3.11-rhel-7-candidate": "RHEL-7-OSE-3.11"
                               }

        def fake_listTags(nvr):
            if nvr == nvr1:
                return [{'arches': None, 'id': 14991, 'locked': False, 'maven_include_all': False, 'maven_support': False,
                         'name': 'rhaos-4.1-rhel-7-candidate', 'perm': None, 'perm_id': None}]
            if nvr == nvr2:
                return [{'arches': None, 'id': 14991, 'locked': False, 'maven_include_all': False, 'maven_support': False,
                         'name': 'rhaos-4.2-rhel-8-candidate', 'perm': None, 'perm_id': None}]

        with mock.patch("koji.ClientSession", spec=True) as MockSession:
            session = MockSession()
            session.listTags = mock.MagicMock(side_effect=fake_listTags)

            pv = _get_product_version(nvr1, product_version_map, session)
            self.assertEqual(pv, "RHEL-7-OSE-4.1")

            pv = _get_product_version(nvr2, product_version_map, session)
            self.assertEqual(pv, "OSE-4.2-RHEL-8")


if __name__ == "__main__":
    unittest.main()
