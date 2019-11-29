from __future__ import unicode_literals, print_function, with_statement
import json

import elliottlib
from elliottlib import constants, logutil, Runtime
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import exit_unauthenticated, override_product_version, ensure_erratatool_auth, get_release_version
from elliottlib.util import green_prefix, green_print, parallel_results_with_progress, pbar_header, red_print, progress_func
from errata_tool import Erratum
from kerberos import GSSError
import requests
import click, koji
# https://click.palletsprojects.com/en/7.x/python3/
click.disable_unicode_literals_warning = True


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
    '--kind', '-k', metavar='KIND',
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
@pass_runtime
def find_builds_cli(runtime, advisory, default_advisory_type, builds, kind, from_diff, as_json):
    '''Automatically or manually find or attach viable rpm or image builds
to ADVISORY. Default behavior searches Brew for viable builds in the
given group. Provide builds manually by giving one or more --build
(-b) options. Manually provided builds are verified against the Errata
Tool API.

\b
  * Attach the builds to ADVISORY by giving --attach
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

\b
    $ elliott --group openshift-3.6 find-builds -k rpm -b megafrobber-1.0.1-2.el7 -b 93170
'''

    if from_diff and builds:
        raise ElliottFatalError('Use only one of --build or --from-diff.')
    if advisory and default_advisory_type:
        raise click.BadParameter('Use only one of --use-default-advisory or --attach')

    runtime.initialize()
    base_tag, product_version, product_version_map = _determine_errata_info(runtime)

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    ensure_erratatool_auth()  # before we waste time looking up builds we can't process

    # get the builds we want to add
    unshipped_nvrs = []
    if builds:
        unshipped_nvrs = _fetch_builds_by_id(builds)
    elif from_diff:
        unshipped_nvrs = _fetch_builds_from_diff(from_diff[0], from_diff[1])
    else:
        if kind == 'image':
            unshipped_nvrs = _fetch_builds_by_kind_image(runtime, product_version)
        elif kind == 'rpm':
            unshipped_nvrs = _fetch_builds_by_kind_rpm(base_tag, product_version)

    results = parallel_results_with_progress(
        unshipped_nvrs,
        lambda nvr: _nvrs_to_builds(nvr, product_version, product_version_map, requests.Session(),
                                    koji.ClientSession(constants.BREW_HUB))
    )

    unshipped_builds = _attached_to_open_erratum_with_correct_pv(kind, results, elliottlib.errata)

    _json_dump(as_json, unshipped_builds, base_tag, kind)

    if not unshipped_builds:
        green_print('No builds needed to be attached.')
        return

    if advisory:
        _attach_to_advisory(unshipped_builds, kind, advisory)
    else:
        click.echo('The following {n} builds '.format(n=len(unshipped_builds)), nl=False)
        click.secho('may be attached ', bold=True, nl=False)
        click.echo('to an advisory:')
        for b in sorted(unshipped_builds):
            click.echo(' ' + b.nvr)


def _get_product_version(nvr, default_product_version, product_version_map, brew_session):
    product_version = ""
    for tag in brew_session.listTags(nvr):
        tag_name = tag.get('name')
        product_version = product_version_map.get(tag_name, "")
        if product_version != "":
            return product_version
    if product_version == "":
        return default_product_version


def _nvrs_to_builds(nvr, default_product_version, product_version_map, errata_session, brew_session):
    pv = _get_product_version(nvr, default_product_version, product_version_map, brew_session)
    return elliottlib.brew.get_brew_build(nvr, pv, session=errata_session)


def _json_dump(as_json, unshipped_builds, base_tag, kind):
    if as_json:
        build_nvrs = sorted(build.nvr for build in unshipped_builds)
        json_data = dict(builds=build_nvrs, base_tag=base_tag, kind=kind)
        if as_json == '-':
            click.echo(json.dumps(json_data, indent=4, sort_keys=True))
        else:
            with open(as_json, 'w') as json_file:
                json.dump(json_data, json_file, indent=4, sort_keys=True)


