from typing import Tuple
import click
from io import BytesIO
import koji
import re
import requests
import yaml
import json
from zipfile import ZipFile

from errata_tool import Erratum

from elliottlib import brew, constants, exectools, errata
from elliottlib.cli.common import cli, pass_runtime
from elliottlib.exceptions import ElliottFatalError, BrewBuildException
from elliottlib.runtime import Runtime
from elliottlib.util import (exit_unauthenticated, red_print, green_print)


@cli.command("verify-attached-operators", short_help="Verify attached operator bundle references are (being) shipped")
@click.option("--omit-shipped",
              required=False,
              is_flag=True,
              help='Do not query shipped images to satisfy bundle references')
@click.option("--omit-attached",
              required=False,
              is_flag=True,
              help='Do not query images shipping in other advisories to satisfy bundle references')
@click.argument("advisories", nargs=-1, type=click.IntRange(1), required=True)
@pass_runtime
def verify_attached_operators_cli(runtime: Runtime, omit_shipped: bool, omit_attached: bool, advisories: Tuple[int, ...]):
    """
    Verify attached operator bundle references are shipping or already shipped.

    NOTE: this will fail for obsolete releases prior to 4.6;
    that is when the bundle format was introduced.

    Args are a list of advisory IDs that may contain operator bundle builds
    and any container builds shipping alongside.

    Verifies whether the operator bundle references are expected to be fulfilled when shipped.
    An error is raised if any references are missing, or are not shipping to the expected repos,
    or if bundle CSV contents fail validation.

    By default, references may be fulfilled by containers that have shipped already or are
    shipping in any advisory (not just those specified). The omission options may be used to limit
    what is considered fulfillment; for example, to prepare an early operator release, specify both
    to ensure that only containers attached to the single advisory shipping are considered:

        elliott -g openshift-4.13 verify-attached-operators \\
                --omit-attached --omit-shipped 111422

    Since builds which are attached somewhere (should) include those which have shipped already,
    --omit-shipped has no real effect if --omit-attached is not also specified.
    If only --omit-attached is specified, then builds shipped previously are still considered to
    fulfill bundle references, as are those attached to advisories specified in the args.
    """

    runtime.initialize(mode="images")
    brew_session = koji.ClientSession(runtime.group_config.urls.brewhub or constants.BREW_HUB)
    image_builds = _get_attached_image_builds(brew_session, advisories)

    bundles = _get_bundle_images(image_builds)
    if not bundles:
        adv_str = ", ".join(str(a) for a in advisories)
        green_print(f"No bundle builds found in advisories ({adv_str}).")
        return

    # check if references are satisfied by any image we are shipping or have shipped
    if not omit_shipped:
        image_builds.extend(_get_shipped_images(runtime, brew_session))
    available_shasums = _extract_available_image_shasums(image_builds)
    missing = _missing_references(runtime, bundles, available_shasums, omit_attached)

    invalid = _validate_csvs(bundles)

    if missing:
        missing_str = "\n              ".join(missing)
        red_print(f"""
            Some references were missing:
              {missing_str}
            Ensure all bundle references are shipped or shipping to correct repos.
        """)
    if invalid:
        invalid_str = "\n              ".join(invalid)
        red_print(f"""
            The following bundles failed CSV validation:
              {invalid_str}
            Check art.yaml substitutions for failing matches.
        """)
    if invalid or missing:
        raise ElliottFatalError("Please resolve the errors above before shipping bundles.")

    green_print("All operator bundles were valid and references were found.")


def _validate_csvs(bundles):
    invalid = set()
    for bundle in bundles:
        nvr, csv = bundle['nvr'], bundle['csv']
        # check the CSV for invalid metadata
        try:
            if not re.search(r'-\d{12}', csv['metadata']['name']):
                red_print(f"Bundle {nvr} CSV metadata.name has no datestamp: {csv['metadata']['name']}")
                invalid.add(nvr)
            if not re.search(r'-\d{12}', csv['spec']['version']):
                red_print(f"Bundle {nvr} CSV spec.version has no datestamp: {csv['spec']['version']}")
                invalid.add(nvr)
        except KeyError as ex:
            red_print(f"Bundle {nvr} CSV is missing key: {ex}")
            invalid.add(nvr)
    return invalid


def _get_attached_image_builds(brew_session, advisories):
    # get all attached image builds
    build_nvrs = []
    for advisory in advisories:
        green_print(f"Retrieving builds from advisory {advisory}")
        advisory = Erratum(errata_id=advisory)
        for build_list in advisory.errata_builds.values():  # one per product version
            build_nvrs.extend(build_list)

    green_print(f"Found {len(build_nvrs)} builds")
    return [build for build in brew.get_build_objects(build_nvrs, brew_session) if _is_image(build)]


def _is_image(build):
    return build.get('extra', {}).get('osbs_build', {}).get('kind') == "container_build"


def _is_bundle(image_build):
    return 'operator_bundle' in image_build.get('extra', {}).get('osbs_build', {}).get('subtypes', [])


def _get_bundle_images(image_builds):
    # extract referenced images from bundles to be shipped
    # returns a map[pullspec: bundle_nvr]
    bundles = []
    for image in image_builds:
        if _is_bundle(image):
            image['csv'] = _download_bundle_csv(image)
            bundles.append(image)
    return bundles


