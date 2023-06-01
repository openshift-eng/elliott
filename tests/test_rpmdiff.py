import unittest
from unittest import mock
import json
from elliottlib import rpmdiff, constants


class TestRPMDiffClient(unittest.TestCase):
    def setUp(self):
        self.client = rpmdiff.RPMDiffClient(
            "https://rpmdiff.example.com",
            session=mock.MagicMock()
        )

    def test_get_token(self):
        token = "abcdefg"
        response = {"token": token}
        self.client.session.get.return_value.json.return_value = response
        actual = self.client.get_token(mock.MagicMock())
        self.assertEqual(actual, token)

    def test_authenticate(self):
        token = "abcdefg"
        self.client.get_token = mock.MagicMock(return_value=token)
        self.client.session.headers = {}
        self.client.authenticate()
        self.assertEqual(self.client.session.headers["Authorization"], "Token " + token)

    def test_get_run(self):
        response = {"run_id ": 12345}
        self.client.session.get.return_value.json.return_value = response
        actual = self.client.get_run(12345)
        self.assertEqual(actual, response)

    def test_get_test_results(self):
        response = {
            "results": [
                {"result_id": 1, "score": 0},
                {"result_id": 2, "score": 3},
                {"result_id": 3, "score": 4},
            ]
        }
        self.client.session.get.return_value.json.return_value = response
        actual = self.client.get_test_results(12345)
        self.assertEqual(actual, response["results"])

    def test_list_waivers(self):
        response = {
            "results": [
                {"waiver_id": 1},
                {"waiver_id": 2},
                {"waiver_id": 3},
            ]
        }
        self.client.session.get.return_value.json.return_value = response
        actual = self.client.list_waivers("foo", 123)
        self.assertEqual(actual, response["results"])


if __name__ == '__main__':
    unittest.main()
