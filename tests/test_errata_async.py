import base64
from asyncio import get_event_loop
from unittest import TestCase
from mock import ANY, AsyncMock, MagicMock, Mock, patch
from elliottlib.errata_async import AsyncErrataAPI, AsyncErrataUtils


class TestAsyncErrataAPI(TestCase):
    @patch("aiohttp.ClientSession", autospec=True)
    @patch("gssapi.SecurityContext", autospec=True)
    def test_login(self, SecurityContext: Mock, ClientSession: Mock):
        client_ctx = SecurityContext.return_value
        client_ctx.step.return_value = b"faketoken"
        api = AsyncErrataAPI("https://errata.example.com")
        get_event_loop().run_until_complete(api.login())
        client_ctx.step.assert_called_once_with(b"")
        self.assertEqual(api._headers["Authorization"], 'Negotiate ' + base64.b64encode(b"faketoken").decode())

    @patch("aiohttp.ClientSession")
    def test_make_request(self, ClientSession: AsyncMock):
        request = MagicMock(
            **{
                'request.return_value.__aenter__.return_value': AsyncMock(
                    **{
                        'json.return_value': {"result": "fake"},
                        'read.return_value': b"daedbeef"
                    }
                )
            }
        )
        ClientSession.return_value.__aenter__.return_value = request
        api = AsyncErrataAPI("https://errata.example.com")
        actual = get_event_loop().run_until_complete(api._make_request("HEAD", "/api/path"))
        self.assertEqual(actual, {"result": "fake"})
        actual = get_event_loop().run_until_complete(api._make_request("GET", "/api/path", parse_json=False))
        self.assertEqual(actual, b"daedbeef")

    @patch("aiohttp.ClientSession", autospec=True)
    @patch("elliottlib.errata_async.AsyncErrataAPI._make_request", autospec=True)
    def test_get_advisory(self, _make_request: Mock, ClientSession: Mock):
        api = AsyncErrataAPI("https://errata.example.com")
        _make_request.return_value = {"result": "fake"}

        actual = get_event_loop().run_until_complete(api.get_advisory(1))
        _make_request.assert_awaited_once_with(ANY, "GET", "/api/v1/erratum/1")
        self.assertEqual(actual, {"result": "fake"})

        _make_request.reset_mock()
        actual = get_event_loop().run_until_complete(api.get_advisory("RHBA-2021:0001"))
        _make_request.assert_awaited_once_with(ANY, "GET", "/api/v1/erratum/RHBA-2021%3A0001")
        self.assertEqual(actual, {"result": "fake"})

    @patch("aiohttp.ClientSession", autospec=True)
    @patch("elliottlib.errata_async.AsyncErrataAPI._make_request", autospec=True)
    def test_get_builds(self, _make_request: Mock, ClientSession: Mock):
        api = AsyncErrataAPI("https://errata.example.com")
        _make_request.return_value = {
            "ProductVersion1": {"builds": [{"a-1.0.0-1": {}, "b-1.0.0-1": {}}]},
            "ProductVersion2": {"builds": [{"c-1.0.0-1": {}}]}
        }
        actual = get_event_loop().run_until_complete(api.get_builds(1))
        _make_request.assert_awaited_once_with(ANY, "GET", "/api/v1/erratum/1/builds_list")
        self.assertEqual(actual, _make_request.return_value)

    @patch("aiohttp.ClientSession", autospec=True)
    @patch("elliottlib.errata_async.AsyncErrataAPI._make_request", autospec=True)
    def test_get_builds_flattened(self, _make_request: Mock, ClientSession: Mock):
        api = AsyncErrataAPI("https://errata.example.com")
        _make_request.return_value = {
            "ProductVersion1": {"builds": [{"a-1.0.0-1": {}, "b-1.0.0-1": {}}]},
            "ProductVersion2": {"builds": [{"c-1.0.0-1": {}}]}
        }
        actual = get_event_loop().run_until_complete(api.get_builds_flattened(1))
        _make_request.assert_awaited_once_with(ANY, "GET", "/api/v1/erratum/1/builds_list")
        self.assertEqual(actual, {"a-1.0.0-1", "b-1.0.0-1", "c-1.0.0-1"})

    @patch("aiohttp.ClientSession", autospec=True)
    @patch("elliottlib.errata_async.AsyncErrataAPI._make_request", autospec=True)
    def test_get_cves(self, _make_request: Mock, ClientSession: Mock):
        api = AsyncErrataAPI("https://errata.example.com")
        api.get_advisory = AsyncMock(return_value={
            "content": {
                "content": {"cve": "A B C"}
            }
        })
        actual = get_event_loop().run_until_complete(api.get_cves(1))
        api.get_advisory.assert_awaited_once_with(1)
        self.assertEqual(actual, ["A", "B", "C"])

    @patch("aiohttp.ClientSession", autospec=True)
    @patch("elliottlib.errata_async.AsyncErrataAPI._make_request", autospec=True)
    def test_create_cve_package_exclusion(self, _make_request: Mock, ClientSession: Mock):
        api = AsyncErrataAPI("https://errata.example.com")
        _make_request.return_value = {"result": "fake"}
        actual = get_event_loop().run_until_complete(api.create_cve_package_exclusion(1, "CVE-1", "a"))
        _make_request.assert_awaited_once_with(ANY, 'POST', '/api/v1/cve_package_exclusion', json={'cve': 'CVE-1', 'errata': 1, 'package': 'a'})
        self.assertEqual(actual, {"result": "fake"})

    @patch("aiohttp.ClientSession", autospec=True)
    @patch("elliottlib.errata_async.AsyncErrataAPI._make_request", autospec=True)
    def test_create_delete_cve_package_exclusion(self, _make_request: Mock, ClientSession: Mock):
        api = AsyncErrataAPI("https://errata.example.com")
        _make_request.return_value = b""
        actual = get_event_loop().run_until_complete(api.delete_cve_package_exclusion(100))
        _make_request.assert_awaited_once_with(ANY, 'DELETE', '/api/v1/cve_package_exclusion/100', parse_json=False)
        self.assertEqual(actual, None)

    @patch("aiohttp.ClientSession", autospec=True)
    @patch("elliottlib.errata_async.AsyncErrataAPI._make_request", autospec=True)
    def test_get_cve_package_exclusions(self, _make_request: Mock, ClientSession: Mock):
        api = AsyncErrataAPI("https://errata.example.com")
        _make_request.side_effect = lambda _0, _1, _2, params: {
            1: {"data": [{"id": 1}, {"id": 2}, {"id": 3}]},
            2: {"data": [{"id": 4}, {"id": 5}]},
            3: {"data": []}
        }[params['page[number]']]

        async def _call():
            items = []
            async for item in api.get_cve_package_exclusions(1):
                items.append(item)
            return items

        actual = get_event_loop().run_until_complete(_call())
        _make_request.assert_awaited_with(ANY, 'GET', '/api/v1/cve_package_exclusion', params={'filter[errata_id]': '1', 'page[number]': 3, 'page[size]': 1000})
        self.assertEqual(actual, [{'id': 1}, {'id': 2}, {'id': 3}, {'id': 4}, {'id': 5}])


