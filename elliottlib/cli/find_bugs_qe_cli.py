import click
import sys
import traceback

from elliottlib import (Runtime, logutil)
from elliottlib.cli.common import cli
from elliottlib.cli.find_bugs_sweep_cli import FindBugsMode
from elliottlib.util import green_prefix

LOGGER = logutil.getLogger(__name__)


class FindBugsQE(FindBugsMode):
    def __init__(self):
        super().__init__(
            status={'MODIFIED'}
        )


@cli.command("find-bugs:qe", short_help="Change MODIFIED bugs to ON_QA")
@click.option("--noop", "--dry-run",
              is_flag=True,
              default=False,
              help="Don't change anything")
@click.pass_obj
def find_bugs_qe_cli(runtime: Runtime, noop):
    """Find MODIFIED bugs for the target-releases, and set them to ON_QA.
    with a release comment on each bug

\b
    $ elliott -g openshift-4.6 find-bugs:qe

"""
    runtime.initialize()
    find_bugs_obj = FindBugsQE()
    exit_code = 0
    for b in [runtime.bug_trackers('jira'), runtime.bug_trackers('bugzilla')]:
        try:
            find_bugs_qe(runtime, find_bugs_obj, noop, b)
        except Exception as e:
            runtime.logger.error(traceback.format_exc())
            runtime.logger.error(f'exception with {b.type} bug tracker: {e}')
            exit_code = 1
    sys.exit(exit_code)


def find_bugs_qe(runtime, find_bugs_obj, noop, bug_tracker):
    major_version, minor_version = runtime.get_major_minor()
    statuses = sorted(find_bugs_obj.status)
    tr = bug_tracker.target_release()
    green_prefix(f"Searching {bug_tracker.type} for bugs with status {statuses} and target releases: {tr}\n")

    bugs = find_bugs_obj.search(bug_tracker_obj=bug_tracker, verbose=runtime.debug)
    click.echo(f"Found {len(bugs)} bugs: {', '.join(sorted(str(b.id) for b in bugs))}")

    release_comment = f"This bug is expected to ship in the next {major_version}.{minor_version} release."
    for bug in bugs:
        bug_tracker.update_bug_status(bug, 'ON_QA', comment=release_comment, noop=noop)
