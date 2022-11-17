import click

from elliottlib import Runtime, logutil
from elliottlib.bzutil import Bug, get_jira_bz_bug_ids
from elliottlib.cli.common import cli, find_default_advisory, use_default_advisory_option
from elliottlib.cli.find_bugs_sweep_cli import print_report


LOGGER = logutil.getLogger(__name__)


@cli.command("attach-bugs", short_help="List and (optional) add bugs to ADVISORY")
@click.argument('bug_ids', metavar='<BUGID>', nargs=-1, required=True, default=None)
@click.option("--report",
              required=False,
              is_flag=True,
              help="Output a detailed report of bugs")
@click.option('--output', '-o',
              required=False,
              type=click.Choice(['text', 'json', 'slack']),
              default='text',
              help='Applies chosen format to --report output')
@click.option("--advisory", "-a", 'advisory',
              type=int, metavar='ADVISORYID',
              help="Attach bugs to ADVISORY")
@use_default_advisory_option
@click.option("--noop", "--dry-run",
              is_flag=True,
              default=False,
              help="Don't change anything")
@click.pass_obj
def attach_bugs_cli(runtime: Runtime, advisory, default_advisory_type, bug_ids, report, output, noop):
    """Attach Openshift Bugs (JIRA or Bugzilla) to ADVISORY
Print bug details with --report
For attaching use --advisory or --use-default-advisory <TYPE>

    Print bug report (no attach)

\b
    $ elliott -g openshift-4.10 attach-bugs OCPBUGS-1 8675309 7001337 --report


    Attach bugs to the advisory 123456

\b
    $ elliott -g openshift-4.10 attach-bugs 8675309 7001337 --advisory 123456


    Attach bugs to the 4.10.2 assembly defined image advisory

\b
    $ elliott -g openshift-4.10 --assembly 4.10.2 attach-bugs 8675309 7001337 --use-default-advisory image

"""
    if advisory and default_advisory_type:
        raise click.BadParameter("Use only one of --use-default-advisory <TYPE> or --advisory <ADVISORY_ID>")

    runtime.initialize()
    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    jira_ids, bz_ids = get_jira_bz_bug_ids(bug_ids)
    if jira_ids:
        attach_bugs(runtime, advisory, jira_ids, report, output, noop, runtime.bug_trackers('jira'))
    if bz_ids:
        attach_bugs(runtime, advisory, bz_ids, report, output, noop, runtime.bug_trackers('bugzilla'))


def attach_bugs(runtime, advisory, bug_ids, report, output, noop, bug_tracker):
    major, minor = runtime.get_major_minor()
    version = f'{major}.{minor}'
    bugs = bug_tracker.get_bugs(bug_ids, verbose=runtime.debug)

    # Check if target release and OCP version match
    target_release = Bug.get_target_release(bugs)
    if version not in target_release:
        raise ValueError('Target release version for given bugs (%s) does not match the group (%s): aborting',
                         target_release, version)

    LOGGER.info(f"Found {len(bugs)} bugs: {', '.join(sorted(str(b.id) for b in bugs))}")
    if report:
        print_report(bugs, output=output)

    if advisory:
        bug_tracker.attach_bugs([b.id for b in bugs], advisory_id=advisory, noop=noop)
