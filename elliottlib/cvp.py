
import asyncio
import json
import logging
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple, cast
from urllib.parse import urljoin

import aiohttp
from aiohttp.client_exceptions import (ClientResponseError,
                                       ServerDisconnectedError)
from tenacity import (before_sleep_log, retry, retry_if_exception_type,
                      stop_after_attempt, wait_exponential)

from elliottlib.exectools import limit_concurrency
from elliottlib.imagecfg import ImageMetadata
from elliottlib.resultsdb import ResultsDBAPI
from elliottlib.util import all_same, brew_arch_for_go_arch, parse_nvr


class CVPInspector:

    CVP_TEST_CASE_SANITY = "cvp.rhproduct.default.sanity"

    def __init__(self, group_config: Dict, image_metas: Iterable[ImageMetadata],
                 logger: Optional[logging.Logger] = None) -> None:
        self._resultsdb_api = ResultsDBAPI()
        self._group_config = group_config
        self._image_metas = list(image_metas)
        self._content_set_to_repo_names = {}
        self._load_content_set_to_repo_names()
        self.component_distgit_keys = {}
        self._build_component_distgit_keys()
        self._logger = logger or logging.getLogger(__name__)

        # build log cache dict; keys are (nvr, arch) tuples, values are logs
        self._build_log_cache: Dict[Tuple[str, str], List[str]] = {}

    async def close(self):
        await self._resultsdb_api.close()

    async def latest_sanity_test_results(self, nvrs: Iterable[str]) -> Dict[str, Optional[Dict]]:
        """ Get latest CVP test results for specified build NVRs
        """
        nvr_results = {}
        nvrs = set(nvrs)
        results = await self._resultsdb_api.get_latest_results((self.CVP_TEST_CASE_SANITY, ), nvrs)
        for r in results:
            nvr = r["data"]["item"][0]
            if nvr in nvr_results:
                raise KeyError(f"Found duplicated CVP test results for NVR {nvr}: {r}, {nvr_results[nvr]}")
            nvr_results[nvr] = r
        for nvr in nvrs - nvr_results.keys():
            nvr_results[nvr] = None  # missing result
        return nvr_results

    def categorize_test_results(self, nvr_results: Dict[str, Optional[Dict]]):
        """ Categorize CVP sanity test results
        :return: (passed, failed, missing)
        """
        missing = {}
        passed = {}
        failed = {}
        # only PASSED, FAILED, INFO, NEEDS_INSPECTION are now valid outcome values (https://resultsdb20.docs.apiary.io/#introduction/changes-since-1.0)
        PASSED_OUTCOMES = {"PASSED", "INFO"}
        FAILED_OUTCOMES = {"NEEDS_INSPECTION", "FAILED"}
        for nvr, result in nvr_results.items():
            if not result:
                missing[nvr] = result
                continue
            outcome = result["outcome"]
            if outcome in PASSED_OUTCOMES:
                passed[nvr] = result
            elif outcome in FAILED_OUTCOMES:
                failed[nvr] = result
            else:
                raise ValueError(f"Unrecognized CVP test result outcome: {outcome}")
        return passed, failed, missing

    async def get_sanity_test_optional_results(self, test_results: Iterable[Dict]):
        @retry(reraise=True, stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=10),
               retry=(retry_if_exception_type((ServerDisconnectedError, ClientResponseError))),
               before_sleep=before_sleep_log(self._logger, logging.WARNING))
        @limit_concurrency(limit=32)
        async def _fetch(url):
            r = await session.get(url)
            if r.status == 404:
                return None
            r.raise_for_status()
            text = await r.text()  # can't use r.json() because the url doesn't return correct content-type
            return json.loads(text)

        async with aiohttp.ClientSession() as session:
            futures = []
            for cvp_result in test_results:
                # Each CVP test result stored in ResultsDB has a link to an external storage with more CVP test details
                # e.g. https://external-ci-coldstorage.datahub.redhat.com/cvp/cvp-product-test/openshift-enterprise-console-container-v4.9.0-202205181110.p0.ge43e6e7.assembly.art2675/edef5ab1-62fb-480e-b0da-f63ce6d19d28/
                url = urljoin(cvp_result["ref_url"], "sanity-tests-optional-results.json")
                # example results https://external-ci-coldstorage.datahub.redhat.com/cvp/cvp-product-test/openshift-enterprise-console-container-v4.9.0-202205181110.p0.ge43e6e7.assembly.art2675/edef5ab1-62fb-480e-b0da-f63ce6d19d28/sanity-tests-optional-results.json
                futures.append(_fetch(url))
            optional_results = await asyncio.gather(*futures)
        return optional_results

    def categorize_sanity_test_optional_results(self, nvr_results: Dict[str, Optional[Dict]], included_checks: Set[str] = set()):
        """ Categorize CVP sanity test optional results
        :return: (passed, failed, missing)
        """
        missing = {}
        passed = {}
        failed = {}
        for nvr, result in nvr_results.items():
            if not result:
                missing[nvr] = result
                continue
            failed_checks = [check["name"] for check in result["checks"] if (not included_checks or check["name"] in included_checks) and not check["ok"]]
            if failed_checks:
                failed[nvr] = result
            else:
                passed[nvr] = result
        return passed, failed, missing

    async def diagnostic_sanity_test_optional_checks(self, build: Dict, checks: List[Dict], included_checks: Set[str] = set()):
        if not checks:
            return None
        bad_checks = [check for check in checks if not check["ok"]]
        report = {}
        for check in bad_checks:
            if check["name"] not in included_checks:
                continue
            self._logger.info(f"* {check['name']} {check['status']}")
            if check['name'] == "content_set_check":
                try:
                    examination_report = await self.diagnostic_content_set_check(build, check)
                    report[check['name']] = examination_report
                except Exception as e:
                    self._logger.warning(f"Error processing sanity_test_optional_checks result for {build['nvr']} :{e}")
        return report

    async def diagnostic_content_set_check(self, build: Dict, check: Dict):
        # example `check` dict:
        # {
        #     "name": "content_set_check",
        #     "ok": true,
        #     "status": "PASS",
        #     "description": "Content sets defined in Dist-git have to match with rpm content which is installed in the image",
        #     "message": "Content sets in content_sets.yml have to be correct",
        #     "reference_url": "https://source.redhat.com/groups/public/container-build-system/container_build_system_wiki/guide_to_layered_image_build_service_osbs#jive_content_id_Content_set_information",
        #     "logs": [
        #         "Checking CS of build: openshift-enterprise-console-container-v4.9.0-202205181110.p0.ge43e6e7.assembly.art2675.s390x",
        #         "Checking CS of build: openshift-enterprise-console-container-v4.9.0-202205181110.p0.ge43e6e7.assembly.art2675.ppc64le",
        #         "Checking CS of build: openshift-enterprise-console-container-v4.9.0-202205181110.p0.ge43e6e7.assembly.art2675.amd64",
        #         "Checking CS of build: openshift-enterprise-console-container-v4.9.0-202205181110.p0.ge43e6e7.assembly.art2675.arm64",
        #         [
        #             {
        #                 "nvr": "openshift-enterprise-console-container-v4.9.0-202205181110.p0.ge43e6e7.assembly.art2675",
        #                 "arch": "s390x",
        #                 "unreleased_rpms": [],
        #                 "not_covered_parent_image_rpms": [],
        #                 "not_covered_rpms": [],
        #                 "redundant_cs": [],
        #                 "dist_git_cs": [
        #                     "rhel-8-for-s390x-appstream-eus-rpms__8_DOT_4",
        #                     "rhel-8-for-s390x-baseos-eus-rpms__8_DOT_4"
        #                 ]
        #             },
        #             {
        #                 "nvr": "openshift-enterprise-console-container-v4.9.0-202205181110.p0.ge43e6e7.assembly.art2675",
        #                 "arch": "ppc64le",
        #                 "unreleased_rpms": [],
        #                 "not_covered_parent_image_rpms": [],
        #                 "not_covered_rpms": [],
        #                 "redundant_cs": [],
        #                 "dist_git_cs": [
        #                     "rhel-8-for-ppc64le-appstream-eus-rpms__8_DOT_4",
        #                     "rhel-8-for-ppc64le-baseos-eus-rpms__8_DOT_4"
        #                 ]
        #             },
        #             {
        #                 "nvr": "openshift-enterprise-console-container-v4.9.0-202205181110.p0.ge43e6e7.assembly.art2675",
        #                 "arch": "amd64",
        #                 "unreleased_rpms": [],
        #                 "not_covered_parent_image_rpms": [],
        #                 "not_covered_rpms": [],
        #                 "redundant_cs": [],
        #                 "dist_git_cs": [
        #                     "rhel-8-for-x86_64-appstream-eus-rpms__8_DOT_4",
        #                     "rhel-8-for-x86_64-baseos-eus-rpms__8_DOT_4"
        #                 ]
        #             },
        #             {
        #                 "nvr": "openshift-enterprise-console-container-v4.9.0-202205181110.p0.ge43e6e7.assembly.art2675",
        #                 "arch": "arm64",
        #                 "unreleased_rpms": [],
        #                 "not_covered_parent_image_rpms": [],
        #                 "not_covered_rpms": [],
        #                 "redundant_cs": [],
        #                 "dist_git_cs": [
        #                     "rhel-8-for-aarch64-appstream-eus-rpms__8_DOT_4",
        #                     "rhel-8-for-aarch64-baseos-eus-rpms__8_DOT_4"
        #                 ]
        #             }
        #         ]
        #     ]
        # },
        nvr: str = build["nvr"]
        check_details = check["logs"][-1]
        if not isinstance(check_details, list):
            raise ValueError(f"Invalid value in CVP logs: {check_details}")
        check_details = cast(List[Dict], check_details)
        report = {}
        for item in check_details:
            arch = brew_arch_for_go_arch(item["arch"])
            report.setdefault("unreleased_rpms", {}).setdefault("symptom", {})[arch] = item["unreleased_rpms"]
            report.setdefault("not_covered_parent_image_rpms", {}).setdefault("symptom", {})[arch] = item["not_covered_parent_image_rpms"]
            report.setdefault("not_covered_rpms", {}).setdefault("symptom", {})[arch] = item["not_covered_rpms"]
            report.setdefault("redundant_cs", {}).setdefault("symptom", {})[arch] = item["redundant_cs"]

        async def _get_build_log(nvr: str, arch: str):
            build_log = self._build_log_cache.get((nvr, arch))
            if not build_log:
                orig_build_log = await self._fetch_build_log(nvr, arch)
                self._logger.info("Processing build log...")
                # looking for lines in brew logs like
                # `2020-07-18 10:52:00,888 - atomic_reactor.plugins.imagebuilder - INFO -  java-11-openjdk      i686   1:11.0.8.10-0.el7_8 rhel-server-rpms-x86_64  215 k`
                pattern = re.compile(r"atomic_reactor\.(?:plugins\.imagebuilder|tasks\.binary_container_build) - INFO -\s+(?P<name>[\w.-]+)\s+(?P<arch>\w+)\s+(?P<VRE>[\w.:-]+)\s+(?P<repo>[\w.-]+)\s+(?P<size>[\d.]+\s+\w)")
                self._build_log_cache[(nvr, arch)] = build_log = [line for line in orig_build_log.splitlines() if line and pattern.search(line)]
            return build_log

        for test_name, value in report.items():
            symptom = value["symptom"]
            passed = all(map(lambda arch: not symptom[arch], symptom))
            value["outcome"] = "PASSED" if passed else "FAILED"
            if passed:
                del value["symptom"]
                continue
            prescription = value["prescription"] = []
            if test_name == "redundant_cs":
                used_repos = {}
                unused_repos = {}
                for arch, content_sets in symptom.items():
                    build_log = await _get_build_log(nvr, arch)
                    repos = {self._content_set_to_repo_names[cs] for cs in content_sets}
                    used_repos[arch] = {repo for repo in repos if any(map(lambda line: f"{repo}-{arch}" in line, build_log))}
                    unused_repos[arch] = repos - used_repos[arch]
                if all_same(used_repos.values()):
                    t = next(iter(used_repos.values()))
                    if t:
                        prescription.append({
                            "action": "add_non_shipping_repos",
                            "value": sorted(t),
                        })
                else:
                    prescription.append({
                        "action": "warn",
                        "note": "Inconsistent used repos among arches",
                        "value": {k: sorted(used_repos[k]) for k in sorted(used_repos)},
                    })
                if all_same(unused_repos.values()):
                    t = next(iter(unused_repos.values()))
                    if t:
                        prescription.append({
                            "action": "remove_repos",
                            "value": sorted(t),
                        })
                else:
                    prescription.append({
                        "action": "warn",
                        "note": "Inconsistent unused repos among arches",
                        "value": {k: sorted(unused_repos[k]) for k in sorted(unused_repos)},
                    })

            elif test_name == "not_covered_rpms":
                missing_repos: Dict[str, Set[str]] = {}
                rpms_not_found: Dict[str, Set[str]] = {}
                unknown_repos: Dict[str, Set[str]] = {}
                for arch, rpms in symptom.items():
                    missing_repos[arch] = set()
                    rpms_not_found[arch] = set()
                    build_log = await _get_build_log(nvr, arch)
                    for rpm in rpms:
                        rpm_nvr = parse_nvr(rpm)
                        rpm_release, rpm_arch = rpm_nvr["release"].rsplit(".", 1)
                        # looking for lines in brew logs like
                        # `2020-07-18 10:52:00,888 - atomic_reactor.plugins.imagebuilder - INFO -  java-11-openjdk      i686   1:11.0.8.10-0.el7_8 rhel-server-rpms-x86_64  215 k`
                        found = False
                        for line in build_log:
                            if rpm_nvr["name"] in line and rpm_nvr["version"] in line and rpm_release in line and rpm_arch in line:
                                line_split = line.split()
                                repo_name = line_split[-3].rsplit("-", 1)[0]  # rhel-server-rpms-x86_64 ==> rhel-server-rpms
                                if not self._group_config.get("repos", {}).get(repo_name):
                                    unknown_repos.setdefault(arch, set()).add(repo_name)
                                else:
                                    missing_repos[arch].add(repo_name)
                                found = True
                                break
                        if not found:
                            self._logger.warning("Couldn't determine which repo has rpm %s in image %s %s", rpm, nvr, arch)
                            rpms_not_found[arch].add(rpm)
                if all_same(missing_repos.values()):
                    t = next(iter(missing_repos.values()))
                    if t:
                        prescription.append({
                            "action": "add_repos",
                            "value": sorted(t),
                        })
                else:
                    prescription.append({
                        "action": "warn",
                        "note": "Inconsistent missing repos among arches",
                        "value": {k: sorted(missing_repos[k]) for k in sorted(missing_repos)},
                    })
                if unknown_repos:
                    prescription.append({
                        "action": "warn",
                        "note": "Repos used in build are unknown to ocp-build-data",
                        "value": {k: sorted(unknown_repos[k]) for k in sorted(unknown_repos)},
                    })
                if any(map(lambda arch: rpms_not_found[arch], rpms_not_found)):
                    t = next(iter(rpms_not_found.values()))
                    prescription.append({
                        "action": "warn",
                        "note": "Didn't find rpms in build logs. CVP bug?",
                        "value": {k: sorted(rpms_not_found[k]) for k in sorted(rpms_not_found)},
                    })

            elif test_name == "not_covered_parent_image_rpms":
                parent_builds = self._get_parent_builds(build)
                for b in parent_builds:
                    nvre = parse_nvr(b["nvr"])
                    dg_key = self.component_distgit_keys.get(nvre["name"])
                    if dg_key:
                        b["dg_key"] = dg_key
                prescription.append({
                    "action": "see_parent_builds",
                    "value": parent_builds,
                })

        return report

    @staticmethod
    def _get_parent_builds(build: Dict):
        parents = list(build["extra"]["image"]["parent_image_builds"].values())
        return parents

    def _load_content_set_to_repo_names(self):
        for repo_name, repo_info in self._group_config.get("repos", {}).items():
            for arch, cs_name in repo_info.get('content_set', {}).items():
                if arch == "optional":
                    continue  # not a real arch name
                self._content_set_to_repo_names[cs_name] = repo_name

    def _build_component_distgit_keys(self):
        for image in self._image_metas:
            self.component_distgit_keys[image.get_component_name()] = image.distgit_key

    @limit_concurrency(limit=32)
    async def _fetch_build_log(self, nvr, arch):
        nvre = parse_nvr(nvr)
        url = f"https://download.eng.bos.redhat.com/brewroot/packages/{nvre['name']}/{nvre['version']}/{nvre['release']}/data/logs/{arch}.log"
        self._logger.info("Fetching build log for %s %s (%s)", nvr, arch, url)
        async with aiohttp.ClientSession() as session:
            async with await session.get(url) as response:
                response.raise_for_status()
                log = await response.text()
        self._logger.info("Done fetching build log for %s %s (%s)", nvr, arch, url)
        return log