def _download_bundle_csv(bundle_build):
    # the CSV is buried in an archive
    url = constants.BREW_DOWNLOAD_TEMPLATE.format(
        name=bundle_build['package_name'],
        version=bundle_build['version'],
        release=bundle_build['release'],
        file_path="operator-manifests/operator_manifests.zip",
    )
    try:
        res = requests.get(url, timeout=10.0)
    except Exception as ex:
        raise ElliottFatalError(f"bundle data download {url} failed: {ex}")
    if res.status_code != 200:
        raise ElliottFatalError(f"bundle data download {url} failed (status_code={res.status_code}): {res.text}")

    csv = {}
    with ZipFile(BytesIO(res.content)) as z:
        for filename in z.namelist():
            if re.match(r"^.*clusterserviceversion.yaml", filename):
                with z.open(filename) as csv_file:
                    if csv:
                        raise ElliottFatalError(f"found more than one CSV in {bundle_build['nvr']}?!? {filename}")
                    csv = yaml.safe_load(csv_file)

    if not csv:
        raise ElliottFatalError(f"could not find the csv for bundle {bundle_build['nvr']}")
    return csv


def _get_shipped_images(runtime: Runtime, brew_session):
    # retrieve all image builds ever shipped for this version (potential operands)
    # NOTE: this will tend to be the slow part, aside from querying ET
    tags = {f"{image.branch()}-container-released" for image in runtime.image_metas()}
    released = brew.get_tagged_builds([(tag, None) for tag in tags], build_type='image', event=None, session=brew_session)
    released = brew.get_build_objects([b['build_id'] for b in released], session=brew_session)
    return [b for b in released if _is_image(b)]  # filter out source images


def _extract_available_image_shasums(image_builds):
    # get shasums for all attached or released images
    image_digests = set()
    for img in image_builds:
        for pullspec in img['extra']['image']['index']['pull']:
            if "@sha256:" in pullspec:
                image_digests.add(pullspec.split('@')[1])
    return image_digests


def _missing_references(runtime, bundles, available_shasums, omit_attached):
    # check that bundle references are all either shipped or shipping,
    # and that they will/did ship to the right repo on the registry
    references = [
        [ref['image'], build]  # ref => the bundle build that references it
        for build in bundles
        for ref in build['csv']['spec']['relatedImages']
    ]
    green_print(f"Found {len(bundles)} bundles with {len(references)} references")
    missing = set()
    missing_builds_by_advisory = {}
    for image_pullspec, build in references:
        # validate an image reference from a bundle is shipp(ed/ing) to the right repo
        repo, digest = image_pullspec.rsplit("@", 1)  # split off the @sha256:...
        _, repo = repo.split("/", 1)  # pick off the registry
        ref = image_pullspec.rsplit('/', 1)[1]  # just need the name@digest

        try:
            ref = _nvr_for_operand_pullspec(runtime, ref)  # convert ref to nvr
            context = f"Bundle {build['nvr']} reference {ref}:\n   "
            attached_advisories = _get_attached_advisory_ids(ref)
            cdn_repos = _get_cdn_repos(attached_advisories, ref)
            if digest not in available_shasums and not attached_advisories:
                red_print(f"{context} not shipped or attached to any advisory.")
            elif not cdn_repos:
                red_print(f"{context} does not have any CDN repos on advisory it is attached to")
            elif repo not in cdn_repos:
                red_print(f"{context} needs CDN repo '{repo}' but advisory only has {cdn_repos}")
            elif digest in available_shasums:
                green_print(f"{context} shipped/shipping as {image_pullspec}")
                continue  # do not count it as missing
            elif omit_attached:
                # not already shipped (or cmdline omitted shipped), nor in a listed advisory;
                # if we passed above gates, it is attached to some other advisory;
                # but cmdline option says to count that as missing.
                red_print(f"{context} only found in omitted advisory {attached_advisories}")
                for a in attached_advisories:
                    if a in missing_builds_by_advisory:
                        missing_builds_by_advisory[a].append(ref)
                    else:
                        missing_builds_by_advisory[a] = [ref]
            else:
                green_print(f"{context} attached to separate advisory {attached_advisories}")
                continue  # do not count it as missing
        except BrewBuildException as ex:
            # advisory lookup for brew build failed, fall through to count as missing
            red_print(f"{context} failed to look up in errata-tool: {ex}")
        missing.add(ref)  # ref is nvr if lookup worked, part of pullspec if not
    if missing_builds_by_advisory:
        print('To fix missing builds in other advisories:')
        for a in missing_builds_by_advisory:
            # -b build1 -b build2 -b build3
            builds_args = " ".join([f"-b {b}" for b in missing_builds_by_advisory[a]])
            print(f'Remove builds: find-builds -k image -a {a} {builds_args} --remove')
            print('Add builds: Same command but without --remove and -a `<target_advisory>`')
    return missing


def _nvr_for_operand_pullspec(runtime, spec):
    # spec should just be the part after the final "/" e.g. "ose-kube-rbac-proxy@sha256:9211b70..."
    # we can look it up in the internal proxy.
    urls = runtime.group_config.urls
    spec = f"{urls.brew_image_host}/{urls.brew_image_namespace}/openshift-{spec}"
    info = exectools.cmd_assert(
        f"oc image info -o json --filter-by-os=linux/amd64 {spec}",
        retries=3, pollrate=5, text_mode=True,
    )[0]
    labels = json.loads(info)["config"]["config"]["Labels"]
    return f"{labels['com.redhat.component']}-{labels['version']}-{labels['release']}"


def _get_attached_advisory_ids(nvr):
    return set(
        ad["id"]
        for ad in brew.get_brew_build(nvr=nvr).all_errata
        if ad["status"] != "DROPPED_NO_SHIP"
    )


def _get_cdn_repos(attached_advisories, for_nvr):
    return set(
        cdn_repo
        for ad_id in attached_advisories
        for nvr, cdn_entry in errata.get_cached_image_cdns(ad_id).items()
        for cdn_repo in cdn_entry["docker"]["target"]["external_repos"]
        if nvr == for_nvr
    )
