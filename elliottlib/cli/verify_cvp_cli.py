import asyncio
import json
import logging
import sys
from ast import Dict
from collections import OrderedDict
from typing import Iterable, List
from urllib.parse import urljoin

import click
from ruamel.yaml import YAML

from elliottlib import Runtime, brew, exectools
from elliottlib.cli.common import cli, click_coroutine, pass_runtime
from elliottlib.cvp import CVPInspector
from elliottlib.imagecfg import ImageMetadata
from elliottlib.util import (green_prefix, green_print, parse_nvr, pbar_header,
                             progress_func, red_prefix, red_print,
                             yellow_print)

yaml = YAML(typ="safe")
yaml.default_flow_style = False

LOGGER = logging.getLogger(__name__)


@cli.command("verify-cvp", short_help="Verify CVP test results")
@click.option(
    '--all', 'all_images', required=False, is_flag=True,
    help='Verify all latest image builds (default to False)')
@click.option(
    '--build', '-b', 'nvrs',
    multiple=True, metavar='NVR_OR_ID',
    help='Only verify specified builds')
@click.option(
    '--include-content-set-check', "include_content_set_check", is_flag=True,
    help="Include content_set_check")
@click.option(
    '--output', '-o', 'output', metavar='FORMAT', default="text", type=click.Choice(['text', 'json', 'yaml']),
    help='Output format. One of: text|json|yaml')
@pass_runtime
@click_coroutine
async def verify_cvp_cli(runtime: Runtime, all_images, nvrs, include_content_set_check, output: str):
    """ Verify CVP test results

    Example 1: Verify CVP test results for all latest 4.12 image builds, including optional content_set_check

    $ elliott --group openshift-4.12 verify-cvp --all --include-content-set-check

    Example 2: Verify CVP test results for 4.11.0, including optional content_set_check

    $ elliott --group openshift-4.11 --assembly 4.11.0 verify-cvp --all --include-content-set-check

    Example 3: Print CVP test results in yaml format

    $ elliott --group openshift-4.12 verify-cvp --all --include-content-set-check -o yaml
    """
    if bool(all_images) + bool(nvrs) != 1:
        raise click.BadParameter('You must use one of --all or --build.')

    runtime.initialize(mode='images')

    # Load brew builds
    brew_session = runtime.build_retrying_koji_client()
    builds = []
    if all_images:
        image_metas = runtime.image_metas()
        builds = await get_latest_image_builds(image_metas)
    elif nvrs:
        runtime.logger.info(f"Finding {len(builds)} builds from Brew...")
        builds = brew.get_build_objects(nvrs, brew_session)
    for b in builds:
        try:
            del b["_tags"]  # b["_tags"] is of type set, which cannot be dumped into json or yaml
        except KeyError:
            pass
    nvr_builds = {build["nvr"]: build for build in builds}  # a dict mapping NVRs to build dicts
    runtime.logger.info(f"Found {len(builds)} image builds.")

    inspector = None
    try:
        inspector = CVPInspector(group_config=runtime.group_config, image_metas=runtime.image_metas(), logger=runtime.logger)

        # Get latest CVP sanity_test results for specified NVRs
        runtime.logger.info(f"Getting CVP test results for {len(nvr_builds)} image builds...")
        nvr_results = await inspector.latest_sanity_test_results(nvr_builds.keys())
        nvr_results = OrderedDict(sorted(nvr_results.items(), key=lambda t: t[0]))

        # process and populate dict `report` for output
        runtime.logger.info("Processing CVP test results...")
        passed, failed, missing = inspector.categorize_test_results(nvr_results)

        def _reconstruct_test_results(test_results: Dict):
            results = {}
            for nvr, test_result in test_results.items():
                r = results[nvr] = {}
                r["dg_key"] = inspector.component_distgit_keys[parse_nvr(nvr)["name"]]
                r["build_url"] = f"https://brewweb.devel.redhat.com/buildinfo?buildID={nvr_builds[nvr]['id']}"
                if test_result:
                    r["ref_url"] = test_result['ref_url']
                    r["outcome"] = test_result['outcome']
            return results

        report = {
            "sanity_tests": {
                "passed": _reconstruct_test_results(passed),
                "failed": _reconstruct_test_results(failed),
                "missing": _reconstruct_test_results(missing),
            }
        }

        if include_content_set_check:
            optional_report = report["sanity_test_optional_checks"] = {}

            # Find failed optional CVP checks in case some of the tiem *will* become required.
            completed = sorted(passed.keys() | failed.keys())
            runtime.logger.info(f"Getting optional checks for {len(completed)} CVP tests...")

            optional_check_results = await inspector.get_sanity_test_optional_results([nvr_results[nvr] for nvr in completed])

            runtime.logger.info("Processing CVP optional test results...")
            included_checks = {"content_set_check"}
            passed_optional, failed_optional, missing_optional = inspector.categorize_sanity_test_optional_results(dict(zip(completed, optional_check_results)), included_checks=included_checks)

            async def _reconstruct_optional_test_results(test_results: Dict):
                results = {}
                tasks = OrderedDict()
                for nvr, result in test_results.items():
                    r = results[nvr] = {}
                    r["dg_key"] = inspector.component_distgit_keys[parse_nvr(nvr)["name"]]
                    r["build_url"] = f"https://brewweb.devel.redhat.com/buildinfo?buildID={nvr_builds[nvr]['id']}"
                    if result:
                        r["ref_url"] = urljoin(nvr_results[nvr]['ref_url'], "sanity-tests-optional-results.json")
                        failed = {check["name"] for check in result["checks"] if (not included_checks or check["name"] in included_checks) and not check["ok"]}
                        outcome = "PASSED" if not failed else "FAILED"
                        r["outcome"] = outcome
                        r["failed_checks"] = sorted(failed)
                        if failed:
                            runtime.logger.info("Examining content_set_check for %s", nvr)
                            failed_checks = [check for check in result["checks"] if check["name"] in failed]
                            tasks[nvr] = inspector.diagnostic_sanity_test_optional_checks(nvr_builds[nvr], failed_checks, included_checks=included_checks)
                if tasks:
                    for nvr, diagnostic_report in zip(tasks.keys(), await asyncio.gather(*tasks.values())):
                        results[nvr]["diagnostic_report"] = diagnostic_report
                return results

            optional_report["passed"], optional_report["failed"], optional_report["missing"] = await asyncio.gather(
                _reconstruct_optional_test_results(passed_optional),
                _reconstruct_optional_test_results(failed_optional),
                _reconstruct_optional_test_results(missing_optional),
            )
    finally:
        if inspector:
            await inspector.close()

    if output == "json":
        json.dump(report, sys.stdout)
    elif output == "yaml":
        yaml.dump(report, sys.stdout)
    else:
        print_report(report)
        failed_optional = report.get("sanity_test_optional_checks", {}).get("failed")
        if failed or failed_optional:
            exit(2)


