import json
import re
from typing import Dict, List, Set, Union

import click
import koji
import requests
from errata_tool import Erratum, ErrataException
from spnego.exceptions import GSSError

import elliottlib
from elliottlib import Runtime, brew, constants, errata, logutil
from elliottlib.assembly import assembly_metadata_config, assembly_rhcos_config
from elliottlib.build_finder import BuildFinder
from elliottlib.cli.common import (cli, find_default_advisory,
                                   use_default_advisory_option)
from elliottlib.exceptions import ElliottFatalError
from elliottlib.imagecfg import ImageMetadata
from elliottlib.util import (ensure_erratatool_auth, exit_unauthenticated,
                             get_release_version, green_prefix, green_print,
                             isolate_el_version_in_brew_tag,
                             parallel_results_with_progress, pbar_header,
                             red_print, yellow_print)

LOGGER = logutil.getLogger(__name__)

pass_runtime = click.make_pass_decorator(Runtime)

#
# Attach Builds
# advisory:find-builds
#


@cli.command('find-builds', short_help='Find or attach builds to ADVISORY')
@click.option(
    '--attach', '-a', 'advisory',
    type=int, metavar='ADVISORY',
    help='Attach the builds to ADVISORY (by default only a list of builds are displayed)')
@use_default_advisory_option
@click.option(
    '--build', '-b', 'builds',
    multiple=True, metavar='NVR_OR_ID',
    help='Add build NVR_OR_ID to ADVISORY [MULTIPLE]')
@click.option(
    '--kind', '-k', metavar='KIND', required=True,
    type=click.Choice(['rpm', 'image']),
    help='Find builds of the given KIND [rpm, image]')
@click.option(
    '--from-diff', '--between',
    required=False,
    nargs=2,
    help='Two payloads to compare against')
@click.option(
    '--json', 'as_json', metavar='FILE_NAME',
    help='Dump new builds as JSON array to a file (or "-" for stdout)')
@click.option(
    '--allow-attached', metavar='FILE_NAME', is_flag=True,
    help='Allow images that have been attached to other advisories (default to True when "--build/-b" is used)')
@click.option(
    '--remove', required=False, is_flag=True,
    help='Remove builds from advisories instead of adding (default to False)')
@click.option(
    '--clean', required=False, is_flag=True,
    help='Clean up all the builds from advisories(default to False)')
@click.option(
    '--no-cdn-repos', required=False, is_flag=True,
    help='Do not configure CDN repos after attaching images (default to False)')
@click.option(
    '--payload', required=False, is_flag=True,
    help='Only attach payload images')
@click.option(
    '--non-payload', required=False, is_flag=True,
    help='Only attach non-payload images')
