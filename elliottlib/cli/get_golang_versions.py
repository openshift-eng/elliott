from elliottlib import brew, constants, errata, Runtime
from elliottlib.cli.common import cli
from elliottlib.exceptions import BrewBuildException
from elliottlib.util import get_golang_version_from_root_log

import click
import koji
pass_runtime = click.make_pass_decorator(Runtime)


def get_rpm_golang_versions(advisory_id: str):
    all_advisory_nvrs = errata.get_all_advisory_nvrs(advisory_id)

    click.echo("Found {} builds".format(len(all_advisory_nvrs)))
    for nvr in all_advisory_nvrs:
        try:
            root_log = brew.get_nvr_root_log(*nvr)
        except BrewBuildException as e:
            print(e)
            continue
        try:
            golang_version = get_golang_version_from_root_log(root_log)
        except AttributeError:
            print('Could not find Go version in {}-{}-{} root.log'.format(*nvr))
            continue
        print('{}-{}-{}:\t{}'.format(*nvr, golang_version))


def get_container_golang_versions(advisory_id: str):
    all_builds = errata.get_brew_builds(advisory_id)

    all_build_objs = brew.get_build_objects([b.nvr for b in all_builds])
    for build in all_build_objs:
        golang_version = None
        name = build.get('name')
        try:
            parents = build['extra']['image']['parent_image_builds']
        except KeyError:
            print('Could not get parent image info for {}'.format(name))
            continue

        for p, pinfo in parents.items():
            if 'builder' in p:
                golang_version = pinfo.get('nvr')

        if golang_version is not None:
            print('{}:\t{}'.format(name, golang_version))


@cli.command("get-golang-versions", short_help="Get version of Go used for builds attached to an advisory")
@click.argument('advisory', type=int)
@pass_runtime
def get_golang_versions_cli(runtime, advisory):
    """
    Prints the Go version used to build a component to stdout.

    Usage:
\b
    $ elliott --group openshift-3.7 get-golang-versions ID
"""
    content_type = errata.get_erratum_content_type(advisory)
    if content_type == 'docker':
        get_container_golang_versions(advisory)
    else:
        get_rpm_golang_versions(advisory)