def print_report(report: Dict):
    sanity_tests = report["sanity_tests"]
    passed, failed, missing = sanity_tests["passed"], sanity_tests["failed"], sanity_tests["missing"]
    print("sanity_tests")
    green_prefix("passed: {}".format(len(passed)))
    click.echo(", ", nl=False)
    red_prefix("failed: {}".format(len(failed)))
    click.echo(", ", nl=False)
    yellow_print("missing: {}".format(len(missing)))

    if failed:
        red_print("The following builds didn't pass CVP tests:")
        for nvr, r in failed.items():
            red_print(f"{nvr} {r['outcome']}: {r['ref_url']}")

    if missing:
        yellow_print("The following builds have no CVP tests results:")
        for nvr in missing:
            yellow_print(nvr)

    sanity_test_optional_checks = report.get("sanity_test_optional_checks")
    if not sanity_test_optional_checks:
        return

    passed_optional, failed_optional, missing_optional = sanity_test_optional_checks["passed"], sanity_test_optional_checks["failed"], sanity_test_optional_checks["missing"]
    print()
    print("sanity_test_optional_checks")
    green_prefix("passed: {}".format(len(passed_optional)))
    click.echo(", ", nl=False)
    red_prefix("failed: {}".format(len(failed_optional)))
    click.echo(", ", nl=False)
    yellow_print("missing: {}".format(len(missing_optional)))
    if failed_optional:
        red_print(f"{len(failed_optional)} builds didn't pass optional CVP tests:")
        for nvr, r in failed_optional.items():
            yellow_print("----------")
            yellow_print(f"{nvr} {r['outcome']}: {r['ref_url']}")
            for check_name, check_result in r["diagnostic_report"].items():
                if check_name not in r["failed_checks"]:
                    green_print(f"* {check_name}: PASSED")
                    continue
                red_print(f"* {check_name}: FAILED")
                for test_name, test_result in check_result.items():
                    if test_result['outcome'] == "PASSED":
                        green_print(f"\t* {test_name}: {test_result['outcome']}")
                        continue
                    red_print(f"\t- {test_name}: {test_result['outcome']}")
                    if "symptom" in test_result:
                        red_print("\t\t* symptom:")
                        for arch, arch_symptom in test_result["symptom"].items():
                            red_print(f"\t\t\t* {arch}: {arch_symptom}")
                    if "prescription" in test_result:
                        red_print(f"\t\t* prescription: {test_result['prescription']}")
                        for action in test_result["prescription"]:
                            red_print(f"\t\t\t* {action['action']}: {action['value']} {action.get('note')}")
                print()

    if missing_optional:
        yellow_print("The following builds have no CVP tests results:")
        for nvr in missing_optional:
            yellow_print(nvr)


@exectools.limit_concurrency(limit=32)
async def get_latest_image_build(image: ImageMetadata) -> List[Dict]:
    return await exectools.to_thread(progress_func, image.get_latest_build, file=sys.stderr)


async def get_latest_image_builds(image_metas: Iterable[ImageMetadata]):
    pbar_header(
        'Generating list of images: ',
        f'Hold on a moment, fetching Brew builds for {len(image_metas)} components...',
        seq=image_metas, file=sys.stderr)
    builds: List[Dict] = await asyncio.gather(*[get_latest_image_build(image) for image in image_metas])
    return builds