@pass_runtime
def find_builds_cli(runtime: Runtime, advisory, default_advisory_type, builds, kind, from_diff, as_json, allow_attached,
                    remove, clean, no_cdn_repos, payload, non_payload):
    '''Automatically or manually find or attach/remove viable rpm or image builds
to ADVISORY. Default behavior searches Brew for viable builds in the
given group. Provide builds manually by giving one or more --build
(-b) options. Manually provided builds are verified against the Errata
Tool API.

\b
  * Attach the builds to ADVISORY by giving --attach
  * Remove the builds to ADVISORY by giving --remove
  * Specify the build type using --kind KIND

Example: Assuming --group=openshift-3.7, then a build is a VIABLE
BUILD IFF it meets ALL of the following criteria:

\b
  * HAS the tag in brew: rhaos-3.7-rhel7-candidate
  * DOES NOT have the tag in brew: rhaos-3.7-rhel7
  * IS NOT attached to ANY existing RHBA, RHSA, or RHEA

That is to say, a viable build is tagged as a "candidate", has NOT
received the "shipped" tag yet, and is NOT attached to any PAST or
PRESENT advisory. Here are some examples:

    SHOW the latest OSE 3.6 image builds that would be attached to a
    3.6 advisory:

    $ elliott --group openshift-3.6 find-builds -k image

    ATTACH the latest OSE 3.6 rpm builds to advisory 123456:

\b
    $ elliott --group openshift-3.6 find-builds -k rpm --attach 123456

    VERIFY (no --attach) that the manually provided RPM NVR and build
    ID are viable builds:

    $ elliott --group openshift-3.6 find-builds -k rpm -b megafrobber-1.0.1-2.el7 -a 93170

\b
    Remove specific RPM NVR and build ID from advisory:

    $ elliott --group openshift-4.3 find-builds -k image -b oauth-server-container-v4.3.22-202005212137 -a 55017 --remove
'''

    if from_diff and builds:
        raise click.BadParameter('Use only one of --build or --from-diff/--between.')
    if clean and (remove or from_diff or builds):
        raise click.BadParameter('Option --clean cannot be used with --build or --from-diff/--between.')
    if not builds and remove:
        raise click.BadParameter('Option --remove only support removing specific build with -b.')
    if from_diff and kind != "image":
        raise click.BadParameter('Option --from-diff/--between should be used with --kind/-k image.')
    if advisory and default_advisory_type:
        raise click.BadParameter('Use only one of --use-default-advisory or --attach')
    if payload and non_payload:
        raise click.BadParameter('Use only one of --payload or --non-payload.')

    runtime.initialize(mode='images' if kind == 'image' else 'rpms')
    replace_vars = runtime.group_config.vars.primitive() if runtime.group_config.vars else {}
    et_data = runtime.gitdata.load_data(key='erratatool', replace_vars=replace_vars).data
    tag_pv_map = et_data.get('brew_tag_product_version_mapping')

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    ensure_erratatool_auth()  # before we waste time looking up builds we can't process

    unshipped_nvrps = []
    unshipped_builds = []
    to_remove = []

    # get the builds we want to add
    brew_session = runtime.build_retrying_koji_client(caching=True)
    if builds:
        green_prefix('Fetching builds...')
        unshipped_nvrps = _fetch_nvrps_by_nvr_or_id(builds, tag_pv_map, ignore_product_version=remove, brew_session=brew_session)
    elif clean:
        unshipped_builds = errata.get_brew_builds(advisory)
    elif from_diff:
        unshipped_nvrps = _fetch_builds_from_diff(from_diff[0], from_diff[1], tag_pv_map)
    else:
        if kind == 'image':
            unshipped_nvrps = _fetch_builds_by_kind_image(runtime, tag_pv_map, brew_session, payload,
                                                          non_payload)
        elif kind == 'rpm':
            unshipped_nvrps = _fetch_builds_by_kind_rpm(runtime, tag_pv_map, brew_session)

    pbar_header(
        'Fetching builds from Errata: ',
        'Hold on a moment, fetching buildinfos from Errata Tool...',
        unshipped_builds if clean else unshipped_nvrps)

    if not clean and not remove:
        # if is --clean then batch fetch from Erratum no need to fetch them individually
        # if is not for --clean fetch individually using nvrp tuples then get specific
        # elliottlib.brew.Build Objects by get_brew_build()
        # e.g. :
        # ('atomic-openshift-descheduler-container', 'v4.3.23', '202005250821', 'RHEL-7-OSE-4.3').
        # Build(atomic-openshift-descheduler-container-v4.3.23-202005250821).
        unshipped_builds = parallel_results_with_progress(
            unshipped_nvrps,
            lambda nvrp: elliottlib.errata.get_brew_build('{}-{}-{}'.format(nvrp[0], nvrp[1], nvrp[2]), nvrp[3], session=requests.Session())
        )
        if not allow_attached:
            unshipped_builds = _filter_out_inviable_builds(kind, unshipped_builds, elliottlib.errata)

        _json_dump(as_json, unshipped_builds, kind, tag_pv_map)

        if not unshipped_builds:
            green_print('No builds needed to be attached.')
            return

    if not advisory:
        click.echo('The following {n} builds '.format(n=len(unshipped_builds)), nl=False)
        if not (remove or clean):
            click.secho('may be attached', bold=True, nl=False)
            click.echo(' to an advisory:')
        else:
            click.secho('may be removed from', bold=True, nl=False)
            click.echo(' from an advisory:')
        for b in sorted(unshipped_builds):
            click.echo(' ' + b.nvr)
        return

    if not unshipped_builds and not (remove and unshipped_nvrps):
        # Do not change advisory state unless strictly necessary
        return

    try:
        erratum = elliottlib.errata.Advisory(errata_id=advisory)
        erratum.ensure_state('NEW_FILES')
        if remove:
            to_remove = [f"{nvrp[0]}-{nvrp[1]}-{nvrp[2]}" for nvrp in unshipped_nvrps]
        elif clean:
            to_remove = [b.nvr for b in unshipped_builds]

        if to_remove:
            erratum.remove_builds(to_remove)
        else:  # attach
            erratum.attach_builds(unshipped_builds, kind)
            cdn_repos = et_data.get('cdn_repos')
            if cdn_repos and not no_cdn_repos and kind == "image":
                erratum.set_cdn_repos(cdn_repos)

    except GSSError:
        exit_unauthenticated()
    except ErrataException as e:
        red_print(f'Cannot change advisory {advisory}: {e}')
        exit(1)


