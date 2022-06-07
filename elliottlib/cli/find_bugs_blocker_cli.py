import click

from elliottlib.cli.find_bugs_sweep_cli import print_report, FindBugsMode
from elliottlib.bzutil import BugzillaBugTracker, BugTracker, JIRABugTracker
from elliottlib import (Runtime, constants)
from elliottlib.cli.common import cli
from elliottlib.util import green_prefix


class FindBugsBlocker(FindBugsMode):
    def __init__(self):
        super().__init__(
            status={'NEW', 'ASSIGNED', 'POST', 'MODIFIED', 'ON_DEV', 'ON_QA'}
        )

    def search(self, bug_tracker_obj: BugTracker, verbose: bool = False):
        return bug_tracker_obj.blocker_search(
            self.status,
            verbose=verbose
        )


@cli.command("find-bugs:blocker", short_help="List active blocker bugs")
@click.option("--include-status", 'include_status',
              multiple=True,
              default=None,
              required=False,
              type=click.Choice(constants.VALID_BUG_STATES),
              help="Include bugs of this status")
@click.option("--exclude-status", 'exclude_status',
              multiple=True,
              default=None,
              required=False,
              type=click.Choice(constants.VALID_BUG_STATES),
              help="Exclude bugs of this status")
@click.option('--output', '-o',
              required=False,
              type=click.Choice(['text', 'json', 'slack']),
              default='text',
              help='Display format for output')
@click.pass_obj
def find_bugs_blocker_cli(runtime: Runtime, include_status, exclude_status, output):
    """
List active OCP blocker bugs for the target-releases.
default bug status to search: ['NEW', 'ASSIGNED', 'POST', 'MODIFIED', 'ON_DEV', 'ON_QA']
Use --exclude_status to filter out from default status list.

    Find blocker bugs for 4.6:
\b
    $ elliott -g openshift-4.6 find-bugs:blocker

    Output in json format:
\b
    $ elliott -g openshift-4.6 find-bugs:blocker --output json
"""
    runtime.initialize()
    if runtime.use_jira:
        find_bugs_blocker(runtime, output, include_status, exclude_status, JIRABugTracker(JIRABugTracker.get_config(runtime)))
    find_bugs_blocker(runtime, output, include_status, exclude_status, BugzillaBugTracker(
        BugzillaBugTracker.get_config(runtime)))


def find_bugs_blocker(runtime, output, include_status, exclude_status, bug_tracker):
    find_bugs_obj = FindBugsBlocker()
    find_bugs_obj.include_status(include_status)
    find_bugs_obj.exclude_status(exclude_status)

    if output == 'text':
        green_prefix(f"Searching for bugs with status {' '.join(sorted(find_bugs_obj.status))} and target release(s):")
        click.echo(" {tr}".format(tr=", ".join(bug_tracker.target_release())))

    bugs = find_bugs_obj.search(bug_tracker_obj=bug_tracker, verbose=runtime.debug)

    if output == 'text':
        green_prefix(f"Found {len(bugs)} bugs: ")
        click.echo(", ".join(sorted(str(b.id) for b in bugs)))

    if bugs:
        print_report(bugs, output)
