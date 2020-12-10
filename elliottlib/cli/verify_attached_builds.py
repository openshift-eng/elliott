import asyncio
from typing import Iterable, Tuple

import click
import koji
import yaml

from elliottlib import Runtime, brew, constants, errata, errata_async
from elliottlib.cli.common import cli, click_coroutine, pass_runtime


@cli.command("verify-attached-builds", short_help="Verify images in a release have no non-shipping RPMs")
@click.argument("advisories", nargs=-1, type=click.IntRange(1), required=False)
@pass_runtime
@click_coroutine
async def verify_attached_builds_cli(runtime: Runtime, advisories: Tuple[int]):
    """
    Verify the images in the advisories (specified as arguments or in group.yml) and payload pullspecs
    for a release have no non-shipping RPMs.

    Non-shipping RPMs, or "Orphan" RPMs called by QE's tests, are RPMs used in images we are trying to ship, but are not themselves shipped.
    """
    runtime.initialize()
    # advisories = advisories or [a for a in runtime.group_config.get('advisories', {}).values()]
    # if not advisories:
    #     #red_print("No advisories specified on command line or in group.yml")
    #     exit(1)
    await BuildValidator(runtime, runtime.logger).validate_async(advisories)
    pass


class BuildValidator:
    def __init__(self, runtime, logger) -> None:
        self._runtime = runtime
        self.logger = logger

    async def validate_async(self, advisories: Iterable[int]):
        all_builds = {}
        image_advisory_builds = {}
        rpm_advisory_builds = {}
        build_advisories = {}
        async with errata_async.ErrataAsyncClient.from_runtime(self._runtime) as errata_client:
            errata_client.gssapi_login()

            pvs = {"RHEL-7.9", "RHEL-8.0.0", "RHEL-8.1.0", "RHEL-8.2.0.GA", "RHEL-8.3.0.GA", "RHOS-16.0-RHEL-8"}
            ga_build_objects = await asyncio.gather(*[errata_client.get_released_builds(pv) for pv in pvs])

            ga_builds = {b['build'] for lst in ga_build_objects for b in lst}

            pvs = {"RHEL-8.0.0", "RHEL-8.1.0", "RHEL-8.2.0.GA", "RHEL-8.3.0.GA", "RHOS-16.0-RHEL-8"}
            ga_module_objects = await asyncio.gather(*[errata_client.get_released_modules(pv) for pv in pvs])
            ga_modules = {b['build'] for lst in ga_module_objects for b in lst}

            ga_builds |= ga_modules

            self.logger.info("Fetching builds associated with %d advisories...", len(advisories))
            build_lists = await asyncio.gather(*[errata_client.get_advisory_builds(advisory) for advisory in advisories])
            for advisory, builds in zip(advisories, build_lists):
                for build in builds:
                    all_builds[build["id"]] = build
                    component_name = build["nvr"].rsplit('-', 2)[0]
                    if component_name.endswith("-container"):  # assume image name always ends with `-container`
                        image_advisory_builds.setdefault(advisory, set()).add(build["id"])
                    else:
                        rpm_advisory_builds.setdefault(advisory, set()).add(build["id"])
                    build_advisories.setdefault(build["id"], set()).add(advisory)

        self.logger.info("Got %d unique builds on %d advisories", len(all_builds), len(advisories))
        brew_session = koji.ClientSession((self._runtime.group_config.urls.brewhub if self._runtime.initialized else None) or constants.BREW_HUB)
        image_builds = list({b for builds in image_advisory_builds.values() for b in builds})
        self.logger.info("Fetching rpms in %d image builds... This may take a few minutes", len(image_builds))
        archives_list = brew.list_archives_by_builds(image_builds, "image", brew_session)
        used_rpms = {}
        rpm_image_builds = {}
        for archives in archives_list:
            for image in archives:
                for rpm in image["rpms"]:
                    used_rpms[rpm["build_id"]] = rpm["nvr"]
                    rpm_image_builds.setdefault(rpm["build_id"], set()).add(image["build_id"])
        self.logger.info("Determining if each of %d RPM used in an image has shipped or attached to an advisory... This may take a few minutes", len(used_rpms))
        used_rpm_build_ids = list(used_rpms.keys())
        build_objects = brew.get_build_objects(used_rpm_build_ids, brew_session)
        for build_id, build in zip(used_rpm_build_ids, build_objects):
            used_rpms[build_id] = build["nvr"]
        # filter out GA rpm builds
        used_rpm_build_ids = [b for b in used_rpm_build_ids if used_rpms[b] not in ga_builds]

        rpms_tags = brew.get_builds_tags(used_rpm_build_ids, brew_session)
        pending_rpms = set()
        unshipped_rpms = set()
        for rpm_build_id, tags in zip(used_rpm_build_ids, rpms_tags):
            if any(tag["name"].endswith("-released") for tag in tags):
                self.logger.info("rpm %s has shipped", used_rpms[rpm_build_id])
            elif any(tag["name"].endswith("-pending") for tag in tags):
                pending_rpms.add(rpm_build_id)
                # self.logger.info("rpm %s has shipped", used_rpms[rpm_build_id])
            else:
                unshipped_rpms.add(rpm_build_id)
                # self.logger.info("rpm %s is not shipped", used_rpms[rpm_build_id])
        self.logger.info("%d rpms are not shipped; %d rpms are attached to an open advisory; %d rpms has shipped", len(unshipped_rpms), len(pending_rpms), len(used_rpm_build_ids) - len(unshipped_rpms) - len(pending_rpms))
        if pending_rpms:
            self.logger.info("Finding advisories that %d rpms are attached to...", len(pending_rpms))
            for rpm in pending_rpms:
                build_info = errata.get_brew_build(rpm)
                build_info.all_errata  # [{'id': 66563, 'name': 'RHSA-2020:5260', 'status': 'QE'}]
                self.logger.info("rpm %s is attached to %s", used_rpms[rpm], build_info.all_errata)
        non_shippings = {}
        if unshipped_rpms:
            self.logger.info("Unshipped RPMs:")
            for rpm in unshipped_rpms:
                rpm_nvr = used_rpms[rpm]
                image_builds = rpm_image_builds[rpm]
                for image_build in image_builds:
                    image_nvr = all_builds[image_build]["nvr"]
                    advisories = build_advisories[image_build]
                    for ad in advisories:
                        non_shippings.setdefault(ad, {}).setdefault(image_nvr, set()).add(rpm_nvr)

        report = {ad: {image: sorted(rpms) for image, rpms in images.items()} for ad, images in non_shippings.items()}
        with open("non-shipping-rpms.yml", "w") as f:
            yaml.dump(report, f, sort_keys=True)

        pass
