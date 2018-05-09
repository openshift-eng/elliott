"""

Test the brew related functions/classes

"""

import mock
from contextlib import nested

import logging
import StringIO

import platform
(major, minor, patch) = platform.python_version_tuple()
if int(major) == 2 and int(minor) < 7:
    import unittest2 as unittest
else:
    import unittest

import exceptions
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
        """Ensure a 'proper' brew build returns a Build object"""
        with nested(
                mock.patch('brew.requests.get'),
                # Mock the HTTPKerberosAuth object in the module
                mock.patch('brew.HTTPKerberosAuth')) as (get, kerb):
            nvr = 'coreutils-8.22-21.el7'
            pv = 'rhaos-test-7'
            response = mock.MagicMock(status_code=200)
            response.json.return_value = test_structures.rpm_build_attached_json
            get.return_value = response

            b = brew.get_brew_build(nvr, product_version=pv)

            # Basic object validation to ensure that the example build
            # object we return from our get() mock matches the
            # returned Build object
            self.assertEqual(nvr, b.nvr)

            get.assert_called_once_with(
                constants.errata_get_build_url.format(id=nvr),
                auth=kerb()
            )

    def test_get_brew_build_success_session(self):
        """Ensure a provided requests session is used when getting brew builds"""
        with mock.patch('brew.HTTPKerberosAuth') as kerb:
            nvr = 'coreutils-8.22-21.el7'
            pv = 'rhaos-test-7'
            # This is the return result from the session.get() call
            response = mock.MagicMock(status_code=200)
            # We'll call the json method on the result to retrieve the
            # response body from ET
            response.json.return_value = test_structures.rpm_build_attached_json
            # We create a session mock HERE to pass in when we call
            # the get_brew_build function
            session = mock.MagicMock()
            # In get_brew_build the get is method is called on the
            # session mock. We want to return our response as if we
            # actually queried the API
            session.get.return_value = response

            # Ensure we pass in the session mock we created here
            b = brew.get_brew_build(nvr, product_version=pv, session=session)

            # Basic object validation to ensure that the example build
            # object we return from our get() mock matches the
            # returned Build object
            self.assertEqual(nvr, b.nvr)

            # Our session object+get method were used, not the
            # requests.get (default) method
            session.get.assert_called_once_with(
                constants.errata_get_build_url.format(id=nvr),
                auth=kerb()
            )

    def test_get_brew_build_failure(self):
        """Ensure we notice invalid get-build responses from the API"""
        with nested(
                mock.patch('brew.requests.get'),
                # Mock the HTTPKerberosAuth object in the module
                mock.patch('brew.HTTPKerberosAuth')) as (get, kerb):
            nvr = 'coreutils-8.22-21.el7'
            pv = 'rhaos-test-7'
            # Engage the failure logic branch, will raise
            response = mock.MagicMock(status_code=404)
            response.json.return_value = test_structures.rpm_build_attached_json
            get.return_value = response

            # The 404 status code will send us down the exception
            # branch of code
            with self.assertRaises(exceptions.BrewBuildException):
                brew.get_brew_build(nvr, product_version=pv)

            get.assert_called_once_with(
                constants.errata_get_build_url.format(id=nvr),
                auth=kerb()
            )

    def test_get_tagged_image_builds_success(self):
        """Ensure the brew list-tagged command is correct for images"""
        # Any value will work for this. Let's use a real one though to
        # maintain our sanity. This matches with the example data in
        # test_structures
        tag = 'rhaos-3.9-rhel-7-candidate'
        # Big multi-line string with brew image build ouput.
        image_builds_mock_return = test_structures.brew_list_tagged_3_9_image_builds
        image_builds_mock_length = len(image_builds_mock_return.splitlines())

        with mock.patch('exectools.cmd_gather') as gexec:
            # gather_exec => (rc, stdout, stderr)
            gexec.return_value = tuple([0, image_builds_mock_return, ""])

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

            gexec.assert_called_once_with(
                # shlex must split our command string into a list
                ['brew', 'list-tagged', 'rhaos-3.9-rhel-7-candidate', '--latest', '--type=image', '--quiet'],
                logger=self.logger
            )

    def test_get_tagged_image_builds_failed(self):
        """Ensure the brew list-tagged explodes if the brew subprocess fails"""
        # Any value will work for this. Let's use a real one though to
        # maintain our sanity. This matches with the example data in
        # test_structures
        tag = 'rhaos-3.9-rhel-7-candidate'
        # Big multi-line string with brew image build ouput.
        image_builds_mock_return = test_structures.brew_list_tagged_3_9_image_builds

        with mock.patch('exectools.cmd_gather') as gexec:
            # gather_exec => (rc, stdout, stderr)
            #
            # The '1' in position 0 is the brew subprocess return
            # code, this invokes the error raising branch of code
            gexec.return_value = tuple([1, image_builds_mock_return, ""])
            tagged_image_builds = brew.BrewTaggedImageBuilds(tag)

            with self.assertRaises(exceptions.BrewBuildException):
                tagged_image_builds.refresh()

            gexec.assert_called_once_with(
                # shlex must split our command string into a list
                ['brew', 'list-tagged', 'rhaos-3.9-rhel-7-candidate', '--latest', '--type=image', '--quiet'],
                logger=self.logger
            )

    def test_get_tagged_rpm_builds_success(self):
        """Ensure the brew list-tagged command is correct for rpms"""
        # Any value will work for this. Let's use a real one though to
        # maintain our sanity. This matches with the example data in
        # test_structures
        tag = 'rhaos-3.9-rhel-7-candidate'
        # Big multi-line string with brew rpm build ouput.
        rpm_builds_mock_return = test_structures.brew_list_tagged_3_9_rpm_builds
        rpm_builds_mock_length = len(rpm_builds_mock_return.splitlines())

        with mock.patch('exectools.cmd_gather') as gexec:
            # gather_exec => (rc, stdout, stderr)
            gexec.return_value = tuple([0, rpm_builds_mock_return, ""])

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

            gexec.assert_called_once_with(
                # shlex must split our command string into a list
                ['brew', 'list-tagged', 'rhaos-3.9-rhel-7-candidate', '--latest', '--rpm', '--quiet', '--arch', 'src'],
                logger=self.logger
            )

    def test_get_tagged_rpm_builds_failed(self):
        """Ensure the brew list-tagged explodes if the brew subprocess fails"""
        # Any value will work for this. Let's use a real one though to
        # maintain our sanity. This matches with the example data in
        # test_structures
        tag = 'rhaos-3.9-rhel-7-candidate'
        # Big multi-line string with brew rpm build ouput.
        rpm_builds_mock_return = test_structures.brew_list_tagged_3_9_rpm_builds

        with mock.patch('exectools.cmd_gather') as gexec:
            # gather_exec => (rc, stdout, stderr)
            #
            # The '1' in position 0 is the brew subprocess return
            # code, this invokes the error raising branch of code
            gexec.return_value = tuple([1, rpm_builds_mock_return, ""])
            tagged_rpm_builds = brew.BrewTaggedRPMBuilds(tag)

            with self.assertRaises(exceptions.BrewBuildException):
                tagged_rpm_builds.refresh()

            gexec.assert_called_once_with(
                # shlex must split our command string into a list
                ['brew', 'list-tagged', 'rhaos-3.9-rhel-7-candidate', '--latest', '--rpm', '--quiet', '--arch', 'src'],
                logger=self.logger
            )


if __name__ == '__main__':
    unittest.main()
