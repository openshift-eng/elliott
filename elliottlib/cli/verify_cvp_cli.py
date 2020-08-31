import asyncio
import json
import pathlib
import re
import sys
from typing import Iterator, List
from urllib.parse import urldefrag

import aiohttp
import click
import koji
import requests
from ruamel.yaml import YAML

import elliottlib
from elliottlib import Runtime, brew, constants
from elliottlib.cli.common import (cli, click_coroutine, find_default_advisory,
                                   pass_runtime, use_default_advisory_option)
from elliottlib.imagecfg import ImageMetadata
from elliottlib.resultsdb import ResultsDBAPI
from elliottlib.util import (green_prefix, parallel_results_with_progress,
                             red_prefix, red_print, yellow_print)

yaml = YAML()


@cli.command("verify-cvp", short_help="Verify CVP test results")
@click.option(
    '--all', 'all_images', required=False, is_flag=True,
    help='Verify all latest image builds (default to False)')
@click.option(
    '--build', '-b', 'nvrs',
    multiple=True, metavar='NVR_OR_ID',
    help='Only verify specified builds')
@click.option(
    '--include-optional-check', "optional_checks",
    multiple=True, metavar='OPTIONAL_CVP_CHECK_NAME',
    help="Also print failed optional CVP checks. e.g. content_set_check")
@click.option(
    '--all-optional-checks', "all_optional_checks", is_flag=True,
    help="If set, print all failed optional CVP checks")
@click.option(
    '--fix', "fix", is_flag=True,
    help="Try to fix failed all_optional_checks. Currently only supports fixing redundant content sets. See --help for more details")
@click.option(
    '--message', '-m', 'message', metavar='COMMIT_MESSAGE',
    help='Commit message for ocp-build-data when using `--fix`. If not given, no changes will be committed.')