def _fetch_nvrps_by_nvr_or_id(ids_or_nvrs, tag_pv_map, ignore_product_version=False, brew_session: koji.ClientSession = None):
    session = koji.ClientSession(constants.BREW_HUB)
    builds = brew.get_build_objects(ids_or_nvrs, session)
    nonexistent_builds = list(filter(lambda b: b[1] is None, zip(ids_or_nvrs, builds)))
    if nonexistent_builds:
        raise ValueError(f"The following builds are not found in Brew: {' '.join(map(lambda b: b[0],nonexistent_builds))}")
    _ensure_accepted_tags(builds, session, tag_pv_map)
    shipped = _find_shipped_builds([b["id"] for b in builds], session)
    unshipped = [b for b in builds if b["id"] not in shipped]
    nvrps = []
    if ignore_product_version:
        for build in unshipped:
            nvrps.append((build["name"], build["version"], build["release"], None))
        return nvrps
    for build in unshipped:
        product_versions = {pv for tag, pv in tag_pv_map.items() if tag in build["_tags"]}
        if not product_versions:
            raise ValueError(f"Build {build['nvr']} doesn't have any of the following whitelisted tags: {list(tag_pv_map.keys())}")
        for pv in product_versions:
            nvrps.append((build["name"], build["version"], build["release"], pv))
    return nvrps


def _gen_nvrp_tuples(builds: List[Dict], tag_pv_map: Dict[str, str]):
    """Returns a list of (name, version, release, product_version) tuples of each build """
    nvrps = [(b['name'], b['version'], b['release'], tag_pv_map[b['tag_name']]) for b in builds]
    return nvrps


def _json_dump(as_json, unshipped_builds, kind, tag_pv_map):
    if as_json:
        builds = []
        tags = []
        reversed_tag_pv_map = {y: x for x, y in tag_pv_map.items()}
        for b in sorted(unshipped_builds):
            builds.append(b.nvr)
            tags.append(reversed_tag_pv_map[b.product_version])
        json_data = dict(builds=builds, base_tag=tags, kind=kind)
        if as_json == '-':
            click.echo(json.dumps(json_data, indent=4, sort_keys=True))
        else:
            with open(as_json, 'w') as json_file:
                json.dump(json_data, json_file, indent=4, sort_keys=True)


def _fetch_builds_from_diff(from_payload, to_payload, tag_pv_map):
    green_print('Fetching changed images between payloads...')
    nvrs = elliottlib.openshiftclient.get_build_list(from_payload, to_payload)
    return _fetch_nvrps_by_nvr_or_id(nvrs, tag_pv_map)


def _find_shipped_builds(build_ids: List[Union[str, int]], brew_session: koji.ClientSession) -> Set[Union[str, int]]:
    """ Finds shipped builds
    :param builds: list of Brew build IDs or NVRs
    :param brew_session: Brew session
    :return: a set of shipped Brew build IDs or NVRs
    """
    shipped_ids = set()
    tag_lists = brew.get_builds_tags(build_ids, brew_session)
    released_tag_pattern = re.compile(r"^RH[BSE]A-.+-released$")  # https://issues.redhat.com/browse/ART-3277
    for build_id, tags in zip(build_ids, tag_lists):
        # a shipped build with OCP Errata should have a Brew tag ending with `-released`, like `RHBA-2020:2713-released`
        shipped = any(map(lambda tag: released_tag_pattern.match(tag["name"]), tags))
        if shipped:
            shipped_ids.add(build_id)
    return shipped_ids


