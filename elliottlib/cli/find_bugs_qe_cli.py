import click

from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker
from elliottlib import (Runtime, bzutil, logutil)
from elliottlib.cli.common import cli
from elliottlib.cli.find_bugs_sweep_cli import FindBugsMode

LOGGER = logutil.getLogger(__name__)


class FindBugsQE(FindBugsMode):
    def __init__(self):
        super().__init__(
            status={'MODIFIED'}
        )


@cli.command("find-bugs:qe", short_help="Change MODIFIED bugs to ON_QA")
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
    with a release comment on each bug

\b
    $ elliott -g openshift-4.6 find-bugs:qe

"""
    runtime.initialize()

    if use_jira:
        jira_config = JIRABugTracker.get_config(runtime)
        bug_tracker = JIRABugTracker(jira_config)
    else:
        bz_config = BugzillaBugTracker.get_config(runtime)
        bug_tracker = BugzillaBugTracker(bz_config)

    major_version, minor_version = runtime.get_major_minor()
    click.echo(f"Searching for bugs with status MODIFIED and target release(s): {', '.join(bug_tracker.target_release())}")

    bugs = FindBugsQE().search(bug_tracker_obj=bug_tracker, verbose=runtime.debug)
    click.echo(f"Found {len(bugs)} bugs: {', '.join(sorted(str(b.id) for b in bugs))}")

    release_comment = f"This bug is expected to ship in the next {major_version}.{minor_version} release."
    for bug in bugs:
        bug_tracker.update_bug_status(bug, 'ON_QA', comment=release_comment, noop=noop)
