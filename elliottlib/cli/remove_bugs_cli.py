import click
import requests

import elliottlib
from elliottlib import constants, logutil, Runtime, errata
from elliottlib.cli import cli_opts
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from elliottlib.util import exit_unauthenticated, ensure_erratatool_auth
from elliottlib.util import green_prefix, green_print, parallel_results_with_progress, pbar_header

from errata_tool import Erratum, ErrataException
from spnego.exceptions import GSSError


LOGGER = logutil.getLogger(__name__)

pass_runtime = click.make_pass_decorator(Runtime)


# -----------------------------------------------------------------------------
# CLI Commands - Please keep these in alphabetical order
# -----------------------------------------------------------------------------
#
#
# Remove bugs
#
@cli.command("remove-bugs", short_help="Remove provided BUGS from ADVISORY")
@click.option('--advisory', '-a', 'advisory',
              type=int, metavar='ADVISORY',
              help='Remove found bugs from ADVISORY')
@click.option("--id", metavar='BUGID', default=[],
              multiple=True, required=False,
              help="Bugzilla IDs to remove from advisory.")
@click.option("--issue", metavar='JIRAID', default=[],
              multiple=True, required=False,
              help="JIRA IDs to remove from advisory.")
@click.option("--all", "remove_all",
              required=False,
              default=False, is_flag=True,
              help="Remove all bugs attached to Advisory")
@pass_runtime
@use_default_advisory_option
def remove_bugs_cli(runtime, advisory, default_advisory_type, id, issue, remove_all):
    """Remove given BUGS from ADVISORY.

    Remove bugs that have been attached an advisory:

\b
    $ elliott --group openshift-3.7 remove-bugs --id 123456 --advisory 1234123

    Remove two bugs from default rpm advisory. Note that --group is required
    because default advisory is from ocp-build-data:

\b
    $ elliott --group openshift-3.7 remove-bugs --id 123456 --id 3412311 --use-default-advisory rpm


"""
    if remove_all and (id or issue):
        raise click.BadParameter("Combining the automatic and manual bug modification options is not supported")
    if not remove_all and not id and not issue:
        raise click.BadParameter("If not using --all then one or more --id's must be provided")
    if bool(advisory) == bool(default_advisory_type):
        raise click.BadParameter("Specify exactly one of --use-default-advisory or advisory arg")

    runtime.initialize()

    jira_config = JIRABugTracker.get_config(runtime)
    jira_tracker = JIRABugTracker(jira_config)
    bz_config = BugzillaBugTracker.get_config(runtime)
    bugzilla_tracker = BugzillaBugTracker(bz_config)

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    if advisory:
        try:
            advs = errata.Advisory(errata_id=advisory)
        except GSSError:
            exit_unauthenticated()

        if advs is False:
            raise ElliottFatalError("Error: Could not locate advisory {advs}".format(advs=advisory))

        try:
            if remove_all:
                bugzilla_bug_ids = advs.errata_bugs
                jira_bug_ids = [issue.key for issue in errata.get_jira_issue(advisory)]
            else:
                bugzilla_bug_ids = [bugzilla_tracker.get_bug(i).id for i in cli_opts.id_convert(id)]
                jira_bug_ids = [jira_tracker.get_bug(i).id for i in cli_opts.id_convert(issue)]
            green_prefix("Found {} bugzilla bugs:".format(len(bugzilla_bug_ids)))
            click.echo(" {}".format(", ".join([str(b) for b in bugzilla_bug_ids])))
            green_prefix("Found {} jira bugs:".format(len(jira_bug_ids)))
            click.echo(" {}".format(", ".join([str(b) for b in jira_bug_ids])))

            green_prefix("Removing {count} bugzilla bugs and {number} jira bugs from advisory:".format(count=len(bugzilla_bug_ids), number=len(jira_bug_ids)))
            click.echo(" {advs}".format(advs=advisory))
            if bugzilla_bug_ids:
                advs.removeBugs([bug for bug in bugzilla_bug_ids])
                advs.commit()
            if jira_bug_ids:
                errata.remove_multi_jira_issues(advisory, jira_bug_ids)
        except ErrataException as ex:
            raise ElliottFatalError(getattr(ex, 'message', repr(ex)))