def _fetch_builds_by_kind_image(runtime: Runtime, tag_pv_map: Dict[str, str],
                                brew_session: koji.ClientSession, payload_only: bool, non_payload_only: bool):
    image_metas: List[ImageMetadata] = []
    for image in runtime.image_metas():
        if image.base_only or not image.is_release:
            continue
        if (payload_only and not image.is_payload) or (non_payload_only and image.is_payload):
            continue
        image_metas.append(image)

    pbar_header(
        'Generating list of images: ',
        f'Hold on a moment, fetching Brew builds for {len(image_metas)} components...')

    brew_latest_builds: List[Dict] = []
    for image in image_metas:
        LOGGER.info("Getting latest build for %s...", image.distgit_key)
        brew_latest_builds.append(image.get_latest_build(brew_session))

    _ensure_accepted_tags(brew_latest_builds, brew_session, tag_pv_map)

    shipped = _find_shipped_builds([b["id"] for b in brew_latest_builds], brew_session)
    unshipped = [b for b in brew_latest_builds if b["id"] not in shipped]
    click.echo(f'Found {len(shipped)+len(unshipped)} builds, of which {len(unshipped)} are new.')
    nvrps = _gen_nvrp_tuples(unshipped, tag_pv_map)
    return nvrps


def _ensure_accepted_tags(builds: List[Dict], brew_session: koji.ClientSession, tag_pv_map: Dict[str, str], raise_exception: bool = True):
    """
    Build dicts returned by koji.listTagged API have their tag names, however other APIs don't set that field.
    Tag names are required because they are associated with Errata product versions.
    For those build dicts whose tags are unknown, we need to query from Brew.
    """
    builds = [b for b in builds if "tag_name" not in b]  # filters out builds whose accepted tag is already set
    unknown_tags_builds = [b for b in builds if "_tags" not in b]  # finds builds whose tags are not cached
    build_tag_lists = brew.get_builds_tags(unknown_tags_builds, brew_session)
    for build, tags in zip(unknown_tags_builds, build_tag_lists):
        build["_tags"] = {tag['name'] for tag in tags}
    # Finds and sets the accepted tag (rhaos-x.y-rhel-z-[candidate|hotfix]) for each build
    for build in builds:
        accepted_tag = next(filter(lambda tag: tag in tag_pv_map, build["_tags"]), None)
        if not accepted_tag:
            msg = f"Build {build['nvr']} has Brew tags {build['_tags']}, but none of them has an associated Errata product version."
            if raise_exception:
                raise IOError(msg)
            else:
                LOGGER.warning(msg)
                continue
        build["tag_name"] = accepted_tag


