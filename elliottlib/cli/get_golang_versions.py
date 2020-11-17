from elliottlib import brew, errata, Runtime
from elliottlib.cli.common import cli
from elliottlib.exceptions import BrewBuildException
from elliottlib.util import get_golang_version_from_root_log

import click
pass_runtime = click.make_pass_decorator(Runtime)


@cli.command("get-golang-versions", short_help="Get version of Go used for builds attached to an advisory")
@click.argument('advisory', type=int)
@pass_runtime
def get_golang_versions_cli(runtime, advisory):
    """
    Only works for RPM builds.

    Usage:
\b
    $ elliott --group openshift-3.7 get-golang-versions ID
"""
    all_advisory_nvrs = errata.get_advisory_nvrs(advisory)

    click.echo("Found {} builds".format(len(all_advisory_nvrs)))
    for component, value in all_advisory_nvrs.items():
        version, release = value.rsplit('-', 1)
        try:
            root_log = brew.get_nvr_root_log(component, version, release)
        except BrewBuildException as e:
            print(e)
            continue
        golang_version = get_golang_version_from_root_log(root_log)
        print('{}-{}-{}: {}'.format(component, version, release, golang_version))
