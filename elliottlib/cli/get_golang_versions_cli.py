import click

from elliottlib import errata, logutil, util
from elliottlib.cli.common import (cli, find_default_advisory,
                                   use_default_advisory_option)
from elliottlib.rpm_utils import parse_nvr

_LOGGER = logutil.getLogger(__name__)


@cli.command("go", short_help="Get version of Go for advisory builds")
@click.option('--advisory', '-a', 'advisory_id', type=int,
              help="The advisory ID to fetch builds from")
@use_default_advisory_option
@click.option('--nvrs', '-n',
              help="Brew nvrs to show go version for. Comma separated")
@click.option('--components', '-c',
              help="Only show go versions for these components (rpms/images) in advisory. Comma separated")
@click.pass_obj
def get_golang_versions_cli(runtime, advisory_id, default_advisory_type, nvrs, components):
    """
    Prints the Go version used to build a component to stdout.

    Usage:

\b
    $ elliott go -a 76557

    List go version for brew builds in the given advisory

\b
    $ elliott go -a 79683 -c ironic-container,ose-ovirt-csi-driver-container

    List go version for brew builds in the given advisory

\b
    $ elliott -g openshift-4.8 go --use-default-advisory image -c grafana-container,ose-installer-container

    List go version for brew builds for given component names attached to the default advisory for a group

\b
    $ elliott go -n podman-3.0.1-6.el8,podman-1.9.3-3.rhaos4.6.el8

    List go version for given brew builds
"""
    count_options = sum(map(bool, [advisory_id, nvrs, default_advisory_type]))
    if count_options > 1:
        raise click.BadParameter("Use only one of --advisory, --nvrs, --use-default-advisory")

    if default_advisory_type:
        runtime.initialize()
        advisory_id = find_default_advisory(runtime, default_advisory_type)
    else:
        runtime.initialize(no_group=True)

    if advisory_id:
        if components:
            components = [c.strip() for c in components.split(',')]
        return get_advisory_golang(advisory_id, components)
    elif nvrs:
        nvrs = [n.strip() for n in nvrs.split(',')]
        return get_nvrs_golang(nvrs)
    else:
        util.red_print('The input value is not valid.')


def get_nvrs_golang(nvrs):
    container_nvrs, rpm_nvrs = [], []
    for n in nvrs:
        parsed_nvr = parse_nvr(n)
        nvr_tuple = (parsed_nvr['name'], parsed_nvr['version'], parsed_nvr['release'])
        if 'container' in parsed_nvr['name']:
            container_nvrs.append(nvr_tuple)
        else:
            rpm_nvrs.append(nvr_tuple)

    if rpm_nvrs:
        go_nvr_map = util.get_golang_rpm_nvrs(rpm_nvrs, _LOGGER)
        util.pretty_print_nvrs_go(go_nvr_map)
    elif container_nvrs:
        go_nvr_map = util.get_golang_container_nvrs(container_nvrs, _LOGGER)
        util.pretty_print_nvrs_go(go_nvr_map)
    else:
        util.green_print('There is no builds related to golang.')


def get_advisory_golang(advisory_id, components):
    nvrs = errata.get_all_advisory_nvrs(advisory_id)
    _LOGGER.debug(f'{len(nvrs)} builds found in advisory')
    if not nvrs:
        _LOGGER.debug('No builds found. exiting')
        util.green_print('there is no builds related to golang')
        return
    if components:
        if 'openshift' in components:
            components.remove('openshift')
            components.append('openshift-hyperkube')
        nvrs = [p for p in nvrs if p[0] in components]

    content_type = errata.get_erratum_content_type(advisory_id)
    if content_type == 'docker':
        go_nvr_map = util.get_golang_container_nvrs(nvrs, _LOGGER)
    else:
        go_nvr_map = util.get_golang_rpm_nvrs(nvrs, _LOGGER)

    util.pretty_print_nvrs_go(go_nvr_map)
