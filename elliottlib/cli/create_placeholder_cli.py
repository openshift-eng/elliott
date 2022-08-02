import elliottlib
from elliottlib import constants, logutil
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import exit_unauthenticated

from errata_tool import Erratum
from spnego.exceptions import GSSError
import click

LOGGER = logutil.getLogger(__name__)


@cli.command('create-placeholder',
             short_help='Create a placeholder BZ')
@click.option('--kind', '-k', metavar='KIND',
              required=False, type=click.Choice(
                  elliottlib.constants.standard_advisory_types),
              help='KIND [{}] of placeholder bug to create. Affects BZ title.'.format(
                  ', '.join(elliottlib.constants.standard_advisory_types)))
@click.option('--attach', '-a', 'advisory_id',
              type=int, metavar='ADVISORY',
              help='Attach the bug to ADVISORY')
@use_default_advisory_option
@click.option("--noop", "--dry-run",
              required=False,
              default=False, is_flag=True,
              help="Print what would change, but don't change anything")
@click.pass_obj
def create_placeholder_cli(runtime, kind, advisory_id, default_advisory_type, noop):
    """Create a placeholder bug for attaching to an advisory.

    KIND - The kind of placeholder to create ({}).
    ADVISORY - Optional. The advisory to attach the bug to.

    $ elliott --group openshift-4.1 create-placeholder --kind rpm --attach 12345
""".format('/'.join(elliottlib.constants.standard_advisory_types))
    if advisory_id and default_advisory_type:
        raise click.BadParameter("Use only one of --use-default-advisory or --advisory")

    runtime.initialize()
    if default_advisory_type is not None:
        advisory_id = find_default_advisory(runtime, default_advisory_type)
        kind = default_advisory_type

    if not kind:
        raise click.BadParameter("--kind must be specified when not using --use-default-advisory")

    bug_trackers = runtime.bug_trackers
    # we want to create one placeholder bug regardless of multiple bug trackers being used
    # we give priority to jira in case both are in use
    if runtime.use_jira or runtime.only_jira:
        create_placeholder(kind, advisory_id, bug_trackers['jira'], noop)
    else:
        create_placeholder(kind, advisory_id, bug_trackers['bugzilla'], noop)


def create_placeholder(kind, advisory_id, bug_tracker, noop):
    newbug = bug_tracker.create_placeholder(kind, noop)
    if noop:
        return

    click.echo(f"Created Bug: {newbug.id} {newbug.weburl}")

    if not advisory_id:
        return

    try:
        advisory = Erratum(errata_id=advisory_id)
    except GSSError:
        exit_unauthenticated()

    if advisory is False:
        raise ElliottFatalError(f"Error: Could not locate advisory {advisory_id}")

    click.echo("Attaching bug to advisory...")
    bug_tracker.attach_bugs(advisory_id, [newbug.id])
