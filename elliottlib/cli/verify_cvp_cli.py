from typing import Iterator, List

import click
import koji
import requests
import pathlib
import sys

import elliottlib
from elliottlib import Runtime, brew, constants
from elliottlib.cli.common import (cli, find_default_advisory, pass_runtime,
                                   use_default_advisory_option)
from elliottlib.imagecfg import ImageMetadata
from elliottlib.resultsdb import ResultsDBAPI
from elliottlib.util import (green_prefix, parallel_results_with_progress,
                             red_prefix, yellow_print, red_print)


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
def verify_cvp_cli(runtime: Runtime, all_images, nvrs, optional_checks, all_optional_checks, fix, message):
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
    latest_cvp_results = get_latest_cvp_results(runtime, resultsdb_api, nvrs)

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
    optional_check_results = get_optional_checks(runtime, complete_results)

    component_distgit_keys = {}  # a dict of brew component names to distgit keys
    content_set_repo_names = {}  # a map of x86_64 content set names to group.yml repo names
    if fix:  # Fixing redundant content sets requires those dicts
        for image in runtime.image_metas():
            component_distgit_keys[image.get_component_name()] = image.distgit_key
        for repo_name, repo_info in runtime.group_config.get("repos", {}).items():
            content_set_name = repo_info.get('content_set', {}).get('x86_64') or repo_info.get('content_set', {}).get('default')
            if content_set_name:
                content_set_repo_names[content_set_name] = repo_name

    ocp_build_data_updated = False

    for cvp_result, checks in zip(complete_results, optional_check_results):
        # example optional checks: http://external-ci-coldstorage.datahub.redhat.com/cvp/cvp-product-test/hive-container-v4.6.0-202008010302.p0/da01e36c-8c69-4a19-be7d-ba4593a7b085/sanity-tests-optional-results.json
        bad_checks = [check for check in checks["checks"] if check["status"] != "PASS" and (all_optional_checks or check["name"] in optional_checks)]
        if not bad_checks:
            continue
        nvr = cvp_result["data"]["item"][0]
        yellow_print("----------")
        yellow_print(f"Build {nvr} has {len(bad_checks)} problematic CVP optional checks:")
        for check in bad_checks:
            yellow_print(f"* {check['name']} {check['status']}")
            if fix and check["name"] == "content_set_check":
                if "Some content sets are redundant." in check["logs"]:
                    # fix redundant content sets
                    name = nvr.rsplit('-', 2)[0]
                    distgit_keys = component_distgit_keys.get(name)
                    if not distgit_keys:
                        runtime.logger.warning(f"Will not apply the redundant content sets fix to image {name}: We don't know its distgit key.")
                        continue
                    amd64_content_sets = list(filter(lambda item: item.get("arch") == "amd64", check["logs"][-1]))  # seems only x86_64 (amd64) content sets are defined in ocp-build-data.
                    if not amd64_content_sets:
                        runtime.logger.warning(f"Will not apply the redundant content sets fix to image {name}: It doesn't have redundant x86_64 (amd64) content sets")
                        continue
                    amd64_redundant_cs = amd64_content_sets[0]["redundant_cs"]
                    redundant_repos = [content_set_repo_names[cs] for cs in amd64_redundant_cs if cs in content_set_repo_names]
                    if len(redundant_repos) != len(amd64_redundant_cs):
                        runtime.logger.error(f"Not all content sets have a repo entry in group.yml: #content_sets is {len(amd64_redundant_cs)}, #repos is {len(redundant_repos)}")
                    runtime.logger.info(f"Applying redundant content sets fix to {distgit_keys}...")
                    fix_redundant_content_set(runtime, distgit_keys, redundant_repos)
                    ocp_build_data_updated = True
                    runtime.logger.info(f"Fixed redundant content sets for {distgit_keys}")
        yellow_print(f"See {cvp_result['ref_url']}sanity-tests-optional-results.json for more details.")

    if message and ocp_build_data_updated:
        runtime.gitdata.commit(message)


def fix_redundant_content_set(runtime: Runtime, distgit_keys: str, redundant_repos: List[str]):
    """ Patch ocp-build-data image config yaml to fix the redundant content sets error.

    Note this function just adds the redundant repos to `non_shipping_repos`. It doesn't really remove repos from enabled_repos because the builder image may require them.
    """
    data_obj = runtime.gitdata.load_data(path='images', key=distgit_keys)
    data_obj.reload()  # reload with ruamel.yaml to preserve the format and comments as much as possible
    image_cfg = data_obj.data
    non_shipping_repos = image_cfg.get("non_shipping_repos", [])
    non_shipping_repos = set(non_shipping_repos) | set(redundant_repos)
    if non_shipping_repos:
        image_cfg["non_shipping_repos"] = sorted(list(non_shipping_repos))
    elif "non_shipping_repos" in image_cfg:
        del image_cfg["non_shipping_repos"]
    data_obj.save()


def get_latest_image_builds(brew_session: koji.ClientSession, tags: Iterator[str], image_metas: Iterator[ImageMetadata]):
    tag_component_tuples = [(tag, image.get_component_name()) for tag in tags for image in image_metas()]
    builds = brew.get_latest_builds(tag_component_tuples, brew_session)
    return [b[0] for b in builds if b]


def get_latest_cvp_results(runtime: Runtime, resultsdb_api: ResultsDBAPI, nvrs: List[str]):
    all_results = []
    results = parallel_results_with_progress(nvrs, lambda nvr: resultsdb_api.get_latest_results(["rhproduct.default.sanity"], [nvr]), file=sys.stderr)
    for nvr, result in zip(nvrs, results):
        data = result.get("data")
        if not data:  # Couldn't find a CVP test result for the given Brew build
            runtime.logger.warning(f"Couldn't find a CVP test result for {nvr}. Is the CVP test still running?")
            all_results.append(None)
            continue
        all_results.append(data[0])
    return all_results


def get_optional_checks(runtime: Runtime, test_results):
    # Each CVP test result stored in ResultsDB has a link to an external storage with more CVP test details
    # e.g. http://external-ci-coldstorage.datahub.redhat.com/cvp/cvp-product-test/ose-insights-operator-container-v4.5.0-202007240519.p0/fb9dd365-e886-46c9-9661-fd13c0d29c49/
    external_urls = [r["ref_url"] + "sanity-tests-optional-results.json" for r in test_results]
    optional_check_results = []
    with requests.session() as session:
        responses = parallel_results_with_progress(external_urls, lambda url: session.get(url), file=sys.stderr)
    for cvp_result, r in zip(test_results, responses):
        if r.status_code != 200:
            nvr = cvp_result["data"]["item"][0]
            runtime.logger.warning(f"Couldn't find sanity-tests-optional-results.json for {nvr}")
            optional_check_results.append(None)
            continue
        optional_check_results.append(r.json())
    return optional_check_results
