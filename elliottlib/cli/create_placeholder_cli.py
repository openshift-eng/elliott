from __future__ import absolute_import, print_function, unicode_literals
import json

import elliottlib
from elliottlib import constants, logutil, Runtime
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import exit_unauthenticated, ensure_erratatool_auth
from elliottlib.util import green_prefix, green_print, parallel_results_with_progress, pbar_header

from errata_tool import Erratum, ErrataException
from kerberos import GSSError
import requests
import click

LOGGER = logutil.getLogger(__name__)

pass_runtime = click.make_pass_decorator(Runtime)

#
# Create Placeholder BZ
# bugzilla:create-placeholder
#


@cli.command('create-placeholder',
             short_help='Create a placeholder BZ')
@click.option('--kind', '-k', metavar='KIND',
              required=False, type=click.Choice(
                  elliottlib.constants.standard_advisory_types),
              help='KIND [{}] of placeholder bug to create. Affects BZ title.'.format(
                  ', '.join(elliottlib.constants.standard_advisory_types)))
@click.option('--attach', '-a', 'advisory',
              default=False, metavar='ADVISORY',
              help='Attach the bug to ADVISORY')
@use_default_advisory_option
@pass_runtime
def create_placeholder_cli(runtime, kind, advisory, default_advisory_type):
    """Create a placeholder bug for attaching to an advisory.

    KIND - The kind of placeholder to create ({}).
    ADVISORY - Optional. The advisory to attach the bug to.

    $ elliott --group openshift-4.1 create-placeholder --kind rpm --attach 12345
""".format('/'.join(elliottlib.constants.standard_advisory_types))

    runtime.initialize()
    if advisory and default_advisory_type:
        raise click.BadParameter(
            "Use only one of --use-default-advisory or --advisory")

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)
        kind = default_advisory_type

    if kind is None:
        raise click.BadParameter(
            "--kind must be specified when not using --use-default-advisory")

    bz_data = runtime.gitdata.load_data(key='bugzilla').data

    newbug = elliottlib.bzutil.create_placeholder(bz_data, kind)

    click.echo("Created BZ: {} {}".format(newbug.id, newbug.weburl))

    if advisory is not False:
        click.echo("Attaching to advisory...")

        try:
            advs = Erratum(errata_id=advisory)
        except GSSError:
            exit_unauthenticated()

        if advs is False:
            raise ElliottFatalError(
                "Error: Could not locate advisory {advs}".format(advs=advisory))

        try:
            green_prefix("Adding placeholder bug to advisory:")
            click.echo(" {advs}".format(advs=advisory))
            advs.addBugs([newbug.id])
            advs.commit()
        except ErrataException as ex:
            raise ElliottFatalError(getattr(ex, 'message', repr(ex)))
