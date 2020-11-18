from __future__ import absolute_import, print_function, unicode_literals

import json

import click
import koji
import requests
from errata_tool import Erratum
from kerberos import GSSError

import elliottlib
from elliottlib import Runtime, brew, constants, errata, logutil
from elliottlib.cli.common import (cli, find_default_advisory,
                                   use_default_advisory_option)
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import (ensure_erratatool_auth, exit_unauthenticated,
                             get_release_version, green_prefix, green_print,
                             parallel_results_with_progress, pbar_header,
                             progress_func, red_print)

LOGGER = logutil.getLogger(__name__)

pass_runtime = click.make_pass_decorator(Runtime)

#
# Attach Builds
# advisory:find-builds
#


@cli.command('find-builds', short_help='Find or attach builds to ADVISORY')
@click.option(
    '--attach', '-a', 'advisory',
    default=False, metavar='ADVISORY',
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
def find_builds_cli(runtime, advisory, default_advisory_type, builds, kind, from_diff, as_json, allow_attached, remove, clean, no_cdn_repos, payload, non_payload):
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

    runtime.initialize(mode='images' if kind == 'image' else 'none')
    replace_vars = runtime.group_config.vars.primitive() if runtime.group_config.vars else {}
    et_data = runtime.gitdata.load_data(key='erratatool', replace_vars=replace_vars).data
    tag_pv_map = et_data.get('brew_tag_product_version_mapping')

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    ensure_erratatool_auth()  # before we waste time looking up builds we can't process

    # get the builds we want to add
    unshipped_nvrps = []
    brew_session = koji.ClientSession(runtime.group_config.urls.brewhub or constants.BREW_HUB)
    if builds:
        green_prefix('Fetching builds...')
        unshipped_nvrps = _fetch_nvrps_by_nvr_or_id(builds, tag_pv_map, ignore_product_version=remove)
    elif clean:
        unshipped_builds = errata.get_brew_builds(advisory)
    elif from_diff:
        unshipped_nvrps = _fetch_builds_from_diff(from_diff[0], from_diff[1], tag_pv_map)
    else:
        if kind == 'image':
            unshipped_nvrps = _fetch_builds_by_kind_image(runtime, tag_pv_map, brew_session, payload, non_payload)
        elif kind == 'rpm':
            unshipped_nvrps = _fetch_builds_by_kind_rpm(tag_pv_map, brew_session)

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
        if not (allow_attached or builds):
            unshipped_builds = _filter_out_inviable_builds(kind, unshipped_builds, elliottlib.errata)

        _json_dump(as_json, unshipped_builds, kind, tag_pv_map)

        if not unshipped_builds:
            green_print('No builds needed to be attached.')
            return

    if advisory:
        if remove:
            _detach_builds(advisory, [f"{nvrp[0]}-{nvrp[1]}-{nvrp[2]}" for nvrp in unshipped_nvrps])
        elif clean:
            _detach_builds(advisory, [b.nvr for b in unshipped_builds])
        else:  # attach
            erratum = _update_to_advisory(unshipped_builds, kind, advisory, remove, clean)
            if not no_cdn_repos and kind == "image" and not (remove or clean):
                cdn_repos = et_data.get('cdn_repos')
                if cdn_repos:
                    # set up CDN repos
                    click.echo(f"Configuring CDN repos {', '.join(cdn_repos)}...")
                    erratum.metadataCdnRepos(enable=cdn_repos)
                    click.echo("Done")

    else:
        click.echo('The following {n} builds '.format(n=len(unshipped_builds)), nl=False)
        if not (remove or clean):
            click.secho('may be attached', bold=True, nl=False)
            click.echo(' to an advisory:')
        else:
            click.secho('may be removed from', bold=True, nl=False)
            click.echo(' from an advisory:')
        for b in sorted(unshipped_builds):
            click.echo(' ' + b.nvr)


def _fetch_nvrps_by_nvr_or_id(ids_or_nvrs, tag_pv_map, ignore_product_version=False):
    session = koji.ClientSession(constants.BREW_HUB)
    builds = brew.get_build_objects(ids_or_nvrs, session)
    nonexistent_builds = list(filter(lambda b: b[1] is None, zip(ids_or_nvrs, builds)))
    if nonexistent_builds:
        raise ValueError(f"The following builds are not found in Brew: {' '.join(map(lambda b: b[0],nonexistent_builds))}")
    nvrps = []
    if ignore_product_version:
        for build in builds:
            nvrps.append((build["name"], build["version"], build["release"], None))
        return nvrps
    for build, tags in zip(builds, brew.get_builds_tags(builds, session)):
        tag_names = {tag["name"] for tag in tags}
        product_versions = [pv for tag, pv in tag_pv_map.items() if tag in tag_names]
        if not product_versions:
            raise ValueError(f"Build {build['nvr']} doesn't have any of the following whitelisted tags: {list(tag_pv_map.keys())}")
        for pv in product_versions:
            nvrps.append((build["name"], build["version"], build["release"], pv))
    return nvrps


def _gen_nvrp_tuples(builds, tag_pv_map, tag):
    tuples = []
    for _, b in builds.items():
        tuples.append((b['name'], b['version'], b['release'], tag_pv_map[tag]))
    return tuples


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


def _fetch_builds_by_kind_image(runtime, tag_pv_map, brew_session, p, np):
    # filter out image like 'openshift-enterprise-base'
    image_metas = [i for i in runtime.image_metas() if not i.base_only]
    # Returns a list of (name, version, release, product_version) tuples of each build
    nvrps = []

    # type judge
    def tj(image, p, np):
        if not image.is_release:
            return False
        if p:
            return p == image.is_payload
        if np:
            # boolean xor.
            return np != image.is_payload
        else:
            return True

    tag_component_tuples = [(tag, image.get_component_name()) for tag in tag_pv_map for image in image_metas if tj(image, p, np)]

    pbar_header(
        'Generating list of images: ',
        f'Hold on a moment, fetching Brew builds for {len(image_metas)} components with tags {", ".join(tag_pv_map.keys())}...',
        tag_component_tuples)
    latest_builds = brew.get_latest_builds(tag_component_tuples, brew_session)

    for i, build in enumerate(latest_builds):
        if not build:
            continue
        tag = tag_component_tuples[i][0]
        nvrps.append((build[0]['name'], build[0]['version'], build[0]['release'], tag_pv_map[tag]))

    return nvrps


def _fetch_builds_by_kind_rpm(tag_pv_map, brew_session):
    green_prefix('Generating list of rpms: ')
    click.echo('Hold on a moment, fetching Brew builds')
    rpm_tuple = []
    for tag in tag_pv_map:
        if tag.endswith('-candidate'):
            base_tag = tag[:-10]
        else:
            red_print("key of brew_tag_product_version_mapping in erratatool.yml must be candidate\n")
            continue
        candidates = elliottlib.brew.find_unshipped_build_candidates(base_tag, brew_session=brew_session)
        rpm_tuple.extend(_gen_nvrp_tuples(candidates, tag_pv_map, tag))
    return rpm_tuple


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


def _update_to_advisory(builds, kind, advisory, remove, clean):
    click.echo(f"Attaching to advisory {advisory}...")
    if kind not in {"rpm", "image"}:
        raise ValueError(f"{kind} should be one of 'rpm' or 'image'")
    try:
        erratum = Erratum(errata_id=advisory)
        file_type = 'tar' if kind == 'image' else 'rpm'
        product_version_set = {build.product_version for build in builds}
        for pv in product_version_set:
            erratum.addBuilds(
                buildlist=[build.nvr for build in builds if build.product_version == pv],
                release=pv,
                file_types={build.nvr: [file_type] for build in builds}
            )
            erratum.commit()

        build_nvrs = sorted(build.nvr for build in builds)
        green_print('Attached build(s) successfully:')
        for b in build_nvrs:
            click.echo(' ' + b)
        return erratum

    except GSSError:
        exit_unauthenticated()
    except elliottlib.exceptions.BrewBuildException as ex:
        raise ElliottFatalError(f'Error attaching/removing builds: {str(ex)}')


def _detach_builds(advisory, nvrs):
    import requests_kerberos
    session = requests.Session()
    click.echo(f"Removing build(s) from advisory {advisory}...")
    for nvr in nvrs:
        errata.detach_build(advisory, nvr, session)
    green_print('Removed build(s) successfully:')
    for nvr in nvrs:
        click.echo(' ' + nvr)