@pass_runtime
@click_coroutine
async def verify_cvp_cli(runtime: Runtime, all_images, nvrs, optional_checks, all_optional_checks, fix, message):
    """ Verify CVP test results

    Example 1: Verify CVP test results for all latest 4.4 image builds, also warn those with failed content_set_check

    $ elliott --group openshift-4.4 verify-cvp --all --include-optional-check content_set_check

    Example 2: Apply patches to ocp-build-data to fix the redundant content sets error:

    $ elliott --group openshift-4.4 verify-cvp --all --include-optional-check content_set_check --fix

    Note:
    1. If `--message` is not given, `--fix` will leave changed ocp-build-data files uncommitted.
    2. Make sure your ocp-build-data directory is clean before running `--fix`.
    """
    if bool(all_images) + bool(nvrs) != 1:
        raise click.BadParameter('You must use one of --all or --build.')
    if all_optional_checks and optional_checks:
        raise click.BadParameter('Use only one of --all-optional-checks or --include-optional-check.')

    runtime.initialize(mode='images')
    tag_pv_map = runtime.gitdata.load_data(key='erratatool', replace_vars=runtime.group_config.vars.primitive() if runtime.group_config.vars else {}).data.get('brew_tag_product_version_mapping')
    brew_session = koji.ClientSession(runtime.group_config.urls.brewhub or constants.BREW_HUB)

    builds = []
    if all_images:
        runtime.logger.info("Getting latest image builds from Brew...")
        builds = get_latest_image_builds(brew_session, tag_pv_map.keys(), runtime.image_metas)
    elif nvrs:
        runtime.logger.info(f"Finding {len(builds)} builds from Brew...")
        builds = brew.get_build_objects(nvrs, brew_session)
    runtime.logger.info(f"Found {len(builds)} image builds.")

    resultsdb_api = ResultsDBAPI()
    nvrs = [b["nvr"] for b in builds]
    runtime.logger.info(f"Getting CVP test results for {len(builds)} image builds...")
    latest_cvp_results = await get_latest_cvp_results(runtime, resultsdb_api, nvrs)

    # print a summary for all CVP results
    good_results = []  # good means PASSED or INFO
    bad_results = []  # bad means NEEDS_INSPECTION or FAILED
    incomplete_nvrs = []
    for nvr, result in zip(nvrs, latest_cvp_results):
        if not result:
            incomplete_nvrs.append(nvr)
            continue
        outcome = result.get("outcome")  # only PASSED, FAILED, INFO, NEEDS_INSPECTION are now valid outcome values (https://resultsdb20.docs.apiary.io/#introduction/changes-since-1.0)
        if outcome in {"PASSED", "INFO"}:
            good_results.append(result)
        elif outcome in {"NEEDS_INSPECTION", "FAILED"}:
            bad_results.append(result)
    green_prefix("good: {}".format(len(good_results)))
    click.echo(", ", nl=False)
    red_prefix("bad: {}".format(len(bad_results)))
    click.echo(", ", nl=False)
    yellow_print("incomplete: {}".format(len(incomplete_nvrs)))

    if bad_results:
        red_print("The following builds didn't pass CVP tests:")
        for r in bad_results:
            nvr = r["data"]["item"][0]
            red_print(f"{nvr} {r['outcome']}: {r['ref_url']}")

    if incomplete_nvrs:
        yellow_print("We couldn't find CVP test results for the following builds:")
        for nvr in incomplete_nvrs:
            yellow_print(nvr)

    if not optional_checks and not all_optional_checks:
        return  # no need to print failed optional CVP checks
    # Find failed optional CVP checks in case some of the tiem *will* become required.
    optional_checks = set(optional_checks)
    complete_results = good_results + bad_results
    runtime.logger.info(f"Getting optional checks for {len(complete_results)} CVP tests...")
    optional_check_results = await get_optional_checks(runtime, complete_results)

    component_distgit_keys = {}  # a dict of brew component names to distgit keys
    content_set_to_repo_names = {}  # a map of content set names to group.yml repo names
    for image in runtime.image_metas():
        component_distgit_keys[image.get_component_name()] = image.distgit_key
    for repo_name, repo_info in runtime.group_config.get("repos", {}).items():
        for arch, cs_name in repo_info.get('content_set', {}).items():
            if arch == "optional":
                continue  # not a real arch name
            content_set_to_repo_names[cs_name] = repo_name

    nvr_to_builds = {build["nvr"]: build for build in builds}

    ocp_build_data_updated = False

    failed_with_not_covered_rpms = set()
    failed_with_redundant_repos = set()
    only_failed_in_non_x86_with_not_covered_rpms = set()
    only_failed_in_non_x86_with_redundant_repos = set()

    for cvp_result, checks in zip(complete_results, optional_check_results):
        # example optional checks: http://external-ci-coldstorage.datahub.redhat.com/cvp/cvp-product-test/hive-container-v4.6.0-202008010302.p0/da01e36c-8c69-4a19-be7d-ba4593a7b085/sanity-tests-optional-results.json
        bad_checks = [check for check in checks["checks"] if check["status"] != "PASS" and (all_optional_checks or check["name"] in optional_checks)]
        if not bad_checks:
            continue
        nvr = cvp_result["data"]["item"][0]
        build = nvr_to_builds[nvr]
        yellow_print("----------")
        yellow_print(f"Build {nvr} (https://brewweb.engineering.redhat.com/brew/buildinfo?buildID={nvr_to_builds[nvr]['id']}) has {len(bad_checks)} problematic CVP optional checks:")
        for check in bad_checks:
            yellow_print(f"* {check['name']} {check['status']}")
            amd64_result = list(filter(lambda item: item.get("arch") == "amd64", check["logs"][-1]))
            if len(amd64_result) != 1:
                red_print("WHAT?! This build doesn't include an amd64 image? This shouldn't happen. Check Brew and CVP logs with the CVP team!")
                continue
            amd64_result = amd64_result[0]
            image_component_name = nvr.rsplit('-', 2)[0]
            distgit_key = component_distgit_keys.get(image_component_name)

            amd64_redundant_cs = amd64_result.get("redundant_cs", [])
            amd64_redundant_repos = {content_set_to_repo_names[cs] for cs in amd64_redundant_cs}

            def _strip_arch_suffix(rpm):
                # rh-nodejs10-3.2-3.el7.x86_64 -> rh-nodejs10-3.2-3.el7
                rpm_split = rpm.rsplit(".", 1)
                return rpm_split[0]

            amd64_not_covered_rpms = {_strip_arch_suffix(rpm) for rpm in amd64_result.get("not_covered_rpms", [])}

            if check["name"] == "content_set_check":
                details = check["logs"][-1]  # example: http://external-ci-coldstorage.datahub.redhat.com/cvp/cvp-product-test/logging-fluentd-container-v4.6.0-202008261251.p0/dd9f2024-5440-4f33-b508-472ccf258439/sanity-tests-optional-results.json
                if not details:
                    red_print("content_set_check failed without any explanation. Report to CVP team!")
                    continue
                if len(details) > 1:  # if this build is multi-arch, check if all per-arch results are consistent
                    for result in details:
                        if result["arch"] == "amd64":
                            continue
                        redundant_repos = {content_set_to_repo_names[cs] for cs in result.get("redundant_cs", [])}
                        if redundant_repos != amd64_redundant_repos:
                            only_failed_in_non_x86_with_redundant_repos.add(nvr)
                            red_print(f"""content_set_check for {nvr} arch {result["arch"]} has different redundant_cs result from the one for amd64:
                            {result["arch"]} has redundant_cs {result.get("redundant_cs")},
                            but amd64 has redundant_cs {amd64_redundant_cs}.
                            Not sure what happened. Please see Brew and CVP logs and/or check with the CVP team.""")
                        not_covered_rpms = {_strip_arch_suffix(rpm) for rpm in result.get("not_covered_rpms", [])}
                        if not_covered_rpms != amd64_not_covered_rpms:
                            only_failed_in_non_x86_with_not_covered_rpms.add(nvr)
                            red_print(f"""content_set_check for {nvr} arch {result["arch"]} has different not_covered_rpms result from the one for amd64:
                            {result["arch"]} has extra not_covered_rpms {not_covered_rpms - amd64_not_covered_rpms},
                            and missing not_covered_rpms {amd64_not_covered_rpms - not_covered_rpms}.
                            Not sure what happened. Check Brew and CVP logs with the CVP team!""")

                if amd64_not_covered_rpms:  # This build has not_covered_rpms
                    failed_with_not_covered_rpms.add(nvr)
                    yellow_print(f"Image {distgit_key} has not_covered_rpms: {amd64_not_covered_rpms}")
                    brew_repos = await find_repos_for_rpms(amd64_not_covered_rpms, build)
                    yellow_print(f"Those repos shown in Brew logs might be a good hint: {brew_repos}")
                    runtime.logger.info("Looking for parent image's content_sets...")
                    parent = get_parant_build_ids([build])[0]
                    if parent:
                        parent_build = brew.get_build_objects([parent])[0]
                        parent_cs = await get_content_sets_for_build(parent_build)
                        parent_enabled_repos = {content_set_to_repo_names[cs] for cs in parent_cs.get("x86_64", [])}
                        enabled_repos = set(runtime.image_map[distgit_key].config.get("enabled_repos", []))
                        missing_repos = parent_enabled_repos - enabled_repos
                        yellow_print(f"""The following repos are defined in parent {parent_build["nvr"]} {component_distgit_keys.get(parent_build["name"], "?")}.yml but not in
                                     {component_distgit_keys[build["name"]]}.yml: {missing_repos}""")
                        if fix and missing_repos:
                            runtime.logger.info("Trying to merge parent image's content_sets...")
                            fix_missing_content_set(runtime, distgit_key, missing_repos)
                            ocp_build_data_updated = True
                            runtime.logger.info(f"{distgit_key}.yml patched")

                if amd64_redundant_repos:  # This build has redundant_cs
                    failed_with_redundant_repos.add(nvr)
                    yellow_print(f"Image {distgit_key} has redundant repos: {amd64_redundant_repos}")
                    if not fix:
                        yellow_print(f"Please add the following repos to non_shipping_repos in {distgit_key}.yml: {amd64_redundant_repos}")
                    else:
                        runtime.logger.info(f"Applying redundant content sets fix to {distgit_key}.yml...")
                        fix_redundant_content_set(runtime, distgit_key, amd64_redundant_repos)
                        ocp_build_data_updated = True
                        runtime.logger.info(f"{distgit_key}.yml patched")

        print(f"See {cvp_result['ref_url']}sanity-tests-optional-results.json for more details.")

    if failed_with_not_covered_rpms or failed_with_redundant_repos:
        yellow_print(f"{len(failed_with_not_covered_rpms | failed_with_redundant_repos)} images failed content_sets.\n Where")

    if failed_with_not_covered_rpms:
        yellow_print(f"\t{len(failed_with_not_covered_rpms)} images failed content_sets check because of not_covered_rpms:")
        for rpm in failed_with_not_covered_rpms:
            line = f"\t\t{rpm}"
            if rpm in only_failed_in_non_x86_with_not_covered_rpms:
                line += " - non-x86 arches are different from x86 one"
            yellow_print(line)
    if failed_with_redundant_repos:
        yellow_print(f"\t{len(failed_with_redundant_repos)} images failed content_sets check because of redundant_repos:")
        for rpm in failed_with_redundant_repos:
            line = f"\t\t{rpm}"
            if rpm in only_failed_in_non_x86_with_redundant_repos:
                line += " - non-x86 arches are different from x86 one"
            yellow_print(line)

    if message and ocp_build_data_updated:
        runtime.gitdata.commit(message)


