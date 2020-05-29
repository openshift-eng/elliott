from __future__ import absolute_import, print_function, unicode_literals
import json

import elliottlib
from elliottlib import constants, logutil, Runtime, brew
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import exit_unauthenticated, ensure_erratatool_auth, get_release_version
from elliottlib.util import green_prefix, green_print, parallel_results_with_progress, pbar_header, red_print, progress_func
from errata_tool import Erratum
from kerberos import GSSError
import requests, click, koji
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
@pass_runtime
def find_builds_cli(runtime, advisory, default_advisory_type, builds, kind, from_diff, as_json, allow_attached, remove, clean, no_cdn_repos):
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
    if remove and clean:
        raise click.BadParameter('Use only one of --remove or --clean.')
    if not builds and remove:
        raise click.BadParameter('Option --remove only support removing specific build with -b.')
    if from_diff and kind != "image":
        raise click.BadParameter('Option --from-diff/--between should be used with --kind/-k image.')
    if advisory and default_advisory_type:
        raise click.BadParameter('Use only one of --use-default-advisory or --attach')

    runtime.initialize(mode='images' if kind == 'image' else 'none')
    replace_vars = runtime.group_config.vars.primitive() if runtime.group_config.vars else {}
    et_data = runtime.gitdata.load_data(key='erratatool', replace_vars=replace_vars).data
    tag_pv_map = et_data.get('brew_tag_product_version_mapping')

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    ensure_erratatool_auth()  # before we waste time looking up builds we can't process

    # get the builds we want to add
    unshipped_nvrps = []
    if builds:
        green_prefix('Fetching tags for builds...')
        unshipped_nvrps = _fetch_builds_by_nvr_or_id(builds, tag_pv_map)
    elif clean:
        unshipped_builds = elliottlib.errata.get_brew_builds(advisory)
    elif from_diff:
        unshipped_nvrps = _fetch_builds_from_diff(from_diff[0], from_diff[1], tag_pv_map)
    else:
        brew_session = koji.ClientSession(runtime.group_config.urls.brewhub or constants.BREW_HUB)
        if kind == 'image':
            unshipped_nvrps = _fetch_builds_by_kind_image(runtime, tag_pv_map, brew_session)
        elif kind == 'rpm':
            unshipped_nvrps = _fetch_builds_by_kind_rpm(tag_pv_map, brew_session)

    pbar_header(
        'Fetching builds from Errata: ',
        'Hold on a moment, fetching buildinfos from Errata Tool...',
        unshipped_builds if clean else unshipped_nvrps)

    if not clean:
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

    if not (clean or allow_attached or builds):
        unshipped_builds = _filter_out_inviable_builds(kind, unshipped_builds, elliottlib.errata)

    _json_dump(as_json, unshipped_builds, kind, tag_pv_map)

    if not unshipped_builds:
        green_print('No builds needed to be attached.')
        return

    if advisory:
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
        click.secho('may be attached ', bold=True, nl=False)
        click.echo('to an advisory:')
        for b in sorted(unshipped_builds):
            click.echo(' ' + b.nvr)


def _fetch_builds_by_nvr_or_id(ids_or_nvrs, tag_pv_map):
    session = koji.ClientSession(constants.BREW_HUB)
    builds = brew.get_build_objects(ids_or_nvrs, session)
    nvrps = []
    for index, tags in enumerate(brew.get_builds_tags(builds, session)):
        build = builds[index]  # type: dict
        tag_names = {tag["name"] for tag in tags}
        for tag, prod_version in tag_pv_map.items():
            if tag in tag_names:
                nvrps.append((build["name"], build["version"], build["release"], prod_version))
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
    return _fetch_builds_by_nvr_or_id(nvrs, tag_pv_map)


def _fetch_builds_by_kind_image(runtime, tag_pv_map, brew_session):
    # filter out image like 'openshift-enterprise-base'
    image_metas = [i for i in runtime.image_metas() if not i.base_only]
    # Returns a list of (name, version, release, product_version) tuples of each build
    nvrps = []

    tag_component_tuples = [(tag, image.get_component_name()) for tag in tag_pv_map for image in image_metas]
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
    if remove:
        click.echo(f"Remvoing from advisory {advisory}...")
    elif clean:
        click.echo(f"Clean up all the builds from advisory {advisory}...")
    else:
        click.echo(f"Attaching to advisory {advisory}...")
    if kind not in {"rpm", "image"}:
        raise ValueError(f"{kind} should be one of 'rpm' or 'image'")
    try:
        erratum = Erratum(errata_id=advisory)
        file_type = 'tar' if kind == 'image' else 'rpm'
        product_version_set = {build.product_version for build in builds}
        for pv in product_version_set:
            if remove or clean:
                erratum.removeBuilds(
                    buildlist=[build.nvr for build in builds if build.product_version == pv])
            else:
                erratum.addBuilds(
                    buildlist=[build.nvr for build in builds if build.product_version == pv],
                    release=pv,
                    file_types={build.nvr: [file_type] for build in builds}
                )
            erratum.commit()

        build_nvrs = sorted(build.nvr for build in builds)
        if remove:
            green_print('Removed build(s) successfully:')
        elif clean:
            green_print('Cleanup build(s) successfully:')
        else:
            green_print('Attached build(s) successfully:')
        for b in build_nvrs:
            click.echo(' ' + b)
        return erratum

    except GSSError:
        exit_unauthenticated()
    except elliottlib.exceptions.BrewBuildException as ex:
        raise ElliottFatalError(f'Error attaching/removing builds: {str(ex)}')
