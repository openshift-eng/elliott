import json
import click
from elliottlib import (Runtime, logutil)
from elliottlib.cli import common
from elliottlib.cli.common import click_coroutine

from elliottlib.cli.find_bugs_sweep_cli import FindBugsSweep


logger = logutil.getLogger(__name__)


@common.cli.command("find-bugs:notv", short_help="Find qualified bugs (sweep) that do not have a target version set")
@click.option("--comment", "comment",
              required=False,
              help="Add comment to found bugs")
@click.pass_obj
@click_coroutine
async def find_bugs_no_tv(runtime: Runtime, comment):
    runtime.initialize(mode="both")
    major_version, _ = runtime.get_major_minor()
    find_bugs_obj = FindBugsSweep()

    bug_tracker = runtime.bug_trackers('jira')
    bugs = find_bugs_obj.search(bug_tracker_obj=bug_tracker, verbose=runtime.debug,
                                with_target_release=False, custom_query=' AND "Target Version" is EMPTY AND '
                                                                        'component != "Release"')
    print([b.id for b in bugs])
    # comment = "This bug has been found to have no 'Target Version' field set.
    # ART automation strictly relies on it to attach bugs to advisories.
    # Please set the target version to the release that you expect the fix to go in."
    if comment:
        for bug in bugs:
            bug_tracker.add_comment(bug, comment, private=False)
