import click
from elliottlib import logutil, errata
from elliottlib.cli import cli_opts
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from elliottlib.util import exit_unauthenticated
from elliottlib.util import green_prefix

from errata_tool import ErrataException
from spnego.exceptions import GSSError

LOGGER = logutil.getLogger(__name__)


@cli.command("remove-bugs", short_help="Remove provided BUGS from ADVISORY")
@click.option('--advisory', '-a', 'advisory_id',
              type=int, metavar='ADVISORY',
              help='Remove found bugs from ADVISORY')
@use_default_advisory_option
@click.argument('bug_ids', metavar='<BUGID>', nargs=-1, required=False, default=None)
@click.option("--all", "remove_all",
              required=False,
              default=False, is_flag=True,
              help="Remove all bugs attached to the Advisory")
@click.option("--noop", "--dry-run",
              is_flag=True,
              default=False,
              help="Don't change anything")
@click.pass_obj
def remove_bugs_cli(runtime, advisory_id, default_advisory_type, bug_ids, remove_all, noop):
    """Remove given BUGS from ADVISORY.

    Remove bugs that have been attached an advisory:

\b
    $ elliott --group openshift-4.10 remove-bugs 123456 --advisory 1234123

    Remove two bugs from default image advisory

\b
    $ elliott --group openshift-4.10 --assembly 4.10.19 remove-bugs 123456 3412311 --use-default-advisory image

    Remove all bugs from default image advisory

\b
    $ elliott --group openshift-4.10 --assembly 4.10.19 remove-bugs --all --use-default-advisory image

"""
    if bool(remove_all) == bool(bug_ids):
        raise click.BadParameter("Specify either <BUGID> or --all param")
    if bool(advisory_id) == bool(default_advisory_type):
        raise click.BadParameter("Specify exactly one of --use-default-advisory or advisory arg")

    runtime.initialize()
    if default_advisory_type is not None:
        advisory_id = find_default_advisory(runtime, default_advisory_type)

    if runtime.use_jira:
        bug_ids = cli_opts.id_convert_str(bug_ids)
        bug_tracker = JIRABugTracker(JIRABugTracker.get_config(runtime))
        remove_bugs(advisory_id, bug_ids, remove_all,
                    bug_tracker, noop)
    else:
        bug_ids = cli_opts.id_convert(bug_ids)
        bug_tracker = BugzillaBugTracker(BugzillaBugTracker.get_config(runtime))
        remove_bugs(advisory_id, bug_ids, remove_all,
                    bug_tracker, noop)


def remove_bugs(advisory_id, bug_ids, remove_all, bug_tracker, noop):
    try:
        advisory = errata.Advisory(errata_id=advisory_id)
    except GSSError:
        exit_unauthenticated()

    if not advisory:
        raise ElliottFatalError(f"Error: Could not locate advisory {advisory_id}")

    try:
        attached_bug_ids = bug_tracker.advisory_bug_ids(advisory)
        if not remove_all:
            bug_ids = [b for b in bug_ids if b in attached_bug_ids]
        else:
            bug_ids = attached_bug_ids
        green_prefix(f"Found {len(bug_ids)} bugs attached to advisory: ")
        click.echo(f"{bug_ids}")

        if not bug_ids:
            return

        green_prefix(f"Removing bugs from advisory {advisory_id}..")
        bug_tracker.remove_bugs(advisory, bug_ids, noop)
    except ErrataException as ex:
        raise ElliottFatalError(getattr(ex, 'message', repr(ex)))
