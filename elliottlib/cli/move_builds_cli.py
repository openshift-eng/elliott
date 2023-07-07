import sys
import click

from elliottlib import errata, logutil
from elliottlib.cli.common import cli
from elliottlib.util import ensure_erratatool_auth

LOGGER = logutil.getLogger(__name__)


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
    '--only', metavar='NVR',
    help='Only move these builds. Comma separated Build NVRs')
@click.option(
    "--noop", "--dry-run",
    is_flag=True, default=False,
    help="Don't change anything")
@click.pass_obj
def move_builds_cli(runtime, from_advisory, to_advisory, kind, only, noop):
    """
    Move attached builds from one advisory to another.
    Default is moving all attached builds. Specify builds using --only.

    $ elliott move-builds --from 123 --to 456 --kind image

    $ elliott move-builds --from 123 --to 456 -k image --only nvr1,nvr2
    """

    runtime.initialize(no_group=True)
    ensure_erratatool_auth()

    LOGGER.info(f'Fetching all builds from {from_advisory}')
    attached_builds = errata.get_brew_builds(from_advisory)
    build_nvrs = [b.nvr for b in attached_builds]

    if only:
        temp = only.split(',')
        LOGGER.info(f'Filtering to only specified builds ({len(temp)})')
        only_nvrs = []
        for n in temp:
            if n not in build_nvrs:
                LOGGER.warning(f"{n} not found attached to advisory {from_advisory}")
            else:
                only_nvrs.append(n)
        build_nvrs = only_nvrs
        attached_builds = [b for b in attached_builds if b.nvr in build_nvrs]

    if not build_nvrs:
        LOGGER.error("No eligible builds found")
        sys.exit(1)

    if noop:
        LOGGER.info(f"[DRY-RUN] Would've moved {len(build_nvrs)} builds from {from_advisory} to {to_advisory}")
        sys.exit(0)

    # remove builds
    from_erratum = errata.Advisory(errata_id=from_advisory)
    from_erratum.ensure_state('NEW_FILES')
    from_erratum.remove_builds(build_nvrs)
    # we do not attempt to move advisory to old state since without builds ET doesn't allow advisory to move to QE

    # add builds
    to_erratum = errata.Advisory(errata_id=to_advisory)
    old_state = to_erratum.errata_state
    to_erratum.ensure_state('NEW_FILES')
    to_erratum.attach_builds(attached_builds, kind)
    if old_state != 'NEW_FILES':
        to_erratum.ensure_state(old_state)
