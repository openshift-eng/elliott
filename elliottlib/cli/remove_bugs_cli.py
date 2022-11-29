import click
from elliottlib import logutil, errata
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import exit_unauthenticated
from elliottlib.util import green_prefix
from elliottlib.bzutil import get_jira_bz_bug_ids, JIRABugTracker, BugzillaBugTracker

from errata_tool import ErrataException

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
    """Remove given BUGS (JIRA or Bugzilla) from ADVISORY.

    Remove bugs that have been attached an advisory:

\b
    $ elliott --group openshift-4.10 remove-bugs OCPBUGS-4 123456 --advisory 1234123

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

    advisory = errata.Advisory(errata_id=advisory_id)
    if not advisory:
        raise ElliottFatalError(f"Error: Could not locate advisory {advisory_id}")
    attached_jira_ids = JIRABugTracker.advisory_bug_ids(advisory)
    attached_bz_ids = BugzillaBugTracker.advisory_bug_ids(advisory)

    if remove_all:
        jira_ids, bz_ids = attached_jira_ids, attached_bz_ids
    else:
        jira_ids, bz_ids = get_jira_bz_bug_ids(bug_ids)
        jira_ids = set(jira_ids) & set(attached_jira_ids)
        bz_ids = set(bz_ids) & set(attached_bz_ids)

    if jira_ids:
        remove_bugs(advisory, jira_ids, runtime.bug_trackers('jira'), noop)
    if bz_ids:
        remove_bugs(advisory, bz_ids, runtime.bug_trackers('bugzilla'), noop)


def remove_bugs(advisory, bug_ids, bug_tracker, noop):
    green_prefix(f"Found {len(bug_ids)} {bug_tracker.type} bugs attached to advisory: ")
    click.echo(f"{bug_ids}")

    green_prefix(f"Removing {bug_tracker.type} bugs from advisory {advisory.errata_id}..")
    try:
        bug_tracker.remove_bugs(advisory, bug_ids, noop)
    except ErrataException as ex:
        raise ElliottFatalError(getattr(ex, 'message', repr(ex)))