def _determine_errata_info(runtime):
    if not runtime.branch or not runtime.product_id:
        raise ElliottFatalError('Need to specify branch/product_id either in group.yml/erratatool.yml or with '
                                '--branch/--product-id option')
    return runtime.branch, runtime.erratatool_config.product_version, \
        elliottlib.errata.get_product_version_from_tag(runtime.product_id)


def _fetch_builds_by_id(builds):
    green_prefix('Build NVRs provided: ')
    click.echo('Manually verifying the builds exist')
    return builds


def _fetch_builds_from_diff(from_payload, to_payload):
    green_print('Fetching changed images between payloads...')
    return elliottlib.openshiftclient.get_build_list(from_payload, to_payload)


def _fetch_builds_by_kind_image(runtime, default_product_version):
    image_metadata = []
    product_version_overide = {}
    for b in runtime.image_metas():
        # filter out non_release builds
        if b not in runtime.group_config.get('non_release', []):
            product_version_overide[b.name] = default_product_version
            if b.branch() != runtime.branch:
                product_version_overide[b.name] = override_product_version(default_product_version, b.branch())
            image_metadata.append(b)

    pbar_header(
        'Generating list of images: ',
        'Hold on a moment, fetching Brew buildinfo',
        image_metadata)

    # Returns a list of (n, v, r, pv) tuples of each build
    image_tuples = parallel_results_with_progress(
        image_metadata,
        lambda build: build.get_latest_build_info(product_version_overide)
    )

    pbar_header(
        'Generating build metadata: ',
        'Fetching data for {n} builds '.format(n=len(image_tuples)),
        image_tuples)

    nvrs = []
    for meta in image_tuples:
        nvrs.append('{}-{}-{}'.format(meta[0], meta[1], meta[2]))
    return nvrs


def _fetch_builds_by_kind_rpm(base_tag, product_version):
    green_prefix('Generating list of rpms: ')
    click.echo('Hold on a moment, fetching Brew builds')
    candidates = elliottlib.brew.find_unshipped_build_candidates(
        base_tag,
        product_version,
        kind='rpm')

    pbar_header('Gathering additional information: ', 'Brew buildinfo is required to continue', candidates)
    return candidates


def _attached_to_open_erratum_with_correct_pv(kind, results, errata):
    if kind != "image":
        return results
    unshipped_builds = []
    # will probably end up loading the same errata and
    # its comments many times, which is pretty slow
    # so we cached the result.
    errata_version_cache = {}
    for b in results:
        if b.nvr.startswith('openshift-enterprise-base-container'):
            continue
        same_version_exist = False
        # We only want builds not attached to an existing open advisory
        if b.attached_to_open_erratum:
            for e in b.open_errata_id:
                if not errata_version_cache.get(e):
                    metadata_comments_json = errata.get_metadata_comments_json(e)
                    if not metadata_comments_json:
                        # Does not contain ART metadata, skip it
                        red_print("Errata {} Does not contain ART metadata\n".format(e))
                        continue
                    # it's possible for an advisory to have multiple metadata comments,
                    # though not very useful (there's a command for adding them,
                    # but not much point in doing it). just looking at the first one is fine.
                    errata_version_cache[e] = metadata_comments_json[0]['release']
                print(b, b.product_version)
                if errata_version_cache[e] == get_release_version(b.product_version):
                    same_version_exist = True
                    break
        if not same_version_exist or not b.attached_to_open_erratum:
            unshipped_builds.append(b)
    return unshipped_builds


def _attach_to_advisory(builds, kind, advisory):
    if kind is None:
        raise ElliottFatalError('Need to specify with --kind=image or --kind=rpm with packages: {}'.format(builds))

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

    except GSSError:
        exit_unauthenticated()
    except elliottlib.exceptions.BrewBuildException as ex:
        raise ElliottFatalError('Error attaching builds: {}'.format(getattr(ex, 'message', repr(ex))))
