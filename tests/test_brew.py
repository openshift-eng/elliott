"""

Test the brew related functions/classes

"""

import flexmock

import logging
import StringIO

import platform
(major, minor, patch) = platform.python_version_tuple()
if int(major) == 2 and int(minor) < 7:
    import unittest2 as unittest
else:
    import unittest

from elliottlib import exceptions
import constants
import brew
import test_structures


class TestBrew(unittest.TestCase):

    def setUp(self):
        """
        Define and provide mock logging for test/response
        """
        self.stream = StringIO.StringIO()
        logging.basicConfig(level=logging.DEBUG, stream=self.stream)
        self.logger = logging.getLogger()

    def tearDown(self):
        """
        Reset logging for each test.
        """
        logging.shutdown()
        reload(logging)

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
        builds.add(b1)
        builds.add(b1)

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
        (flexmock(brew.ssl)
            .should_receive("get_default_verify_paths")
            .and_return(flexmock(openssl_cafile="/my/cert.pem")))

        (flexmock(brew)
            .should_receive("HTTPKerberosAuth")
            .and_return("MyHTTPKerberosAuth"))

        response = flexmock(status_code=200)
        response.should_receive("json").and_return(test_structures.rpm_build_attached_json)

        nvr = 'coreutils-8.22-21.el7'
        pv = 'rhaos-test-7'

        (flexmock(brew.requests)
            .should_receive("get")
            .with_args(constants.errata_get_build_url.format(id=nvr),
                       auth="MyHTTPKerberosAuth",
                       verify="/my/cert.pem")
            .and_return(response))

        b = brew.get_brew_build(nvr, product_version=pv)

        self.assertEqual(nvr, b.nvr)

    def test_get_brew_build_success_session(self):
        (flexmock(brew.ssl)
            .should_receive("get_default_verify_paths")
            .and_return(flexmock(openssl_cafile="/my/cert.pem")))

        (flexmock(brew)
            .should_receive("HTTPKerberosAuth")
            .and_return("MyHTTPKerberosAuth"))

        response = flexmock(status_code=200)
        response.should_receive("json").and_return(test_structures.rpm_build_attached_json)

        nvr = 'coreutils-8.22-21.el7'
        pv = 'rhaos-test-7'

        session = flexmock()
        (session
            .should_receive("get")
            .with_args(constants.errata_get_build_url.format(id=nvr),
                       auth="MyHTTPKerberosAuth",
                       verify="/my/cert.pem")
            .and_return(response))

        b = brew.get_brew_build(nvr, product_version=pv, session=session)

        self.assertEqual(nvr, b.nvr)

    def test_get_brew_build_failure(self):
        (flexmock(brew.ssl)
            .should_receive("get_default_verify_paths")
            .and_return(flexmock(openssl_cafile="/my/cert.pem")))

        (flexmock(brew)
            .should_receive("HTTPKerberosAuth")
            .and_return("MyHTTPKerberosAuth"))

        response = flexmock(status_code=404, text="_irrelevant_")

        nvr = 'coreutils-8.22-21.el7'
        pv = 'rhaos-test-7'

        (flexmock(brew.requests)
            .should_receive("get")
            .with_args(constants.errata_get_build_url.format(id=nvr),
                       auth="MyHTTPKerberosAuth",
                       verify="/my/cert.pem")
            .and_return(response))

        self.assertRaises(exceptions.BrewBuildException,
                          brew.get_brew_build, nvr, product_version=pv)

    def test_get_tagged_image_builds_success(self):
        """Ensure the brew list-tagged command is correct for images"""
        # Any value will work for this. Let's use a real one though to
        # maintain our sanity. This matches with the example data in
        # test_structures
        tag = 'rhaos-3.9-rhel-7-candidate'
        # Big multi-line string with brew image build ouput.
        image_builds_mock_return = test_structures.brew_list_tagged_3_9_image_builds
        image_builds_mock_length = len(image_builds_mock_return.splitlines())

        expected_args = ['brew', 'list-tagged', 'rhaos-3.9-rhel-7-candidate',
                         '--latest', '--type=image', '--quiet']

        (flexmock(brew.exectools)
            .should_receive("cmd_gather")
            .with_args(expected_args)
            .once()
            .and_return((0, image_builds_mock_return, '')))

        # Now we can test the BrewTaggedImageBuilds
        # collecter/parser class as well as the
        # get_tagged_image_builds function
        tagged_image_builds = brew.BrewTaggedImageBuilds(tag)
        # This invokes get_tagged_image_builds, which in turn
        # invokes our mocked gather_exec
        images_refreshed = tagged_image_builds.refresh()

        # Refreshing returns True after parsing the results from
        # the brew CLI command, errors will raise an exception
        self.assertTrue(images_refreshed)

        # Our example data has 59 valid parseable images listed
        self.assertEqual(image_builds_mock_length, len(tagged_image_builds.builds))

    def test_get_tagged_image_builds_failed(self):
        """Ensure the brew list-tagged explodes if the brew subprocess fails"""
        # Any value will work for this. Let's use a real one though to
        # maintain our sanity. This matches with the example data in
        # test_structures
        tag = 'rhaos-3.9-rhel-7-candidate'
        # Big multi-line string with brew image build ouput.
        image_builds_mock_return = test_structures.brew_list_tagged_3_9_image_builds

        expected_args = ['brew', 'list-tagged', 'rhaos-3.9-rhel-7-candidate',
                         '--latest', '--type=image', '--quiet']

        (flexmock(brew.exectools)
            .should_receive("cmd_gather")
            .with_args(expected_args)
            .once()
            .and_return((1, image_builds_mock_return, "")))

        tagged_image_builds = brew.BrewTaggedImageBuilds(tag)

        self.assertRaises(exceptions.BrewBuildException, tagged_image_builds.refresh)

    def test_get_tagged_rpm_builds_success(self):
        """Ensure the brew list-tagged command is correct for rpms"""
        # Any value will work for this. Let's use a real one though to
        # maintain our sanity. This matches with the example data in
        # test_structures
        tag = 'rhaos-3.9-rhel-7-candidate'
        # Big multi-line string with brew rpm build ouput.
        rpm_builds_mock_return = test_structures.brew_list_tagged_3_9_rpm_builds
        rpm_builds_mock_length = len(rpm_builds_mock_return.splitlines())

        expected_args = ['brew', 'list-tagged', 'rhaos-3.9-rhel-7-candidate',
                         '--latest', '--rpm', '--quiet', '--arch', 'src']

        (flexmock(brew.exectools)
            .should_receive("cmd_gather")
            .with_args(expected_args)
            .once()
            .and_return((0, rpm_builds_mock_return, "")))

        # Now we can test the BrewTaggedRPMBuilds
        # collecter/parser class as well as the
        # get_tagged_rpm_builds function
        tagged_rpm_builds = brew.BrewTaggedRPMBuilds(tag)
        # This invokes get_tagged_rpm_builds, which in turn
        # invokes our mocked gather_exec
        rpms_refreshed = tagged_rpm_builds.refresh()

        # Refreshing returns True after parsing the results from
        # the brew CLI command, errors will raise an exception
        self.assertTrue(rpms_refreshed)

        # Our example data has 59 valid parseable rpms listed
        self.assertEqual(rpm_builds_mock_length, len(tagged_rpm_builds.builds))

    def test_get_tagged_rpm_builds_failed(self):
        """Ensure the brew list-tagged explodes if the brew subprocess fails"""
        # Any value will work for this. Let's use a real one though to
        # maintain our sanity. This matches with the example data in
        # test_structures
        tag = 'rhaos-3.9-rhel-7-candidate'
        # Big multi-line string with brew rpm build ouput.
        rpm_builds_mock_return = test_structures.brew_list_tagged_3_9_rpm_builds

        expected_args = ['brew', 'list-tagged', 'rhaos-3.9-rhel-7-candidate',
                         '--latest', '--rpm', '--quiet', '--arch', 'src']

        (flexmock(brew.exectools)
            .should_receive("cmd_gather")
            .with_args(expected_args)
            .once()
            .and_return((1, rpm_builds_mock_return, "")))

        tagged_rpm_builds = brew.BrewTaggedRPMBuilds(tag)

        self.assertRaises(exceptions.BrewBuildException, tagged_rpm_builds.refresh)


if __name__ == '__main__':
    unittest.main()
