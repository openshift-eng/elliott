import json
import click
from elliottlib import (Runtime, logutil)
from elliottlib.cli import common
from elliottlib.cli.find_bugs_sweep_cli import FindBugsSweep, print_report

logger = logutil.getLogger(__name__)


@common.cli.command("find-bugs:notv", short_help="Find qualified ART managed jira bugs (sweep) that do not have a "
                                                 "target version field set")
@click.option("--comment", "comment",
              required=False,
              help="Add comment to found bugs")
@click.option("--report",
              required=False,
              is_flag=True,
              help="Output a detailed report of found bugs")
@click.pass_obj
@common.click_coroutine
async def find_bugs_no_tv(runtime: Runtime, comment, report):
    """Find qualified ART managed jira bugs (sweep) that do not have a target version field set
    The group only determines which components are filtered out of the search
    (https://github.com/openshift/ocp-build-data/blob/openshift-4.12/bug.yml)
    Bugs are not restricted to a specific version.
    This is only intended to be used with --assembly=stream

    $ elliott -g openshift-4.12 find-bugs:notv --report

    $ elliott -g openshift-4.12 find-bugs:notv --comment "This bug has been found to have 'Target Version' field set
    to empty. ART automation strictly relies on it to attach bugs to advisories. Please set the Target Version to the
    release that you expect the fix to go in."

    """
    if runtime.assembly != 'stream':
        raise click.BadParameter("This command is intended to work only with --assembly=stream",
                                 param_hint='--assembly')

    runtime.initialize(mode="both")
    find_bugs_obj = FindBugsSweep()
    bug_tracker = runtime.bug_trackers('jira')
    bugs = find_bugs_obj.search(bug_tracker_obj=bug_tracker, verbose=runtime.debug,
                                with_target_release=False, custom_query=' AND "Target Version" is EMPTY AND '
                                                                        'component != "Release"')
    click.echo(f'Found {len(bugs)} bugs with status={find_bugs_obj.status} and no Target Version set')
    if report:
        print_report(bugs)
    else:
        click.echo([b.id for b in bugs])

    if comment:
        logger.info('Adding comment to bugs...')
        for bug in bugs:
            bug_tracker.add_comment(bug.id, comment, private=True)
