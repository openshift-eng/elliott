from typing import List, Tuple
import click
import requests
import koji
import time
from elliottlib import Runtime
from elliottlib import errata, brew, constants, exceptions
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.util import green_print, red_print, yellow_print

pass_runtime = click.make_pass_decorator(Runtime)


#
# Tag Brew builds
# tag-builds
#
@cli.command("tag-builds", short_help="Tag specified Brew builds into specified tag")
@click.option(
    '--advisory', '-a', 'advisories',
    multiple=True, metavar='ADVISORY', type=int,
    help='Add builds on ADVISORY to tag [MULTIPLE]')
@use_default_advisory_option
@click.option(
    '--product-version', '--pv', 'product_version',
    metavar='PRODUCT_VERSION', type=str,
    help='Narrow builds with specified product version. e.g. RHEL-7-OSE-4.4, OSE-4.4-RHEL-8')
@click.option(
    '--build', '-b', 'builds',
    multiple=True, metavar='NVR_OR_ID',
    help='Add build NVR_OR_ID to tag [MULTIPLE]')
@click.option(
    '--tag', '-t',
    metavar='TAG', required=True,
    help='Tag name. e.g. rhaos-4.4-rhel-8-image-build')
@click.option(
    '--dont-untag', '-d', is_flag=True,
    help="Don't untag unspecified Brew builds")
@click.option(
    '--dry-run', is_flag=True,
    help="Don't really tag/untag any builds. Just print which builds should be tagged and untagged")
