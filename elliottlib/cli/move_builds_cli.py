import click
from errata_tool import ErrataException

import elliottlib
from elliottlib import Runtime, errata, logutil
from elliottlib.cli.common import cli
from elliottlib.util import (ensure_erratatool_auth, red_print)

LOGGER = logutil.getLogger(__name__)

pass_runtime = click.make_pass_decorator(Runtime)


@cli.command('move-builds', short_help='Move builds from one advisory to another')
@click.option(
    '--from', 'from_advisory', metavar='ADVISORY_ID',
    type=int, required=True,
    help='Source advisory to remove attached builds from')
@click.option(
    '--to', 'to_advisory', metavar='ADVISORY_ID',
    type=int, required=True,
    help='Target advisory to attach builds to')
@click.option(
    '--kind', '-k', metavar='KIND', required=True,
    type=click.Choice(['rpm', 'image']),
    help='Builds of the given KIND [rpm, image]')
@click.option(
    "--noop", "--dry-run",
    is_flag=True,
    default=False,
    help="Don't change anything")
@pass_runtime
def move_builds_cli(runtime: Runtime, from_advisory, to_advisory, kind, noop):
    """
    Move attached builds from one advisory to another

    $ elliott move-builds --from 123 --to 456 --kind image
    """

    ensure_erratatool_auth()

    attached_builds = errata.get_brew_builds(from_advisory)
    build_nvrs = [b.nvr for b in attached_builds]

    if noop:
        click.echo(f"[DRY-RUN] Would've removed {len(attached_builds)} builds from {from_advisory} and added to {to_advisory}")
        exit(0)

    # remove builds
    from_erratum = elliottlib.errata.Advisory(errata_id=from_advisory)
    old_state = from_erratum.errata_state
    from_erratum.ensure_state('NEW_FILES')
    from_erratum.remove_builds(build_nvrs)
    if old_state != 'NEW_FILES':
        from_erratum.ensure_state(old_state)

    # add builds
    to_erratum = elliottlib.errata.Advisory(errata_id=to_advisory)
    old_state = to_erratum.errata_state
    to_erratum.ensure_state('NEW_FILES')
    to_erratum.attach_builds(attached_builds, kind)
    if old_state != 'NEW_FILES':
        to_erratum.ensure_state(old_state)
