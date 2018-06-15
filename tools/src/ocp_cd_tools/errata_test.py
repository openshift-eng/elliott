"""
Test errata models/controllers
"""

import datetime
import mock
import json
from contextlib import nested

# Import the right version for your python
import platform
(major, minor, patch) = platform.python_version_tuple()
if int(major) == 2 and int(minor) < 7:
    import unittest2 as unittest
else:
    import unittest

import exceptions
import constants
import errata
import bugzilla
import brew
import test_structures

from requests_kerberos import HTTPKerberosAuth


class TestBrew(unittest.TestCase):

    def test_get_erratum_success(self):
        """Verify a 'good' erratum request is fulfilled"""
        with mock.patch('errata.requests.get') as get:
            # Create the requests.response object. The status code
            # here will change the path of execution to the not-found
            # branch of errata.get_erratum
            response = mock.MagicMock(status_code=200)
            # response's have a 'json' function that returns a dict of
            # the JSON response body ('example_erratum' defined below)
            response.json.return_value = test_structures.example_erratum
            # Set the return value of the requests.get call to the
            # response we just created
            get.return_value = response
            e = errata.get_erratum(123456)
            self.assertIsInstance(e, errata.Erratum)

    def test_get_erratum_unauthorized(self):
        """Verify an we can detect unauthorized requests"""
        with mock.patch('errata.requests.get') as get:
            # Create the requests.response object. The status code
            # here will change the path of execution to the
            # unauthorized branch of code
            response = mock.MagicMock(status_code=401)
            get.return_value = response
            with self.assertRaises(exceptions.ErrataToolUnauthenticatedException):
                errata.get_erratum(123456)

    def test_get_erratum_failure(self):
        """Verify a 'bad' erratum request returns False"""
        with mock.patch('errata.requests.get') as get:
            # Engage the not-found branch
            response = mock.MagicMock(status_code=404)
            response.json.return_value = test_structures.example_erratum
            get.return_value = response
            e = errata.get_erratum(123456)
            self.assertFalse(e)

    def test_parse_date(self):
        """Verify we can parse the date string returned from Errata Tool"""
        d_expected = '2018-03-02 15:19:08'
        d_out = datetime.datetime.strptime(test_structures.example_erratum['errata']['rhba']['created_at'], '%Y-%m-%dT%H:%M:%SZ')
        self.assertEqual(str(d_out), d_expected)

    def test_erratum_as_string(self):
        """Verify str(Erratum) is formatted correctly"""
        ds = test_structures.example_erratum
        e = errata.Erratum(body=ds)
        expected_str = "{date} {state} {synopsis} {url}".format(
            date=datetime.datetime.strptime(ds['errata']['rhba']['created_at'], '%Y-%m-%dT%H:%M:%SZ').isoformat(),
            state=ds['errata']['rhba']['status'],
            synopsis=ds['errata']['rhba']['synopsis'],
            url="{et}/advisory/{id}".format(
                et=constants.errata_url,
                id=ds['errata']['rhba']['id']))
        self.assertEqual(expected_str, str(e))

    def test_erratum_to_json(self):
        """Ensure Erratum.to_json returns the source datastructure"""
        e = errata.Erratum(body=test_structures.example_erratum)
        self.assertEqual(json.loads(e.to_json()), test_structures.example_erratum)

    def test_erratum_refresh(self):
        """Ensure Erratum.refresh does the needful"""
        with mock.patch('errata.requests.get') as get:
            # Create the requests.response object. The status code
            # here will change the path of execution to the not-found
            # branch of errata.get_erratum
            response = mock.MagicMock(status_code=200)
            # response's have a 'json' function that returns a dict of
            # the JSON response body ('example_erratum' defined below)
            response.json.return_value = test_structures.example_erratum
            # Set the return value of the requests.get call to the
            # response we just created
            get.return_value = response
            e = errata.get_erratum(123456)

            # Use the string representation for comparison, they should be identical
            original_str = str(e)

            e.refresh()
            self.assertEqual(original_str, str(e))

    def test_get_filtered_list(self):
        """Ensure we can generate an Erratum List"""
        with mock.patch('errata.requests.get') as get:
            response = mock.MagicMock(status_code=200)
            response.json.return_value = test_structures.example_erratum_filtered_list
            get.return_value = response
            res = errata.get_filtered_list()
            self.assertEqual(2, len(res))

    def test_get_filtered_list_limit(self):
        """Ensure we can generate a trimmed Erratum List"""
        with mock.patch('errata.requests.get') as get:
            response = mock.MagicMock(status_code=200)
            response.json.return_value = test_structures.example_erratum_filtered_list
            get.return_value = response
            res = errata.get_filtered_list(limit=1)
            self.assertEqual(1, len(res))

    def test_get_filtered_list_fail(self):
        """Ensure we notice invalid erratum lists"""
        with mock.patch('errata.requests.get') as get:
            response = mock.MagicMock(status_code=404)
            response.json.return_value = test_structures.example_erratum_filtered_list
            get.return_value = response
            with self.assertRaises(exceptions.ErrataToolError):
                errata.get_filtered_list()

    def test_working_erratum(self):
        """We can create an Erratum object with a known erratum from the API"""
        # If there is an error, it will raise on its own during parsing
        #
        # If the tool fails in the future due to a schema change in
        # the returned erratum object from the ET API then the
        # `example_erratum` in this test file will need to be updated.
        e = errata.Erratum(body=test_structures.example_erratum)
        self.assertEqual(type(e), type(errata.Erratum()))

    def test_add_bug(self):
        """Verify Bugs are added the right way"""
        with nested(
                mock.patch('errata.requests.post'),
                # Mock the HTTPKerberosAuth object in the module
                mock.patch('errata.HTTPKerberosAuth')) as (post, kerb):
            response = mock.MagicMock(status_code=404)
            response.json.return_value = test_structures.example_erratum_filtered_list
            post.return_value = response

            b = bugzilla.Bug(id=1337)

            # With the mocked HTTPKerberosAuth object we can now
            # create an erratum
            e = errata.Erratum(body=test_structures.example_erratum)

            # When we make the method call, we will be using the same
            # mocked ('kerb') HTTPKerberosAuth object
            e.add_bug(b)

            post.assert_called_once_with(
                constants.errata_add_bug_url.format(id=test_structures.example_erratum['content']['content']['errata_id']),
                auth=kerb(),
                json={'bug': b.id}
            )

    def test_add_builds_success(self):
        """Ensure legit builds are added correctly"""
        with nested(
                mock.patch('errata.requests.post'),
                mock.patch('errata.HTTPKerberosAuth')) as (post, kerb):
            response = mock.MagicMock(status_code=200)
            response.json.return_value = test_structures.example_erratum_filtered_list
            post.return_value = response

            pv = 'rhaos-test-7'
            e = errata.Erratum(body=test_structures.example_erratum)
            b1 = brew.Build(nvr='coreutils-8.22-21.el7',
                            body=test_structures.rpm_build_attached_json,
                            product_version=pv)
            b2 = brew.Build(nvr='ansible-service-broker-1.0.21-1.el7',
                            body=test_structures.rpm_build_unattached_json,
                            product_version=pv)
            builds = [b1, b2]

            result = e.add_builds(builds)

            # add_builds returns True on success
            self.assertTrue(result)
            # Even though we have multiple builds, the add_builds
            # endpoint allows us to make just one call, as it
            # accepts a list of builds in the request body
            self.assertEqual(post.call_count, 1)

            post.assert_called_once_with(
                constants.errata_add_builds_url.format(id=test_structures.example_erratum['content']['content']['errata_id']),
                auth=kerb(),
                json=[b1.to_json(), b2.to_json()]
            )

    def test_add_builds_failure(self):
        """Ensure failing add_builds raises correctly on a known bad status code"""
        with nested(
                mock.patch('errata.requests.post'),
                mock.patch('errata.HTTPKerberosAuth')) as (post, kerb):
            # This triggers the failure code-branch
            response = mock.MagicMock(status_code=422)
            response.json.return_value = test_structures.example_erratum_filtered_list
            post.return_value = response

            pv = 'rhaos-test-7'
            e = errata.Erratum(body=test_structures.example_erratum)
            b1 = brew.Build(nvr='coreutils-8.22-21.el7',
                            body=test_structures.rpm_build_attached_json,
                            product_version=pv)
            b2 = brew.Build(nvr='ansible-service-broker-1.0.21-1.el7',
                            body=test_structures.rpm_build_unattached_json,
                            product_version=pv)
            builds = [b1, b2]

            with self.assertRaises(exceptions.BrewBuildException):
                e.add_builds(builds)

    # Commented out until we update add_builds to handle non-422 response codes
    # def test_add_builds_failure(self):
    #     """Ensure failing add_builds raises correctly on an unknown bad status code"""
    #     with mock.patch('errata.requests.post') as post:
    #         # This triggers the failure code-branch
    #         response = mock.MagicMock(status_code=500)
    #         response.json.return_value = example_erratum_filtered_list
    #         post.return_value = response
    #         with mock.patch('errata.HTTPKerberosAuth') as kerb:
    #             pv = 'rhaos-test-7'
    #             e = errata.Erratum(body=example_erratum)
    #             b1 = brew.Build(nvr='coreutils-8.22-21.el7',
    #                             body=rpm_build_attached_json,
    #                             product_version=pv)
    #             b2 = brew.Build(nvr='ansible-service-broker-1.0.21-1.el7',
    #                             body=rpm_build_unattached_json,
    #                             product_version=pv)
    #             builds = [b1, b2]

    #             with self.assertRaises(exceptions.BrewBuildException):
    #                 result = e.add_builds(builds)


if __name__ == '__main__':
    unittest.main()