def get_parant_build_ids(builds):
    parents = []
    for b in builds:
        if b.get("extra") is None:
            b = brew.get_build_objects([b["id"]])[0]
        parent = b["extra"]["image"].get("parent_build_id")
        parents.append(parent)
    return parents


async def get_content_sets_for_build(build):
    # git://pkgs.devel.redhat.com/containers/openshift-jenkins-2#462b9c17a1e58715b96019843aa2b1331b1fd775 -> git://pkgs.devel.redhat.com/containers/openshift-jenkins-2, 462b9c17a1e58715b96019843aa2b1331b1fd775
    repo, commit = urldefrag(build["source"])
    # -> https://pkgs.devel.redhat.com/cgit/containers/openshift-jenkins-2/tree/content_sets.yml?id=aca48b7c59429978a73e276383a6077c8f1ae55c
    url = repo.replace("git://pkgs.devel.redhat.com/", "https://pkgs.devel.redhat.com/cgit/") + "/plain/content_sets.yml?id=" + commit
    async with aiohttp.ClientSession() as session:
        async with await session.get(url) as response:
            text = await response.text()
            content_sets = yaml.load(text)
    return content_sets


async def find_repos_for_rpms(rpms, build, arch="x86_64"):
    """ Find content sets for rpms by looking at Brew logs
    """
    log_url = f"http://download.eng.bos.redhat.com/brewroot/packages/{build['name']}/{build['version']}/{build['release']}/data/logs/{arch}.log"
    async with aiohttp.ClientSession() as session:
        async with await session.get(log_url) as response:
            log = await response.text()
    # looking for lines in logs like
    # `2020-07-18 10:52:00,888 - atomic_reactor.plugins.imagebuilder - INFO -  java-11-openjdk      i686   1:11.0.8.10-0.el7_8 rhel-server-rpms-x86_64  215 k`
    pattern = re.compile(r"atomic_reactor.plugins.imagebuilder - INFO -\s+([\w-]+)\s+\w+\s+([\w.-]+)\s+([\w-]+)\s+[\d.]+")
    rpm_to_content_set = {}

    for line in log.split("\n"):
        match = pattern.search(line)
        if not match:
            continue
        name = match[1]
        version_release = match[2]
        content_set = match[3]
        if f"{name}-{version_release}" in rpms:
            rpm_to_content_set[f"{name}-{version_release}"] = content_set

    return rpm_to_content_set


