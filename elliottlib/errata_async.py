import asyncio
import base64
import logging
from typing import Dict, Iterable, List, Set, Union
from urllib.parse import quote, urlparse

import aiohttp
import gssapi
from kobo.rpmlib import parse_nvr

_LOGGER = logging.getLogger(__name__)


class AsyncErrataAPI:
    def __init__(self, url: str):
        self._errata_url = urlparse(url).geturl()
        self._session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=32, force_close=True))
        self._gssapi_client_ctx = None
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def login(self):
        if self._gssapi_client_ctx:
            return  # already logged in
        server_name = gssapi.Name(f"HTTP@{urlparse(self._errata_url).hostname}", gssapi.NameType.hostbased_service)
        client_ctx = gssapi.SecurityContext(name=server_name, usage='initiate')
        out_token = client_ctx.step(b"")
        self._gssapi_client_ctx = client_ctx
        self._headers["Authorization"] = 'Negotiate ' + base64.b64encode(out_token).decode()

    async def close(self):
        await self._session.close()

    async def _make_request(self, method: str, path: str, parse_json: bool = True, **kwargs) -> Union[Dict, bytes]:
        if "headers" not in kwargs:
            kwargs["headers"] = self._headers
        async with self._session.request(method, self._errata_url + path, **kwargs) as resp:
            resp.raise_for_status()
            result = await (resp.json() if parse_json else resp.read())
        return result

    async def get_advisory(self, advisory: Union[int, str]) -> Dict:
        path = f"/api/v1/erratum/{quote(str(advisory))}"
        return await self._make_request(aiohttp.hdrs.METH_GET, path)

    async def get_builds(self, advisory: Union[int, str]):
        path = f"/api/v1/erratum/{quote(str(advisory))}/builds_list"
        return await self._make_request(aiohttp.hdrs.METH_GET, path)

    async def get_builds_flattened(self, advisory: Union[int, str]) -> Set[str]:
        pv_builds = await self.get_builds(advisory)
        return {
            nvr for pv in pv_builds.values() for pvb in pv["builds"] for nvr in pvb
        }

    async def get_cves(self, advisory: Union[int, str]) -> List[str]:
        # Errata API "/cve/show/{advisory}.json" doesn't return the correct CVEs for some RHSAs.
        # Not sure if it's an Errata bug. Use a different approach instead.
        return (await self.get_advisory(advisory))["content"]["content"]["cve"].split()

    async def get_cve_package_exclusions(self, advisory_id: int):
        path = "/api/v1/cve_package_exclusion"
        # This is a paginated API, we need to increment page[number] until an empty array is returned.
        params = {"filter[errata_id]": str(int(advisory_id)), "page[number]": 1}
        while True:
            result = await self._make_request(aiohttp.hdrs.METH_GET, path, params=params)
            data: List[Dict] = result.get('data', [])
            if not data:
                break
            for item in data:
                yield item
            params["page[number]"] += 1

    async def create_cve_package_exclusion(self, advisory_id: int, cve: str, package: str):
        path = "/api/v1/cve_package_exclusion"
        data = {
            "cve": cve,
            "errata": advisory_id,
            "package": package,
        }
        return await self._make_request(aiohttp.hdrs.METH_POST, path, json=data)

    async def delete_cve_package_exclusion(self, exclusion_id: int):
        path = f"/api/v1/cve_package_exclusion/{int(exclusion_id)}"
        await self._make_request(aiohttp.hdrs.METH_DELETE, path, parse_json=False)


