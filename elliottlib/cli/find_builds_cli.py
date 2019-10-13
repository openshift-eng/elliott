from __future__ import unicode_literals, print_function, with_statement
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
import json

import elliottlib
from elliottlib import constants, logutil, Runtime
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import exit_unauthenticated, green_prefix, override_product_version
from elliottlib.util import green_print, progress_func, pbar_header

from errata_tool import Erratum
from kerberos import GSSError
import requests
import click
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
    required=False, type=click.Choice(['rpm', 'image']),
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

    if (from_diff and kind) or (from_diff and builds) or (builds and kind):
        raise ElliottFatalError('Use only one of --kind or --build or --from-diff.')

    if not builds and not from_diff and not kind:
        raise ElliottFatalError('Must use one of --kind or --build or --from-diff.')

    if advisory and default_advisory_type:
        raise click.BadParameter('Use only one of --use-default-advisory or --attach')

    runtime.initialize()

    if not runtime.branch:
        raise ElliottFatalError('Need to specify a branch either in group.yml or with --branch option')
    base_tag = runtime.branch

    et_data = runtime.gitdata.load_data(key='erratatool').data
    product_version = override_product_version(et_data.get('product_version'), runtime.branch)

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    # Test authentication
    try:
        Erratum(errata_id=1)
    except GSSError:
        exit_unauthenticated()

    session = requests.Session()
    unshipped_builds = []

    if len(builds) > 0:
        green_prefix('Build NVRs provided: ')
        click.echo('Manually verifying the builds exist')
        try:
            unshipped_builds = [elliottlib.brew.get_brew_build(b, product_version, session=session) for b in builds]
        except elliottlib.exceptions.BrewBuildException as ex:
            raise ElliottFatalError(getattr(ex, 'message', repr(ex)))
    elif kind:
        if kind == 'image':
            initial_builds = runtime.image_metas()
            pbar_header('Generating list of {kind}s: '.format(kind=kind),
                        'Hold on a moment, fetching Brew buildinfo',
                        initial_builds)
            pool = ThreadPool(cpu_count())
            # Look up builds concurrently
            click.secho('[', nl=False)

            # Returns a list of (n, v, r) tuples of each build
            potential_builds = pool.map(
                lambda build: progress_func(lambda: build.get_latest_build_info(), '*'),
                initial_builds)
            # Wait for results
            pool.close()
            pool.join()
            click.echo(']')

            pbar_header('Generating build metadata: ',
                        'Fetching data for {n} builds '.format(n=len(potential_builds)),
                        potential_builds)
            click.secho('[', nl=False)

            # Reassign variable contents, filter out remove non_release builds
            potential_builds = [i for i in potential_builds
                                if i[0] not in runtime.group_config.get('non_release', [])]

            # By 'meta' I mean the lil bits of meta data given back from
            # get_latest_build_info
            #
            # TODO: Update the ImageMetaData class to include the NVR as
            # an object attribute.
            pool = ThreadPool(cpu_count())
            results = pool.map(
                lambda meta: progress_func(
                    lambda: elliottlib.brew.get_brew_build('{}-{}-{}'.format(meta[0], meta[1], meta[2]),
                                                           product_version,
                                                           session=session),
                    '*'),
                potential_builds)
            # Wait for results

            # filter out 'openshift-enterprise-base-container' since it's not needed in advisory
            unshipped_builds = [b for b in results
                                if not b.attached_to_open_erratum
                                if 'openshift-enterprise-base-container' not in b.nvr]
            pool.close()
            pool.join()
            click.echo(']')
        elif kind == 'rpm':
            green_prefix('Generating list of {kind}s: '.format(kind=kind))
            click.echo('Hold on a moment, fetching Brew builds')
            unshipped_build_candidates = elliottlib.brew.find_unshipped_build_candidates(
                base_tag,
                product_version,
                kind=kind)

            pbar_header('Gathering additional information: ', 'Brew buildinfo is required to continue', unshipped_build_candidates)
            click.secho('[', nl=False)

            # We could easily be making scores of requests, one for each build
            # we need information about. May as well do it in parallel.
            pool = ThreadPool(cpu_count())
            results = pool.map(
                lambda nvr: progress_func(
                    lambda: elliottlib.brew.get_brew_build(nvr, product_version, session=session),
                    '*'),
                unshipped_build_candidates)
            # Wait for results
            pool.close()
            pool.join()
            click.echo(']')

            # We only want builds not attached to an existing open advisory
            unshipped_builds = [b for b in results if not b.attached_to_open_erratum]
    elif from_diff:
        green_print('Fetching changed images between payloads...')
        changed_builds = elliottlib.openshiftclient.get_build_list(from_diff[0], from_diff[1])
        unshipped_builds = [elliottlib.brew.get_brew_build(b, product_version, session=session) for b in changed_builds]

    build_nvrs = sorted(build.nvr for build in unshipped_builds)
    json_data = dict(builds=build_nvrs, base_tag=base_tag, kind=kind)
    if as_json == '-':
        click.echo(json.dumps(json_data, indent=4, sort_keys=True))
    elif as_json:
        with open(as_json, 'w') as json_file:
            json.dump(json_data, json_file, indent=4, sort_keys=True)

    if not unshipped_builds:
        green_print('No builds needed to be attached.')
        return

    if advisory is not False:
        # Search and attach
        file_type = None
        try:
            erratum = Erratum(errata_id=advisory)
            if kind == 'image':
                file_type = 'tar'
            elif kind == 'rpm':
                file_type = 'rpm'

            if file_type is None:
                raise ElliottFatalError('Need to specify with --kind=image or --kind=rpm with packages: {}'.format(unshipped_builds))

            erratum.addBuilds(build_nvrs,
                              release=product_version,
                              file_types={build.nvr: [file_type] for build in unshipped_builds})
            erratum.commit()
            green_print('Attached build(s) successfully:')
            for b in sorted(unshipped_builds):
                click.echo(' ' + b.nvr)
        except GSSError:
            exit_unauthenticated()
        except elliottlib.exceptions.BrewBuildException as ex:
            raise ElliottFatalError('Error attaching builds: {}'.format(getattr(ex, 'message', repr(ex))))
    else:
        click.echo('The following {n} builds '.format(n=len(unshipped_builds)), nl=False)
        click.secho('may be attached ', bold=True, nl=False)
        click.echo('to an advisory:')
        for b in sorted(unshipped_builds):
            click.echo(' ' + b.nvr)