def fix_missing_content_set(runtime: Runtime, distgit_key: str, repos: List[str]):
    """ Patch ocp-build-data image config yaml to fix the missing content sets error.

    Note this function just adds the redundant repos to `non_shipping_repos`. It doesn't really remove repos from enabled_repos because the builder image may require them.
    """
    repos = set(repos)
    data_obj = runtime.gitdata.load_data(path='images', key=distgit_key)
    data_obj.reload()  # reload with ruamel.yaml to preserve the format and comments as much as possible
    image_cfg = data_obj.data
    # add repos to enabled_repos
    enabled_repos = set(image_cfg.get("enabled_repos", []))
    enabled_repos = enabled_repos | repos
    if enabled_repos:
        image_cfg["enabled_repos"] = sorted(list(enabled_repos))
    elif "enabled_repos" in image_cfg:
        del image_cfg["enabled_repos"]
    # remove repos from non_shipping_repos
    non_shipping_repos = set(image_cfg.get("non_shipping_repos", []))
    non_shipping_repos = non_shipping_repos - repos
    if non_shipping_repos:
        image_cfg["non_shipping_repos"] = sorted(list(non_shipping_repos))
    elif "non_shipping_repos" in image_cfg:
        del image_cfg["non_shipping_repos"]
    data_obj.save()