class AsyncErrataUtils:
    @classmethod
    async def get_advisory_cve_package_exclusions(cls, api: AsyncErrataAPI, advisory_id: int):
        """ This is a wrapper around `AsyncErrataAPI.get_cve_package_exclusions`.
        The result value of original Errata API call `get_cve_package_exclusions` is not user friendly.
        This method converts the result value into a better data structure.
        :return: a dict that key is CVE name, value is another dict with package name as key and exclusion_id as value
        """
        current_cve_package_exclusions: Dict[str, Dict[str, int]] = {}
        async for cve_package_exclusion in api.get_cve_package_exclusions(advisory_id):
            current_cve_package_exclusions.setdefault(cve_package_exclusion["relationships"]["cve"]["name"], {})[cve_package_exclusion["relationships"]["package"]["name"]] = cve_package_exclusion["id"]
        return current_cve_package_exclusions

    @classmethod
    def compute_cve_package_exclusions(cls, attached_builds: Iterable[str], expected_cve_components: Dict[str, Set[str]]):
        """ Compute cve_package_exclusions from a list of attached builds and CVE-components mapping.
        :param attached_builds: list of NVRs
        :param expected_cve_components: a dict mapping each CVE to a list of brew components
        :return: a dict that key is CVE name, value is another dict with package name as key and 0 as value
        """
        brew_components = {parse_nvr(nvr)["name"] for nvr in attached_builds}
        missing_brew_brew_components = {c for components in expected_cve_components.values() for c in components} - brew_components
        if missing_brew_brew_components:
            raise ValueError(f"Missing builds for brew component(s): {missing_brew_brew_components}")
        cve_packages_exclusions = {
            cve: {pkg: 0 for pkg in brew_components - components}
            for cve, components in expected_cve_components.items()
        }
        return cve_packages_exclusions

    @classmethod
    def diff_cve_package_exclusions(cls, current_cve_package_exclusions: Dict[str, Dict[str, int]], expected_cve_packages_exclusions: Dict[str, Dict[str, int]]):
        """ Given 2 cve_package_exclusions dicts, return the difference.
        :return: (extra_cve_package_exclusions, missing_cve_package_exclusions)
        """
        extra_cve_package_exclusions = {cve: {pkg: exclusions[pkg] for pkg in exclusions.keys() - expected_cve_packages_exclusions.get(cve, {}).keys()} for cve, exclusions in current_cve_package_exclusions.items()}
        missing_cve_package_exclusions = {cve: {pkg: exclusions[pkg] for pkg in exclusions.keys() - current_cve_package_exclusions.get(cve, {}).keys()} for cve, exclusions in expected_cve_packages_exclusions.items()}
        return extra_cve_package_exclusions, missing_cve_package_exclusions

    @classmethod
    async def associate_builds_with_cves(cls, api: AsyncErrataAPI, advisory_id: int, attached_builds: List[str], cve_components_mapping: Dict[str, Set[str]], dry_run=False):
        """ Request Errata to associate CVEs to attached Brew builds
        :param api: Errata API
        :param advisory_id: advisory id
        :param attached_builds: list of attached Brew build NVRs
        :param cve_components_mapping: a dict mapping each CVE to a list of brew components
        """
        _LOGGER.info("Getting associated CVEs for advisory %s", advisory_id)
        advisory_cves = await api.get_cves(advisory_id)

        extra_cves = cve_components_mapping.keys() - advisory_cves
        if extra_cves:
            raise ValueError(f"The following CVEs are not associated with advisory {advisory_id}: {', '.join(sorted(extra_cves))}")
        missing_cves = advisory_cves - cve_components_mapping.keys()
        if missing_cves:
            raise ValueError(f"Tracker bugs for the following CVEs associated with advisory {advisory_id} are not attached: {', '.join(sorted(missing_cves))}")

        _LOGGER.info("Getting current CVE package exclusions for advisory %s", advisory_id)
        current_cve_package_exclusions = await cls.get_advisory_cve_package_exclusions(api, advisory_id)
        _LOGGER.info("Comparing current CVE package exclusions with expected ones for advisory %s", advisory_id)
        expected_cve_packages_exclusions = cls.compute_cve_package_exclusions(attached_builds, cve_components_mapping)
        extra_cve_package_exclusions, missing_cve_package_exclusions = cls.diff_cve_package_exclusions(current_cve_package_exclusions, expected_cve_packages_exclusions)

        _LOGGER.info("Reconciling CVE package exclusions for advisory %s", advisory_id)
        if dry_run:
            _LOGGER.warning("[DRY RUN] Would have Reconciled CVE package exclusions for advisory %s", advisory_id)
            return
        futures = []
        for cve, exclusions in extra_cve_package_exclusions.items():
            for package, exclusion_id in exclusions.items():
                futures.append(api.delete_cve_package_exclusion(exclusion_id))

        for cve, exclusions in missing_cve_package_exclusions.items():
            for package in exclusions:
                futures.append(api.create_cve_package_exclusion(advisory_id, cve, package))

        await asyncio.gather(*futures)
        _LOGGER.info("Reconciled CVE package exclusions for advisory %s", advisory_id)
