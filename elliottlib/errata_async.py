import asyncio
import base64
from typing import Dict, Iterable, List, Set, Union
from urllib.parse import quote, urlparse
from aiohttp import ClientResponseError, ClientTimeout

import aiohttp
import gssapi
from elliottlib.exectools import limit_concurrency

from elliottlib.rpm_utils import parse_nvr
from elliottlib import constants, util, logutil

_LOGGER = logutil.getLogger(__name__)


class AsyncErrataAPI:
    def __init__(self, url: str = constants.errata_url):
        self._errata_url = urlparse(url).geturl()
        self._timeout = ClientTimeout(total=60 * 15)  # 900 seconds (15 min)
        self._errata_gssapi_name = gssapi.Name(f"HTTP@{urlparse(self._errata_url).hostname}", gssapi.NameType.hostbased_service)
        self._gssapi_flags = [gssapi.RequirementFlag.out_of_sequence_detection]
        self._session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=32, force_close=True), timeout=self._timeout)
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def close(self):
        await self._session.close()

    def _generate_auth_header(self):
        client_ctx = gssapi.SecurityContext(name=self._errata_gssapi_name, usage='initiate', flags=self._gssapi_flags)
        out_token = client_ctx.step(b"")
        return f'Negotiate {base64.b64encode(out_token).decode()}'

    async def _make_request(self, method: str, path: str, parse_json: bool = True, **kwargs) -> Union[Dict, bytes]:
        auth_header = self._generate_auth_header()
        headers = self._headers.copy()
        headers["Authorization"] = auth_header
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        async with self._session.request(method, self._errata_url + path, headers=headers, **kwargs) as resp:
            resp.raise_for_status()
            result = await (resp.json() if parse_json else resp.read())
        return result

    async def get_advisory(self, advisory: Union[int, str]) -> Dict:
        path = f"/api/v1/erratum/{quote(str(advisory))}"
        return await self._make_request(aiohttp.hdrs.METH_GET, path)

    async def get_builds(self, advisory: Union[int, str]):
        # As of May 25, 2023, /api/v1/erratum/{id}/builds_list doesn't return all builds.
        # Use /api/v1/erratum/{id}/builds instead.
        path = f"/api/v1/erratum/{quote(str(advisory))}/builds"
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
        params = {"filter[errata_id]": str(int(advisory_id)), "page[number]": 1, "page[size]": 1000}
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

    @limit_concurrency(limit=16)
    async def get_advisories_for_jira(self, jira_key: str, ignore_not_found=False):
        path = f"/jira_issues/{quote(jira_key)}/advisories.json"
        try:
            result = await self._make_request(aiohttp.hdrs.METH_GET, path)
        except ClientResponseError as e:
            # When newly created jira bugs are not sync'd to ET we get a 404,
            # assume that they are not attached to any advisory
            if ignore_not_found and e.status == 404:
                result = []
            else:
                raise
        return result

    @limit_concurrency(limit=16)
    async def get_advisories_for_bug(self, bz_key: str):
        path = f"/bugs/{bz_key}/advisories.json"
        return await self._make_request(aiohttp.hdrs.METH_GET, path)