@pass_runtime
def tag_builds_cli(runtime: Runtime, advisories: Tuple[int], default_advisory_type: str, product_version: str,
                   builds: Tuple[str], tag: str, dont_untag: bool, dry_run: bool):
    """ Tag builds into Brew tag and optionally untag unspecified builds.

    Example 1: Tag RHEL7 RPMs that on ocp-build-data recorded advisory into rhaos-4.3-rhel-7-image-build

    $ elliott --group=openshift-4.3 tag-builds --use-default-advisory rpm --product-version RHEL-7-OSE-4.3 --tag rhaos-4.3-rhel-7-image-build

    Example 2: Tag RHEL8 RPMs that are on advisory 55016 into rhaos-4.3-rhel-8-image-build

    $ elliott --group=openshift-4.3 tag-builds --advisory 55016 --product-version OSE-4.4-RHEL-8 --tag rhaos-4.3-rhel-8-image-build

    Example 3: Tag specified builds into rhaos-4.3-rhel-8-image-build

    $ elliott --group=openshift-4.3 tag-builds --build buildah-1.11.6-6.rhaos4.3.el8 --build openshift-4.3.23-202005230952.git.1.b596217.el8 --tag rhaos-4.3-rhel-8-image-build
    """
    if advisories and builds:
        raise click.BadParameter('Use only one of --build or --advisory/-a.')
    if advisories and default_advisory_type:
        raise click.BadParameter('Use only one of --use-default-advisory or --advisory/-a.')
    if default_advisory_type and builds:
        raise click.BadParameter('Use only one of --build or --use-default-advisory.')
    if product_version and not advisories and not default_advisory_type:
        raise click.BadParameter('--product-version should only be used with --use-default-advisory or --advisory/-a.')

    runtime.initialize()
    logger = runtime.logger
    if default_advisory_type:
        advisories = (find_default_advisory(runtime, default_advisory_type), )

    all_builds = set()  # All Brew builds that should be in the tag

    if advisories:
        errata_session = requests.session()
        for advisory in advisories:
            logger.info(f"Fetching attached Brew builds from advisory {advisory}...")
            errata_builds = errata.get_builds(advisory, errata_session)
            product_versions = list(errata_builds.keys())
            logger.debug(f"Advisory {advisory} has builds for {len(product_versions)} product versions: {product_versions}")
            if product_version:  # Only this product version should be concerned
                product_versions = [product_version]
            for pv in product_versions:
                logger.debug(f"Extract Errata builds for product version {pv}")
                nvrs = _extract_nvrs_from_errata_build_list(errata_builds, pv)
                logger.info(f"Found {len(nvrs)} builds from advisory {advisory} with product version {pv}")
                logger.debug(f"The following builds are found for product version {pv}:\n\t{list(nvrs)}")
                all_builds |= set(nvrs)

    brew_session = koji.ClientSession(runtime.group_config.urls.brewhub or constants.BREW_HUB)
    if builds:  # NVRs are directly specified with --build
        build_objs = brew.get_build_objects(list(builds), brew_session)
        all_builds = {build["nvr"] for build in build_objs}

    click.echo(f"The following {len(all_builds)} build(s) should be in tag {tag}:")
    for nvr in all_builds:
        green_print(f"\t{nvr}")

    # get NVRs that have been tagged
    tagged_build_objs = brew_session.listTagged(tag, latest=False, inherit=False)
    tagged_builds = {build["nvr"] for build in tagged_build_objs}

    # get NVRs that should be tagged
    missing_builds = all_builds - tagged_builds
    click.echo(f"{len(missing_builds)} build(s) need to be tagged into {tag}:")
    for nvr in missing_builds:
        green_print(f"\t{nvr}")

    # get NVRs that should be untagged
    extra_builds = tagged_builds - all_builds
    click.echo(f"{len(extra_builds)} build(s) need to be untagged from {tag}:")
    for nvr in extra_builds:
        green_print(f"\t{nvr}")

    if dry_run:
        yellow_print("Dry run: Do nothing.")
        return

    brew_session.gssapi_login()

    if not dont_untag:
        # untag extra builds
        extra_builds = list(extra_builds)
        logger.info(f"Untagging {len(extra_builds)} build(s) from {tag}...")
        multicall_tasks = brew.untag_builds(tag, extra_builds, brew_session)
        failed_to_untag = []
        for index, task in enumerate(multicall_tasks):
            try:
                task.result
                click.echo(f"{nvr} has been successfully untagged from {tag}")
            except Exception as ex:
                nvr = extra_builds[index]
                failed_to_untag.append(nvr)
                logger.error(f"Failed to untag {nvr}: {ex}")

    # tag missing builds
    missing_builds = list(missing_builds)
    task_id_nvr_map = {}
    logger.info(f"Tagging {len(missing_builds)} build(s) into {tag}...")
    multicall_tasks = brew.tag_builds(tag, missing_builds, brew_session)
    failed_to_tag = []
    for index, task in enumerate(multicall_tasks):
        nvr = missing_builds[index]
        try:
            task_id = task.result
            task_id_nvr_map[task_id] = nvr
        except Exception as ex:
            failed_to_tag.append(nvr)
            logger.error(f"Failed to tag {nvr}: {ex}")

    if task_id_nvr_map:
        # wait for tag task to finish
        logger.info("Waiting for tag tasks to finish")
        brew.wait_tasks(task_id_nvr_map.keys(), brew_session, logger=logger)
        # get tagging results
        stopped_tasks = list(task_id_nvr_map.keys())
        with brew_session.multicall(strict=False) as m:
            multicall_tasks = []
            for task_id in stopped_tasks:
                multicall_tasks.append(m.getTaskResult(task_id, raise_fault=False))
        for index, t in enumerate(multicall_tasks):
            task_id = stopped_tasks[index]
            nvr = task_id_nvr_map[task_id]
            tag_res = t.result
            logger.debug(f"Tagging task {task_id} {nvr} returned result {tag_res}")
            click.echo(f"{nvr} has been successfully tagged into {tag}")
            if tag_res and 'faultCode' in tag_res:
                if "already tagged" not in tag_res["faultString"]:
                    failed_to_tag.append(nvr)
                    logger.error(f'Failed to tag {nvr} into {tag}: {tag_res["faultString"]}')

    if failed_to_untag:
        red_print("The following builds were failed to untag:")
        for nvr in failed_to_untag:
            red_print(f"\t{nvr}")
    elif not dont_untag:
        green_print(f"All unspecified builds have been successfully untagged from {tag}.")

    if failed_to_tag:
        red_print("The following builds were failed to tag:")
        for nvr in failed_to_tag:
            red_print(f"\t{nvr}")
    else:
        green_print(f"All builds have been successfully tagged into {tag}.")

    if failed_to_untag or failed_to_tag:
        raise exceptions.ElliottFatalError("Not all builds were successfully tagged/untagged.")


# Extract NVRs for specified product version from Errata returned build list.
# This function is useful because Errata API returns attached builds in a very weird JSON format.
def _extract_nvrs_from_errata_build_list(errata_builds, product_version):
    return [key for build in errata_builds.get(product_version, {}).get("builds", {}) for key in build]