def _fetch_builds_by_kind_rpm(runtime: Runtime, tag_pv_map: Dict[str, str], brew_session: koji.ClientSession):
    assembly = runtime.assembly
    if runtime.assembly_basis_event:
        LOGGER.warning(f'Constraining rpm search to stream assembly due to assembly basis event {runtime.assembly_basis_event}')
        # If an assembly has a basis event, its latest rpms can only be sourced from
        # "is:" or the stream assembly.
        assembly = 'stream'

        # ensures the runtime assembly doesn't include any image member specific or rhcos specific dependencies
        image_configs = [assembly_metadata_config(runtime.get_releases_config(), runtime.assembly, 'image', image.distgit_key, image.config) for _, image in runtime.image_map.items()]
        if any(nvr for image_config in image_configs for dep in image_config.dependencies.rpms for _, nvr in dep.items()):
            raise ElliottFatalError(f"Assembly {runtime.assembly} is not appliable for build sweep because it contains image member specific dependencies for a custom release.")
        rhcos_config = assembly_rhcos_config(runtime.get_releases_config(), runtime.assembly)
        if any(nvr for dep in rhcos_config.dependencies.rpms for _, nvr in dep.items()):
            raise ElliottFatalError(f"Assembly {runtime.assembly} is not appliable for build sweep because it contains RHCOS specific dependencies for a custom release.")

    green_prefix('Generating list of rpms: ')
    click.echo('Hold on a moment, fetching Brew builds')

    builder = BuildFinder(brew_session, logger=LOGGER)
    builds: List[Dict] = []
    for tag in tag_pv_map:
        # keys are rpm component names, values are nvres
        component_builds: Dict[str, Dict] = builder.from_tag("rpm", tag, inherit=False, assembly=assembly, event=runtime.brew_event)

        if runtime.assembly_basis_event:
            # If an assembly has a basis event, rpms pinned by "is" and group dependencies should take precedence over every build from the tag
            el_version = isolate_el_version_in_brew_tag(tag)
            if not el_version:
                continue  # Only honor pinned rpms if this tag is relevant to a RHEL version

            # Honors pinned NVRs by "is"
            pinned_by_is = builder.from_pinned_by_is(el_version, runtime.assembly, runtime.get_releases_config(), runtime.rpm_map)
            _ensure_accepted_tags(pinned_by_is.values(), brew_session, tag_pv_map)

            # Builds pinned by "is" should take precedence over every build from tag
            for component, pinned_build in pinned_by_is.items():
                if component in component_builds and pinned_build["id"] != component_builds[component]["id"]:
                    LOGGER.warning("Swapping stream nvr %s for pinned nvr %s...", component_builds[component]["nvr"], pinned_build["nvr"])

            component_builds.update(pinned_by_is)  # pinned rpms take precedence over those from tags

            # Honors group dependencies
            group_deps = builder.from_group_deps(el_version, runtime.group_config, runtime.rpm_map)  # the return value doesn't include any ART managed rpms
            # Group dependencies should take precedence over anything previously determined except those pinned by "is".
            for component, dep_build in group_deps.items():
                if component in component_builds and dep_build["id"] != component_builds[component]["id"]:
                    LOGGER.warning("Swapping stream nvr %s for group dependency nvr %s...", component_builds[component]["nvr"], dep_build["nvr"])
            component_builds.update(group_deps)
        builds.extend(component_builds.values())

    _ensure_accepted_tags(builds, brew_session, tag_pv_map, raise_exception=False)
    qualified_builds = [b for b in builds if "tag_name" in b]
    not_attachable_nvrs = [b["nvr"] for b in builds if "tag_name" not in b]

    if not_attachable_nvrs:
        yellow_print(f"The following NVRs will not be swept because they don't have allowed tags {list(tag_pv_map.keys())}:")
        for nvr in not_attachable_nvrs:
            yellow_print(f"\t{nvr}")

    click.echo("Filtering out shipped builds...")
    shipped = _find_shipped_builds([b["id"] for b in qualified_builds], brew_session)
    unshipped = [b for b in qualified_builds if b["id"] not in shipped]
    click.echo(f'Found {len(shipped)+len(unshipped)} builds, of which {len(unshipped)} are new.')
    nvrps = _gen_nvrp_tuples(unshipped, tag_pv_map)
    nvrps = sorted(set(nvrps))  # remove duplicates
    return nvrps


def _filter_out_inviable_builds(kind, results, errata):
    unshipped_builds = []
    errata_version_cache = {}  # avoid reloading the same errata for multiple builds
    for b in results:
        # check if build is attached to any existing advisory for this version
        in_same_version = False
        for eid in [e['id'] for e in b.all_errata]:
            if eid not in errata_version_cache:
                metadata_comments_json = errata.get_metadata_comments_json(eid)
                if not metadata_comments_json:
                    # Does not contain ART metadata; consider it unversioned
                    red_print("Errata {} Does not contain ART metadata\n".format(eid))
                    errata_version_cache[eid] = ''
                    continue
                # it's possible for an advisory to have multiple metadata comments,
                # though not very useful (there's a command for adding them,
                # but not much point in doing it). just looking at the first one is fine.
                errata_version_cache[eid] = metadata_comments_json[0]['release']
            if errata_version_cache[eid] == get_release_version(b.product_version):
                in_same_version = True
                break
        if not in_same_version:
            unshipped_builds.append(b)
    return unshipped_builds