class AsyncErrataUtils:
    @classmethod
    async def get_advisory_cve_exclusions(cls, api: AsyncErrataAPI, advisory_id: int):
        """ This is a wrapper around `AsyncErrataAPI.get_cve_package_exclusions`.
        The result value of original Errata API call `get_cve_package_exclusions` is not user-friendly.
        This method converts the result value into a better data structure.
        :return: a dict that key is CVE name, value is another dict with package name as key and exclusion_id as value
        """
        current_exclusions: Dict[str, Dict[str, int]] = {}
        async for ex in api.get_cve_package_exclusions(advisory_id):
            current_exclusions.setdefault(ex["relationships"]["cve"]["name"], {})[ex["relationships"]["package"]["name"]] = ex["id"]
        return current_exclusions

    @classmethod
    def compute_cve_exclusions(cls, attached_builds: Iterable[str], expected_cve_components: Dict[str, Set[str]]):
        """ Compute cve package exclusions from a list of attached builds and CVE-components mapping.
        :param attached_builds: list of NVRs
        :param expected_cve_components: a dict mapping each CVE to a list of brew components
        :return: a dict that key is CVE name, value is another dict with package name as key and 0 as value
        """
        attached_brew_components = {parse_nvr(nvr)["name"] for nvr in attached_builds}

        # separate out golang CVEs and non-golang CVEs
        # expected_brew_components contain non-golang CVEs components for regular analysis
        # All golang CVEs will have component as constants.GOLANG_BUILDER_CVE_COMPONENT
        # which we do not attach to our advisories since it's a builder image
        # It requires special treatment
        expected_brew_components = set()
        golang_cve_names = set()
        for cve_name, components in expected_cve_components.items():
            if constants.GOLANG_BUILDER_CVE_COMPONENT not in components:
                expected_brew_components.update(components)
            else:
                golang_cve_names.add(cve_name)

        missing_brew_components = expected_brew_components - attached_brew_components
        if missing_brew_components:
            raise ValueError(f"Missing builds for brew component(s): {missing_brew_components}")

        if golang_cve_names:
            expected_cve_components = cls.populate_golang_cve_components(golang_cve_names,
                                                                         expected_cve_components,
                                                                         attached_builds)

        cve_exclusions = {
            cve_name: {pkg: 0 for pkg in attached_brew_components - components}
            for cve_name, components in expected_cve_components.items()
        }
        return cve_exclusions

    @classmethod
    def populate_golang_cve_components(cls, golang_cve_names, expected_cve_components, attached_builds):
        # Get go builder images for all attached image builds
        parsed_nvrs = [(n['name'], n['version'], n['release']) for n in [parse_nvr(n) for n in attached_builds]]
        go_nvr_map = util.get_golang_container_nvrs(parsed_nvrs, _LOGGER)

        # image advisory should have maximum 3 go build versions - one for etcd and
        # possibly 2 (rhelX and rhelX+1) for all other images
        # in case of other image advisories, there should max be 2
        if len(go_nvr_map) > 3:
            raise ValueError(f"Unexpected go build versions found {go_nvr_map.keys()}. "
                             "There should not be more than 3: 1 for etcd and maximum 2 for all other images. "
                             "Please investigate")

        etcd_golang_builder, base_golang_builders = None, []
        for builder_nvr_string in go_nvr_map.keys():
            builder_nvr = parse_nvr(builder_nvr_string)

            # Make sure they are go builder nvrs (this should never happen)
            if builder_nvr['name'] != constants.GOLANG_BUILDER_CVE_COMPONENT:
                raise ValueError(f"Unexpected `name` value for nvr {builder_nvr}. Expected "
                                 f"{constants.GOLANG_BUILDER_CVE_COMPONENT}. Please investigate.")

            if len(go_nvr_map[builder_nvr_string]) == 1 and 'etcd' in list(go_nvr_map[builder_nvr_string])[0]:
                etcd_golang_builder = builder_nvr_string
            else:
                base_golang_builders.append(builder_nvr_string)

        # Now try to map CVEs to {etcd, rhelX, rhelX+1} builders
        # TODO: Figure out how to find out if a golang CVE only affects etcd
        # For now we map CVEs to base_golang build images

        if etcd_golang_builder:
            _LOGGER.warning(f'etcd build found in advisory {go_nvr_map[etcd_golang_builder][0]}, with builder: '
                            f'{etcd_golang_builder}. If an attached CVE affects etcd please manually associate CVE '
                            'with etcd build')

        for cve_name in golang_cve_names:
            nvrs = set()
            for base_golang_builder in base_golang_builders:
                nvrs.update({nvr[0] for nvr in go_nvr_map[base_golang_builder]})
            _LOGGER.info(f"Associating golang {cve_name} with golang "
                         f"images ({len(nvrs)})")
            expected_cve_components[cve_name] = nvrs

        return expected_cve_components

    @classmethod
    def diff_cve_exclusions(cls, current_exclusions: Dict[str, Dict[str, int]],
                            expected_exclusions: Dict[str, Dict[str, int]]):
        """ Given 2 cve_package_exclusions dicts, return the difference.
        :return: (extra_exclusions, missing_exclusions)
        """
        extra_exclusions = {cve: {pkg: exclusions[pkg] for pkg in exclusions.keys()
                                  - expected_exclusions.get(cve, {}).keys()}
                            for cve, exclusions in current_exclusions.items()}
        missing_exclusions = {cve: {pkg: exclusions[pkg] for pkg in exclusions.keys()
                                    - current_exclusions.get(cve, {}).keys()}
                              for cve, exclusions in expected_exclusions.items()}
        return extra_exclusions, missing_exclusions

    @classmethod
    async def validate_cves_and_get_exclusions_diff(cls, api: AsyncErrataAPI, advisory_id: int, attached_builds: List[
                                                    str], cve_components_mapping: Dict[str, Dict]):
        _LOGGER.info("Getting associated CVEs for advisory %s", advisory_id)
        advisory_cves = await api.get_cves(advisory_id)

        extra_cves = cve_components_mapping.keys() - advisory_cves
        if extra_cves:
            raise ValueError(f"The following CVEs does not seem to be associated with advisory {advisory_id}: "
                             f"{', '.join(sorted(extra_cves))}. Make sure CVE names field in advisory"
                             f"is consistent with CVEs that are attached (`elliott attach-cve-flaws` is your friend)")

        missing_cves = advisory_cves - cve_components_mapping.keys()
        if missing_cves:
            raise ValueError(f"Tracker bugs for the following CVEs associated with advisory {advisory_id} "
                             f"are not attached: {', '.join(sorted(missing_cves))}. Either attach trackers or remove "
                             f"associated flaw bug (`elliott verify-attached-bugs` is your friend) and remove {missing_cves}"
                             " from the CVE names field in advisory")

        _LOGGER.info("Getting current CVE package exclusions for advisory %s", advisory_id)
        current_exclusions = await cls.get_advisory_cve_exclusions(api, advisory_id)
        _LOGGER.info("Comparing current CVE package exclusions with expected ones for advisory %s", advisory_id)
        expected_exclusions = cls.compute_cve_exclusions(attached_builds, cve_components_mapping)
        extra_exclusions, missing_exclusions = cls.diff_cve_exclusions(current_exclusions, expected_exclusions)
        return extra_exclusions, missing_exclusions

    @classmethod
    async def associate_builds_with_cves(cls, api: AsyncErrataAPI, advisory_id: int, attached_builds: List[str],
                                         cve_components_mapping: Dict[str, Dict], dry_run=False):
        """ Request Errata to associate CVEs to attached Brew builds
        :param api: Errata API
        :param advisory_id: advisory id
        :param attached_builds: list of attached Brew build NVRs
        :param cve_components_mapping: a dict mapping each CVE to a dict containing flaw bug and brew components
        """

        extra_exclusions, missing_exclusions = await cls.validate_cves_and_get_exclusions_diff(api,
                                                                                               advisory_id,
                                                                                               attached_builds,
                                                                                               cve_components_mapping)
        _LOGGER.info("Reconciling CVE package exclusions for advisory %s", advisory_id)
        if dry_run:
            _LOGGER.warning("[DRY RUN] Would have Reconciled CVE package exclusions for advisory %s", advisory_id)
            return
        futures = []
        for cve, exclusions in extra_exclusions.items():
            for package, exclusion_id in exclusions.items():
                futures.append(api.delete_cve_package_exclusion(exclusion_id))

        for cve, exclusions in missing_exclusions.items():
            for package in exclusions:
                futures.append(api.create_cve_package_exclusion(advisory_id, cve, package))

        await asyncio.gather(*futures)
        _LOGGER.info("Reconciled CVE package exclusions for advisory %s", advisory_id)
