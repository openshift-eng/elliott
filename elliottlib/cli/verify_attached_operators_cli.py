import click
from io import BytesIO
import koji
from kerberos import GSSError
import re
import requests
import yaml
from zipfile import ZipFile

from errata_tool import Erratum

from elliottlib import brew, constants
from elliottlib.cli.common import cli, pass_runtime
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import (exit_unauthenticated, red_print, green_print)


@cli.command("verify-attached-operators", short_help="Verify attached operator manifest references are (being) shipped")
@click.argument("advisories", nargs=-1, type=click.IntRange(1), required=True)
@pass_runtime
def verify_attached_operators_cli(runtime, advisories):
    """
    Verify attached operator manifest references are shipping or already shipped.

    Takes a list of advisories that may contain operator metadata/bundle builds
    or image builds that are shipping alongside. Then determines whether the
    operator manifests refer only to images that have shipped in the past or
    are shipping in these advisories. An error is raised if there are no
    manifest builds attached, or if any references are missing.

    NOTE: this will fail before 4.3 because they referred to images not manifest lists.
    """

    runtime.initialize()
    brew_session = koji.ClientSession(runtime.group_config.urls.brewhub or constants.BREW_HUB)
    image_builds = _get_attached_image_builds(brew_session, advisories)

    referenced_specs = _extract_operator_manifest_image_references(image_builds)
    if not referenced_specs:
        # you are probably using this because you expect attached operator bundles or metadata
        raise ElliottFatalError(f"No bundle or appregistry builds found in advisories {advisories}.")

    # check if references are satisfied by any image we are shipping or have shipped
    image_builds.extend(_get_shipped_images(runtime, brew_session))
    available_shasums = _extract_available_image_shasums(image_builds)
    if _any_references_are_missing(referenced_specs, available_shasums):
        raise ElliottFatalError("Some references were missing. Ensure all manifest references are shipped or shipping.")
    green_print("All operator manifest references were found.")


def _get_attached_image_builds(brew_session, advisories):
    # get all attached image builds
    build_nvrs = []
    try:
        for advisory in advisories:
            green_print(f"Retrieving builds from advisory {advisory}")
            advisory = Erratum(errata_id=advisory)
            for build_list in advisory.errata_builds.values():  # one per product version
                build_nvrs.extend(build_list)
    except GSSError:
        exit_unauthenticated()

    green_print(f"Found {len(build_nvrs)} builds")
    return [build for build in brew.get_build_objects(build_nvrs, brew_session) if _is_image(build)]


def _is_image(build):
    return build.get('extra', {}).get('osbs_build', {}).get('kind') == "container_build"


def _is_bundle(image_build):
    return 'operator_bundle' in image_build.get('extra', {}).get('osbs_build', {}).get('subtypes', [])


def _is_appregistry(image_build):
    return 'operator_appregistry' in image_build.get('extra', {}).get('osbs_build', {}).get('subtypes', [])


def _extract_operator_manifest_image_references(image_builds):
    # extract referenced images from bundles to be shipped
    # returns a map[pullspec: bundle_nvr]
    image_specs = {}
    for image in image_builds:
        if _is_bundle(image):
            for pullspec in image['extra']['image']['operator_manifests']['related_images']['pullspecs']:
                image_specs[pullspec['new']] = image['nvr']
        elif _is_appregistry(image):
            for pullspec in _download_appregistry_image_references(image):
                image_specs[pullspec] = image['nvr']
    return image_specs


def _download_appregistry_image_references(appregistry_build):
    # for appregistry, image references are buried in the CSV in an archive
    url = constants.BREW_DOWNLOAD_TEMPLATE.format(
        name=appregistry_build['package_name'],
        version=appregistry_build['version'],
        release=appregistry_build['release'],
        file_path="operator-manifests/operator_manifests.zip",
    )
    try:
        res = requests.get(url, timeout=10.0)
    except Exception as ex:
        raise ElliottFatalError(f"appregistry data download {url} failed: {ex}")
    if res.status_code != 200:
        raise ElliottFatalError(f"appregistry data download {url} failed (status_code={res.status_code}): {res.text}")

    minor_version = re.match(r'^v(\d+\.\d+)', appregistry_build['version']).groups()[0]
    csv = {}
    with ZipFile(BytesIO(res.content)) as z:
        for filename in z.namelist():
            if re.match(f"^{minor_version}/.*clusterserviceversion.yaml", filename):
                with z.open(filename) as csv_file:
                    if csv:
                        raise ElliottFatalError(f"found more than one CSV in {appregistry_build['nvr']}?!? {filename}")
                    csv = yaml.full_load(csv_file)

    if not csv:
        raise ElliottFatalError(f"could not find the csv for appregistry {appregistry_build['nvr']}")
    return [ref['image'] for ref in csv['spec']['relatedImages']]


def _get_shipped_images(runtime, brew_session):
    # retrieve all image builds ever shipped for this version (potential operands)
    tag = f"{runtime.branch}-container-released"
    tags = {tag, tag.replace('-rhel-7-', '-rhel-8-')}  # may be one or two depending
    released = brew.get_tagged_builds(tags, build_type='image', event=None, session=brew_session)
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


def _any_references_are_missing(references, available):
    # check that referenced are all attached
    missing = False
    for image_pullspec, metadata in references.items():
        digest = image_pullspec.split("@")[1]  # just the shasum
        if digest not in available:
            missing = True
            ref = image_pullspec.rsplit('/', 1)[1]  # cut off the registry/namespace, just need the name:shasum
            red_print(f"{metadata} has a reference to {ref} not present in the advisories nor shipped images.")
    return missing
