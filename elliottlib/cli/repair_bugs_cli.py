import click
import elliottlib

from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
from elliottlib import Runtime
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from elliottlib.util import green_print, progress_func, pbar_header
from elliottlib.cli import cli_opts
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory, click_coroutine

pass_runtime = click.make_pass_decorator(Runtime)


@cli.command("repair-bugs", short_help="Move bugs attached to ADVISORY from one state to another")
@click.option("--advisory", "-a",
              type=int, metavar='ADVISORY',
              help="Repair bugs attached to ADVISORY.")
@click.option("--auto",
              required=False,
              default=False, is_flag=True,
              help="AUTO mode, check all bugs attached to ADVISORY")
@click.option("--id", default=None, metavar='BUGID',
              multiple=True, required=False,
              help="Bugzilla IDs to modify, conflicts with --auto [MULTIPLE]")
@click.option("--from", "original_state",
              multiple=True,
              default=['MODIFIED'],
              type=click.Choice(elliottlib.constants.VALID_BUG_STATES),
              help="Current state of the bugs (default: MODIFIED)")
@click.option("--to", "new_state",
              default='ON_QA',
              type=click.Choice(elliottlib.constants.VALID_BUG_STATES),
              help="Final state of the bugs (default: ON_QA)")
@click.option("--comment", "comment",
              required=False,
              help="Add comment to bug")
@click.option("--close-placeholder", "close_placeholder",
              required=False,
              default=False, is_flag=True,
              help="When checking bug state, close the bug if it's a placehoder bug.")
@click.option("--jira", 'use_jira',
              is_flag=True,
              default=False,
              help="Use jira in combination with bugzilla")
@click.option("--noop", "--dry-run",
              required=False,
              default=False, is_flag=True,
              help="Check bugs attached, print what would change, but don't change anything")
@use_default_advisory_option
@pass_runtime
def repair_bugs(runtime, advisory, auto, id, original_state, new_state, comment, close_placeholder, use_jira, noop, default_advisory_type):
    """Move bugs attached to the advisory from one state to another
state. This is useful if the bugs have changed states *after* they
were attached. Similar to `find-bugs` but in reverse. `repair-bugs`
begins by reading bugs from an advisory, whereas `find-bugs` reads
from bugzilla.

This looks at attached bugs in the provided --from state and moves
them to the provided --to state.

\b
    Background: This is intended for bugs which went to MODIFIED, were
    attached to advisories, set to ON_QA, and then failed
    testing. When this happens their state is reset back to ASSIGNED.

Using --use-default-advisory without a value set for the matching key
in the build-data will cause an error and elliott will exit in a
non-zero state. Most likely you will only want to use the `rpm` state,
but that could change in the future. Use of this option conflicts with
providing an advisory with the -a/--advisory option.

    Move bugs on 123456 FROM the MODIFIED state back TO ON_QA state:

\b
    $ elliott --group=openshift-4.1 repair-bugs --auto --advisory 123456 --from MODIFIED --to ON_QA

    As above, but using the default RPM advisory defined in ocp-build-data:

\b
    $ elliott --group=openshift-4.1 repair-bugs --auto --use-default-advisory rpm --from MODIFIED --to ON_QA

    The previous examples could also be ran like this (MODIFIED and ON_QA are both defaults):

\b
    $ elliott --group=openshift-4.1 repair-bugs --auto --use-default-advisory rpm

    Bug ids may be given manually instead of using --auto:

\b
    $ elliott --group=openshift-4.1 repair-bugs --id 170899 --id 8675309 --use-default-advisory rpm
"""
    if auto and len(id) > 0:
        raise click.BadParameter("Combining the automatic and manual bug modification options is not supported")

    if not auto and len(id) == 0:
        # No bugs were provided
        raise click.BadParameter("If not using --auto then one or more --id's must be provided")

    if advisory and default_advisory_type:
        raise click.BadParameter("Use only one of --use-default-advisory or --advisory")

    if len(id) == 0 and advisory is None and default_advisory_type is None:
        # error, no bugs, advisory, or default selected
        raise click.BadParameter("No input provided: Must use one of --id, --advisory, or --use-default-advisory")

    # Load bugzilla information and get a reference to the api
    runtime.initialize()
    if use_jira:
        jira_config = JIRABugTracker.get_config(runtime)
        bug_tracker = JIRABugTracker(jira_config)
    else:
        bz_config = BugzillaBugTracker.get_config(runtime)
        bug_tracker = BugzillaBugTracker(bz_config)
    changed_bug_count = 0

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    if auto:
        click.echo("Fetching Advisory(errata_id={})".format(advisory))
        e = elliottlib.errata.Advisory(errata_id=advisory)
        raw_bug_list = e.errata_bugs
    else:
        click.echo("Bypassed fetching erratum, using provided BZs")
        raw_bug_list = cli_opts.id_convert(id)

    green_print("Getting bugs for advisory")

    # Fetch bugs in parallel because it can be really slow doing it
    # one-by-one when you have hundreds of bugs
    pbar_header("Fetching data for {} bugs: ".format(len(raw_bug_list)),
                "Hold on a moment, we have to grab each one",
                raw_bug_list)
    pool = ThreadPool(cpu_count())
    click.secho("[", nl=False)

    attached_bugs = pool.map(
        lambda bug: progress_func(lambda: bug_tracker.get_bug(bug), '*'),
        raw_bug_list)
    # Wait for results
    pool.close()
    pool.join()
    click.echo(']')

    green_print("Got bugs for advisory")
    for bug in attached_bugs:
        if bug.status in original_state:
            if close_placeholder and "Placeholder" in bug.summary:
                bug_tracker.update_bug_status(bug, "CLOSED")
            else:
                bug_tracker.update_bug_status(bug, new_state)
                # only add comments for non-placeholder bug
                if comment and not noop:
                    bug_tracker.add_comment(bug, comment, private=False)
            changed_bug_count += 1

    green_print("{} bugs successfully modified (or would have been)".format(changed_bug_count))