def fix_redundant_content_set(runtime: Runtime, distgit_key: str, redundant_repos: List[str]):
    """ Patch ocp-build-data image config yaml to fix the redundant content sets error.

    Note this function just adds the redundant repos to `non_shipping_repos`. It doesn't really remove repos from enabled_repos because the builder image may require them.
    """
    data_obj = runtime.gitdata.load_data(path='images', key=distgit_key)
    data_obj.reload()  # reload with ruamel.yaml to preserve the format and comments as much as possible
    image_cfg = data_obj.data
    # add redundant_repos to non_shipping_repos
    non_shipping_repos = image_cfg.get("non_shipping_repos", [])
    non_shipping_repos = set(non_shipping_repos) | set(redundant_repos)
    if non_shipping_repos:
        image_cfg["non_shipping_repos"] = sorted(list(non_shipping_repos))
    elif "non_shipping_repos" in image_cfg:
        del image_cfg["non_shipping_repos"]
    enabled_repos = set(image_cfg.get("enabled_repos", []))
    # ensure all non_shipping_repos are in enabled_repos
    enabled_repos = enabled_repos | non_shipping_repos
    if enabled_repos:
        image_cfg["enabled_repos"] = sorted(list(enabled_repos))
    elif "enabled_repos" in image_cfg:
        del image_cfg["enabled_repos"]
    data_obj.save()


def get_latest_image_builds(brew_session: koji.ClientSession, tags: Iterator[str], image_metas: Iterator[ImageMetadata]):
    tag_component_tuples = [(tag, image.get_component_name()) for tag in tags for image in image_metas()]
    builds = brew.get_latest_builds(tag_component_tuples, brew_session)
    return [b[0] for b in builds if b]


async def get_latest_cvp_results(runtime: Runtime, resultsdb_api: ResultsDBAPI, nvrs: List[str]):
    all_results = []
    async with aiohttp.ClientSession() as session:
        futures = []
        for nvr in nvrs:
            futures.append(resultsdb_api.async_get_latest_results(["rhproduct.default.sanity"], [nvr], session))
        results = await asyncio.gather(*futures)

    # results = parallel_results_with_progress(nvrs, lambda nvr: resultsdb_api.get_latest_results(["rhproduct.default.sanity"], [nvr]), file=sys.stderr)
    for nvr, result in zip(nvrs, results):
        data = result.get("data")
        if not data:  # Couldn't find a CVP test result for the given Brew build
            runtime.logger.warning(f"Couldn't find a CVP test result for {nvr}. Is the CVP test still running?")
            all_results.append(None)
            continue
        all_results.append(data[0])
    return all_results


async def get_optional_checks(runtime: Runtime, test_results):
    async def _fetch(url, cvp_result):
        r = await session.get(url)
        if r.status != 200:
            nvr = cvp_result["data"]["item"][0]
            runtime.logger.warning(f"Couldn't find sanity-tests-optional-results.json for {nvr}")
            return None
        text = await r.text()  # can't use r.json() because the url doesn't return correct content-type
        return json.loads(text)

    async with aiohttp.ClientSession() as session:
        futures = []
        for cvp_result in test_results:
            # Each CVP test result stored in ResultsDB has a link to an external storage with more CVP test details
            # e.g. http://external-ci-coldstorage.datahub.redhat.com/cvp/cvp-product-test/ose-insights-operator-container-v4.5.0-202007240519.p0/fb9dd365-e886-46c9-9661-fd13c0d29c49/
            url = cvp_result["ref_url"] + "sanity-tests-optional-results.json"
            futures.append(_fetch(url, cvp_result))
        optional_check_results = await asyncio.gather(*futures)
    return optional_check_results
