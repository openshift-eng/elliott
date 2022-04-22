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
              help="Bug IDs to remove from advisory.")
@click.option("--all", "remove_all",
              required=False,
              default=False, is_flag=True,
              help="Remove all bugs attached to Advisory")
@click.option("--jira", 'use_jira',
              is_flag=True,
              default=False,
              help="Use jira instead of bugzilla")
@pass_runtime
@use_default_advisory_option
def remove_bugs_cli(runtime, advisory, default_advisory_type, id, remove_all, use_jira):
    """Remove given BUGS from ADVISORY.

    Remove bugs that have been attached an advisory:

\b
    $ elliott --group openshift-3.7 remove-bugs --id 123456 --advisory 1234123

    Remove two bugs from default rpm advisory. Note that --group is required
    because default advisory is from ocp-build-data:

\b
    $ elliott --group openshift-3.7 remove-bugs --id 123456 --id 3412311 --use-default-advisory rpm


"""
    if remove_all and id:
        raise click.BadParameter("Combining the automatic and manual bug modification options is not supported")
    if not remove_all and not id:
        raise click.BadParameter("If not using --all then one or more --id's must be provided")
    if bool(advisory) == bool(default_advisory_type):
        raise click.BadParameter("Specify exactly one of --use-default-advisory or advisory arg")

    runtime.initialize()

    if use_jira:
        jira_config = JIRABugTracker.get_config(runtime)
        bug_tracker = JIRABugTracker(jira_config)
    else:
        bz_config = BugzillaBugTracker.get_config(runtime)
        bug_tracker = BugzillaBugTracker(bz_config)

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
                if use_jira:
                    # TODO: this will soon become advs.jira_issues
                    bug_ids = [issue.key for issue in errata.get_jira_issue(advisory)]
                else:
                    bug_ids = advs.errata_bugs
            else:
                bug_ids = [bug_tracker.get_bug(i).id for i in cli_opts.id_convert(id)]
            green_prefix(f"Found {len(bug_ids)} bugs:")
            click.echo(f" {', '.join([str(b) for b in bug_ids])}")
            green_prefix(f"Removing bugs from advisory {advisory}:")
            if bug_ids:
                if use_jira:
                    errata.remove_multi_jira_issues(advisory, bug_ids)
                else:
                    advs.removeBugs([bug for bug in bug_ids])
                    advs.commit()
        except ErrataException as ex:
            raise ElliottFatalError(getattr(ex, 'message', repr(ex)))
