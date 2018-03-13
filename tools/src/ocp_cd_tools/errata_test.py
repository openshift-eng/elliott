"""
Test errata models/controllers
"""

import mock
from contextlib import nested

# Import the right version for your python
import platform
(major, minor, patch) = platform.python_version_tuple()
if int(major) == 2 and int(minor) < 7:
    import unittest2 as unittest
else:
    import unittest

import errata

class TestBrew(unittest.TestCase):

    def test_get_erratum_success(self):
        """Verify a 'good' erratum request is fulfilled"""
        with mock.patch('errata.requests.get') as get:
            pass

    def test_get_erratum_failure(self):
        """Verify a 'bad' erratum request returns False"""
        pass




if __name__ == '__main__':
    unittest.main()