class TestAsyncErrataUtils(TestCase):
    @patch("elliottlib.errata_async.AsyncErrataAPI", autospec=True)
    def test_get_advisory_cve_package_exclusions(self, FakeAsyncErrataAPI: AsyncMock):
        api = FakeAsyncErrataAPI.return_value
        api.get_cve_package_exclusions.return_value.__aiter__.return_value = [
            {"id": 1, "relationships": {"cve": {"name": "CVE-2099-1"}, "package": {"name": "a"}}},
            {"id": 2, "relationships": {"cve": {"name": "CVE-2099-1"}, "package": {"name": "b"}}},
            {"id": 3, "relationships": {"cve": {"name": "CVE-2099-2"}, "package": {"name": "c"}}},
        ]
        expected = {
            "CVE-2099-1": {"a": 1, "b": 2},
            "CVE-2099-2": {"c": 3},
        }
        actual = get_event_loop().run_until_complete(AsyncErrataUtils.get_advisory_cve_package_exclusions(api, 1))
        self.assertEqual(actual, expected)

    def test_compute_cve_package_exclusions(self):
        cve_components = {
            "CVE-2099-1": {"a", "b"},
            "CVE-2099-2": {"c"},
            "CVE-2099-3": {"openshift-golang-builder-container"},
        }
        attached_builds = ["a-1.0.0-1.el8", "a-1.0.0-1.el7", "b-1.0.0-1.el8", "c-1.0.0-1.el8", "d-1.0.0-1.el8"]
        expected = {
            "CVE-2099-1": {"c": 0, "d": 0},
            "CVE-2099-2": {"a": 0, "b": 0, "d": 0},
            "CVE-2099-3": {'a': 0, 'a': 0, 'b': 0, 'c': 0, 'd': 0},
        }
        actual = AsyncErrataUtils.compute_cve_package_exclusions(attached_builds, cve_components)
        self.assertEqual(actual, expected)

    def test_diff_cve_package_exclusions(self):
        current_cve_package_exclusions = {
            "CVE-2099-1": {"c": 1, "d": 2},
            "CVE-2099-2": {"a": 3, "b": 4, "d": 5},
            "CVE-2099-3": {}
        }
        expected_cve_packages_exclusions = {
            "CVE-2099-1": {"c": 0, "e": 0},
            "CVE-2099-2": {"a": 0, "b": 0, "d": 0},
            "CVE-2099-3": {"e": 0}
        }
        expected_extra = {
            "CVE-2099-1": {"d": 2},
            "CVE-2099-2": {},
            "CVE-2099-3": {},
        }
        expected_misisng = {
            "CVE-2099-1": {"e": 0},
            "CVE-2099-2": {},
            "CVE-2099-3": {"e": 0},
        }
        actual_extra, actual_missing = AsyncErrataUtils.diff_cve_package_exclusions(current_cve_package_exclusions, expected_cve_packages_exclusions)
        self.assertEqual((actual_extra, actual_missing), (expected_extra, expected_misisng))

    @patch("elliottlib.errata_async.AsyncErrataUtils.get_advisory_cve_package_exclusions", autospec=True)
    @patch("elliottlib.errata_async.AsyncErrataAPI", autospec=True)
    def test_associate_builds_with_cves(self, FakeAsyncErrataAPI: AsyncMock, fake_get_advisory_cve_package_exclusions: AsyncMock):
        api = FakeAsyncErrataAPI.return_value
        api.get_cves.return_value = ["CVE-2099-1", "CVE-2099-2", "CVE-2099-3"]
        attached_builds = ["a-1.0.0-1.el8", "a-1.0.0-1.el7", "b-1.0.0-1.el8", "c-1.0.0-1.el8", "d-1.0.0-1.el8", "e-1.0.0-1.el7"]
        cve_components = {
            "CVE-2099-1": {"a", "b", "d"},
            "CVE-2099-2": {"c", "e"},
            "CVE-2099-3": {"a", "b", "c", "d"},
        }
        fake_get_advisory_cve_package_exclusions.return_value = {
            "CVE-2099-1": {"c": 1, "d": 2},
            "CVE-2099-2": {"a": 3, "b": 4, "d": 5},
            "CVE-2099-3": {}
        }
        actual = get_event_loop().run_until_complete(AsyncErrataUtils.associate_builds_with_cves(api, 1, attached_builds, cve_components, dry_run=False))
        api.delete_cve_package_exclusion.assert_any_await(2)
        api.create_cve_package_exclusion.assert_any_await(1, "CVE-2099-1", "e")
        api.create_cve_package_exclusion.assert_any_await(1, "CVE-2099-3", "e")
        self.assertEqual(actual, None)
