"""
Test the brew related functions/classes
"""

from flexmock import flexmock
import platform
import unittest
from unittest import mock

from elliottlib import exceptions, constants, brew, errata
from tests import test_structures


class TestBrew(unittest.TestCase):
    def test_build_attached_to_open_erratum(self):
        """We can tell if a build is attached to any open erratum"""
        # Create Erratum(), create Build() using dict with all_errata
        # containing an object with 'id' matching Erratum.advisory_id
        b = brew.Build(nvr='template-service-broker-docker-v3.7.36-2',
                       body=test_structures.image_build_attached_open_json,
                       product_version='rhaos-test-7')
        self.assertTrue(b.attached_to_open_erratum)

    def test_build_attached_to_closed_erratum(self):
        """We can tell if a build is attached to any closed erratum"""
        # Use filter #1991: (Active; Product: RHOSE; sorted by newest)
        b = brew.Build(nvr='template-service-broker-docker-v3.7.36-2',
                       body=test_structures.image_build_attached_closed_json,
                       product_version='rhaos-test-7')
        self.assertTrue(b.attached_to_closed_erratum)

    def test_good_attached_brew_image_build(self):
        """We can create and process an attached image Build object"""
        b = brew.Build(nvr='template-service-broker-docker-v3.7.36-2',
                       body=test_structures.image_build_attached_json,
                       product_version='rhaos-test-7')

        self.assertEqual('template-service-broker-docker-v3.7.36-2', b.nvr)
        self.assertEqual('image', b.kind)
        self.assertEqual('tar', b.file_type)
        self.assertTrue(b.attached)

    def test_good_unattached_brew_image_build(self):
        """We can create and process an unattached image Build object"""
        b = brew.Build(nvr='cri-o-docker-v3.7.37-1',
                       body=test_structures.image_build_unattached_json,
                       product_version='rhaos-test-7')

        self.assertEqual('cri-o-docker-v3.7.37-1', b.nvr)
        self.assertEqual('image', b.kind)
        self.assertEqual('tar', b.file_type)
        self.assertFalse(b.attached)

    def test_good_attached_brew_rpm_build(self):
        """We can create and process an attached rpm Build object"""
        b = brew.Build(nvr='coreutils-8.22-21.el7',
                       body=test_structures.rpm_build_attached_json,
                       product_version='rhaos-test-7')

        self.assertEqual('coreutils-8.22-21.el7', b.nvr)
        self.assertEqual('rpm', b.kind)
        self.assertEqual('rpm', b.file_type)
        self.assertTrue(b.attached)

    def test_good_unattached_brew_rpm_build(self):
        """We can create and process an unattached rpm Build object"""
        b = brew.Build(nvr='ansible-service-broker-1.0.21-1.el7',
                       body=test_structures.rpm_build_unattached_json,
                       product_version='rhaos-test-7')

        self.assertEqual('ansible-service-broker-1.0.21-1.el7', b.nvr)
        self.assertEqual('rpm', b.kind)
        self.assertEqual('rpm', b.file_type)
        self.assertFalse(b.attached)

    def test_build_sorting(self):
        """Ensure we can sort a list of builds"""
        b1 = brew.Build(nvr='abcd-1.0.0')
        b2 = brew.Build(nvr='zyxw-1.0.0')
        # Same one as before for equality
        b3 = brew.Build(nvr='zyxw-1.0.0')

        self.assertGreater(b2, b1)
        self.assertLess(b1, b2)
        self.assertEqual(b2, b3)

    def test_build_display(self):
        """Verify brew Builds display correctly"""
        nvr = 'megafrobber-1.3.3-7'
        b = brew.Build(nvr=nvr)
        self.assertEqual(nvr, str(b))
        self.assertEqual("Build({nvr})".format(nvr=nvr), repr(b))

    def test_build_equality(self):
        """Ensure brew Builds are unique and can be tested for equality"""
        b1 = brew.Build(nvr='megafrobber-1.3.3-7')
        b2 = brew.Build(nvr='tuxracer-42')

        builds = set([])
        builds.add(str(b1))
        builds.add(str(b1))

        self.assertEqual(1, len(builds))
        self.assertTrue(b1 != b2)

    def test_rpm_build_json_formatting(self):
        """Ensure a brew Build returns proper JSON for API posting"""
        nvr = 'coreutils-8.22-21.el7'
        pv = 'rhaos-test-7'

        b = brew.Build(nvr=nvr,
                       body=test_structures.rpm_build_attached_json,
                       product_version=pv)

        expected_json = {
            'product_version': pv,
            'build': nvr,
            'file_types': ['rpm']
        }

        self.assertEqual(expected_json, b.to_json())

    def test_image_build_json_formatting(self):
        """Ensure a brew Build returns proper JSON for API posting"""
        nvr = 'template-service-broker-docker-v3.7.36-2'
        pv = 'rhaos-test-7'

        b = brew.Build(nvr=nvr,
                       body=test_structures.image_build_attached_json,
                       product_version=pv)

        expected_json = {
            'product_version': pv,
            'build': nvr,
            'file_types': ['tar']
        }

        self.assertEqual(expected_json, b.to_json())

    def test_get_brew_build_success(self):
        (flexmock(errata.ssl)
            .should_receive("get_default_verify_paths")
            .and_return(flexmock(openssl_cafile="/my/cert.pem")))

        (flexmock(errata)
            .should_receive("HTTPSPNEGOAuth")
            .and_return("MyHTTPSPNEGOAuth"))

        response = flexmock(status_code=200)
        response.should_receive("json").and_return(test_structures.rpm_build_attached_json)

        nvr = 'coreutils-8.22-21.el7'
        pv = 'rhaos-test-7'

        (flexmock(errata.requests.Session)
            .should_receive("get")
            .with_args(constants.errata_get_build_url.format(id=nvr),
                       auth="MyHTTPSPNEGOAuth",
                       verify="/my/cert.pem")
            .and_return(response))

        b = errata.get_brew_build(nvr, product_version=pv)

        self.assertEqual(nvr, b.nvr)

    def test_get_brew_build_success_session(self):
        (flexmock(errata.ssl)
            .should_receive("get_default_verify_paths")
            .and_return(flexmock(openssl_cafile="/my/cert.pem")))

        (flexmock(errata)
            .should_receive("HTTPSPNEGOAuth")
            .and_return("MyHTTPSPNEGOAuth"))

        response = flexmock(status_code=200)
        response.should_receive("json").and_return(test_structures.rpm_build_attached_json)

        nvr = 'coreutils-8.22-21.el7'
        pv = 'rhaos-test-7'

        session = flexmock()
        (session
            .should_receive("get")
            .with_args(constants.errata_get_build_url.format(id=nvr),
                       auth="MyHTTPSPNEGOAuth",
                       verify="/my/cert.pem")
            .and_return(response))

        b = errata.get_brew_build(nvr, product_version=pv, session=session)

        self.assertEqual(nvr, b.nvr)

    def test_get_brew_build_failure(self):
        (flexmock(errata.ssl)
            .should_receive("get_default_verify_paths")
            .and_return(flexmock(openssl_cafile="/my/cert.pem")))

        (flexmock(errata)
            .should_receive("HTTPSPNEGOAuth")
            .and_return("MyHTTPSPNEGOAuth"))

        response = flexmock(status_code=404, text="_irrelevant_")

        nvr = 'coreutils-8.22-21.el7'
        pv = 'rhaos-test-7'

        (flexmock(errata.requests.Session)
            .should_receive("get")
            .with_args(constants.errata_get_build_url.format(id=nvr),
                       auth="MyHTTPSPNEGOAuth",
                       verify="/my/cert.pem")
            .and_return(response))

        self.assertRaises(exceptions.BrewBuildException,
                          errata.get_brew_build, nvr, product_version=pv)

    def test_get_build_objects(self):
        build_infos = {
            "logging-fluentd-container-v3.11.141-2": {"cg_id": None, "package_name": "logging-fluentd-container", "extra": {"submitter": "osbs", "image": {"media_types": ["application/vnd.docker.distribution.manifest.list.v2+json", "application/vnd.docker.distribution.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"], "help": None, "index": {"pull": ["brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift3/ose-logging-fluentd@sha256:1df5eacdd98923590afdc85330aaac0488de96e991b24a7f4cb60113b7a66e80", "brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift3/ose-logging-fluentd:v3.11.141-2"], "digests": {"application/vnd.docker.distribution.manifest.list.v2+json": "sha256:1df5eacdd98923590afdc85330aaac0488de96e991b24a7f4cb60113b7a66e80"}, "tags": ["v3.11.141-2"]}, "autorebuild": False, "isolated": False, "yum_repourls": ["https://pkgs.devel.redhat.com/cgit/containers/logging-fluentd/plain/.oit/signed.repo?h=rhaos-3.11-rhel-7"], "parent_build_id": 955726, "parent_images": ["openshift/ose-base:rhel7"], "parent_image_builds": {"openshift/ose-base:rhel7": {"id": 955726, "nvr": "openshift-enterprise-base-container-v4.0-201908250221"}}}, "container_koji_task_id": 23188768}, "creation_time": "2019-08-26 07:34:32.613833", "completion_time": "2019-08-26 07:34:31", "package_id": 67151, "cg_name": None, "id": 956245, "build_id": 956245, "epoch": None, "source": "git://pkgs.devel.redhat.com/containers/logging-fluentd#7f4bcdc798fd72414a29dc1010c448e1ed52f591", "state": 1, "version": "v3.11.141", "completion_ts": 1566804871.0, "owner_id": 4078, "owner_name": "ocp-build/buildvm.openshift.eng.bos.redhat.com", "nvr": "logging-fluentd-container-v3.11.141-2", "start_time": "2019-08-26 07:03:41", "creation_event_id": 26029088, "start_ts": 1566803021.0, "volume_id": 0, "creation_ts": 1566804872.61383, "name": "logging-fluentd-container", "task_id": None, "volume_name": "DEFAULT", "release": "2"},
            "logging-fluentd-container-v4.1.14-201908291507": {"cg_id": None, "package_name": "logging-fluentd-container", "extra": {"submitter": "osbs", "image": {"media_types": ["application/vnd.docker.distribution.manifest.list.v2+json", "application/vnd.docker.distribution.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"], "help": None, "index": {"unique_tags": ["rhaos-4.1-rhel-7-containers-candidate-94076-20190829211225"], "pull": ["brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift/ose-logging-fluentd@sha256:7503f828aaf80e04b2aaab0b88626b97a20e5600ba75fef8b764e02cc1164a7c", "brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift/ose-logging-fluentd:v4.1.14-201908291507"], "floating_tags": ["latest", "v4.1.14", "v4.1.14.20190829.150756", "v4.1"], "digests": {"application/vnd.docker.distribution.manifest.list.v2+json": "sha256:7503f828aaf80e04b2aaab0b88626b97a20e5600ba75fef8b764e02cc1164a7c"}, "tags": ["v4.1.14-201908291507"]}, "autorebuild": False, "isolated": False, "yum_repourls": ["https://pkgs.devel.redhat.com/cgit/containers/logging-fluentd/plain/.oit/signed.repo?h=rhaos-4.1-rhel-7"], "parent_build_id": 958278, "parent_images": ["rhscl/ruby-25-rhel7:latest", "openshift/ose-base:ubi7"], "parent_image_builds": {"openshift/ose-base:ubi7": {"id": 958278, "nvr": "openshift-enterprise-base-container-v4.0-201908290538"}, "rhscl/ruby-25-rhel7:latest": {"id": 957642, "nvr": "rh-ruby25-container-2.5-50"}}}, "container_koji_task_id": 23241046}, "creation_time": "2019-08-29 21:42:46.062037", "completion_time": "2019-08-29 21:42:44", "package_id": 67151, "cg_name": None, "id": 958765, "build_id": 958765, "epoch": None, "source": "git://pkgs.devel.redhat.com/containers/logging-fluentd#ecac10b38f035ea2f9ea62b9efa63c051667ebbb", "state": 1, "version": "v4.1.14", "completion_ts": 1567114964.0, "owner_id": 4078, "owner_name": "ocp-build/buildvm.openshift.eng.bos.redhat.com", "nvr": "logging-fluentd-container-v4.1.14-201908291507", "start_time": "2019-08-29 21:12:51", "creation_event_id": 26063093, "start_ts": 1567113171.0, "volume_id": 0, "creation_ts": 1567114966.06204, "name": "logging-fluentd-container", "task_id": None, "volume_name": "DEFAULT", "release": "201908291507"},
            "logging-fluentd-container-v4.1.15-201909041605": {"cg_id": None, "package_name": "logging-fluentd-container", "extra": {"submitter": "osbs", "image": {"media_types": ["application/vnd.docker.distribution.manifest.list.v2+json", "application/vnd.docker.distribution.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"], "help": None, "index": {"unique_tags": ["rhaos-4.1-rhel-7-containers-candidate-96970-20190904214308"], "pull": ["brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift/ose-logging-fluentd@sha256:1ce1555b58982a29354c293948ee6c788743a08f39a0c530be791cb9bdaf4189", "brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift/ose-logging-fluentd:v4.1.15-201909041605"], "floating_tags": ["latest", "v4.1.15", "v4.1", "v4.1.15.20190904.160545"], "digests": {"application/vnd.docker.distribution.manifest.list.v2+json": "sha256:1ce1555b58982a29354c293948ee6c788743a08f39a0c530be791cb9bdaf4189"}, "tags": ["v4.1.15-201909041605"]}, "autorebuild": False, "isolated": False, "yum_repourls": ["https://pkgs.devel.redhat.com/cgit/containers/logging-fluentd/plain/.oit/signed.repo?h=rhaos-4.1-rhel-7"], "parent_build_id": 961131, "parent_images": ["rhscl/ruby-25-rhel7:latest", "openshift/ose-base:ubi7"], "parent_image_builds": {"openshift/ose-base:ubi7": {"id": 961131, "nvr": "openshift-enterprise-base-container-v4.0-201909040323"}, "rhscl/ruby-25-rhel7:latest": {"id": 957642, "nvr": "rh-ruby25-container-2.5-50"}}}, "container_koji_task_id": 23365465}, "creation_time": "2019-09-04 22:17:36.432110", "completion_time": "2019-09-04 22:17:35", "package_id": 67151, "cg_name": None, "id": 962144, "build_id": 962144, "epoch": None, "source": "git://pkgs.devel.redhat.com/containers/logging-fluentd#31cf3d4264dabb8892fb4b5921e5ff4d5d0ab2de", "state": 1, "version": "v4.1.15", "completion_ts": 1567635455.0, "owner_id": 4078, "owner_name": "ocp-build/buildvm.openshift.eng.bos.redhat.com", "nvr": "logging-fluentd-container-v4.1.15-201909041605", "start_time": "2019-09-04 21:43:32", "creation_event_id": 26176078, "start_ts": 1567633412.0, "volume_id": 0, "creation_ts": 1567635456.43211, "name": "logging-fluentd-container", "task_id": None, "volume_name": "DEFAULT", "release": "201909041605"},
        }

        def fake_get_build(nvr):
            return mock.MagicMock(result=build_infos[nvr])

        fake_session = mock.MagicMock()
        fake_context_manager = fake_session.multicall.return_value.__enter__.return_value
        fake_context_manager.getBuild.side_effect = fake_get_build
        expected = list(build_infos.values())
        actual = brew.get_build_objects(build_infos.keys(), fake_session)
        self.assertListEqual(actual, expected)

    def test_get_builds_tags(self):
        build_tags_map = {
            "foo-1.0.0-1": ["rhaos-4.3-rhel-7-candidate"],
            "bar-1.0.0-1": ["rhaos-4.3-rhel-8-candidate"],
        }

        def fake_list_tags(build):
            return mock.MagicMock(result=build_tags_map[build])

        fake_session = mock.MagicMock()
        fake_context_manager = fake_session.multicall.return_value.__enter__.return_value
        fake_context_manager.listTags.side_effect = fake_list_tags
        actual = brew.get_builds_tags(build_tags_map.keys(), fake_session)
        expected = list(build_tags_map.values())
        self.assertListEqual(expected, actual)

    def test_get_latest_builds(self):
        tag_component_tuples = [
            ("faketag1", "component1"),
            ("faketag2", "component2"),
            ("faketag2", None),
            ("faketag1", "component4"),
            ("", "component5"),
            ("faketag2", "component6"),
        ]
        expected = [
            {"name": "component1", "nvr": "component1-v1.0.0-1.faketag1"},
            {"name": "component2", "nvr": "component2-v1.0.0-1.faketag2"},
            None,
            {"name": "component4", "nvr": "component4-v1.0.0-1.faketag1"},
            None,
            {"name": "component6", "nvr": "component6-v1.0.0-1.faketag2"},
        ]

        def fake_response(tag, package, event=None):
            return mock.MagicMock(result={"name": package, "nvr": f"{package}-v1.0.0-1.{tag}"})

        fake_session = mock.MagicMock()
        fake_context_manager = fake_session.multicall.return_value.__enter__.return_value
        fake_context_manager.getLatestBuilds.side_effect = fake_response
        actual = brew.get_latest_builds(tag_component_tuples, fake_session)
        self.assertListEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
