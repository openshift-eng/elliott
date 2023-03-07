import click
import sys
import traceback

from elliottlib.cli.find_bugs_sweep_cli import print_report, FindBugsMode
from elliottlib.bzutil import BugTracker
from elliottlib import (Runtime, constants)
from elliottlib.cli.common import cli
from elliottlib.util import green_prefix


class FindBugsBlocker(FindBugsMode):
    def __init__(self):
        super().__init__(
            status={'NEW', 'ASSIGNED', 'POST', 'MODIFIED', 'ON_DEV', 'ON_QA'},
            cve_only=False,
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
    find_bugs_obj = FindBugsBlocker()
    find_bugs_obj.include_status(include_status)
    find_bugs_obj.exclude_status(exclude_status)
    exit_code = 0
    for b in [runtime.bug_trackers('jira'), runtime.bug_trackers('bugzilla')]:
        try:
            find_bugs_blocker(runtime, output, find_bugs_obj, b)
        except Exception as e:
            runtime.logger.error(traceback.format_exc())
            runtime.logger.error(f'exception with {b.type} bug tracker: {e}')
            exit_code = 1
    sys.exit(exit_code)


def find_bugs_blocker(runtime, output, find_bugs_obj, bug_tracker):
    if output == 'text':
        statuses = sorted(find_bugs_obj.status)
        tr = bug_tracker.target_release()
        green_prefix(f"Searching {bug_tracker.type} for bugs with status {statuses} and target releases: {tr}\n")

    bugs = find_bugs_obj.search(bug_tracker_obj=bug_tracker, verbose=runtime.debug)

    if output == 'text':
        green_prefix(f"Found {len(bugs)} bugs: ")
        click.echo(", ".join(sorted(str(b.id) for b in bugs)))

    if bugs:
        print_report(bugs, output)
