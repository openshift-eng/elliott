import click

from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from elliottlib import (Runtime, bzutil, logutil)
from elliottlib.cli.common import cli
from elliottlib.cli.find_bugs_cli import FindBugsMode

LOGGER = logutil.getLogger(__name__)


class FindBugsQE(FindBugsMode):
    def __init__(self):
        super().__init__(
            status={'MODIFIED'}
        )


@cli.command("find-bugs:qe", short_help="Find or add MODIFIED/VERIFIED bugs to ADVISORY")
@click.option("--jira", 'use_jira',
              is_flag=True,
              default=False,
              help="Use jira in combination with bugzilla (https://issues.redhat.com/browse/ART-3818)")
@click.option("--noop", "--dry-run",
              is_flag=True,
              default=False,
              help="Don't change anything")
@click.pass_obj
def find_bugs_qe_cli(runtime: Runtime, use_jira, noop):
    """Find MODIFIED bugs for the target-releases, and set them to ON_QA.

\b
    $ elliott -g openshift-4.6 find-bugs:qe

"""
    runtime.initialize()

    if use_jira:
        jira_config = JIRABugTracker.get_config(runtime)
        jira = JIRABugTracker(jira_config)
        bug_tracker = jira
    else:
        bz_config = BugzillaBugTracker.get_config(runtime)
        bugzilla = BugzillaBugTracker(bz_config)
        bug_tracker = bugzilla

    major_version, minor_version = runtime.get_major_minor()

    find_bugs_obj = FindBugsQE()
    click.echo(f"Searching for bugs with status {' '.join(find_bugs_obj.status)} and target release(s):"
               f" {', '.join(bug_tracker.target_release())}")

    bugs = find_bugs_obj.search(bug_tracker_obj=bug_tracker, verbose=runtime.debug)

    click.echo(f"Found {len(bugs)} bugs: {', '.join(sorted(str(b.id) for b in bugs))}")

    for bug in bugs:
        bzutil.set_state(bug, 'ON_QA', noop=noop, comment_for_release=f"{major_version}.{minor_version}")
