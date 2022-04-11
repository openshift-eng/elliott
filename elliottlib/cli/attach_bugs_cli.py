import click
import sys

from elliottlib import Runtime, errata, logutil
from elliottlib.bzutil import BugzillaBugTracker, JIRABugTracker, Bug
from elliottlib.cli import cli_opts
from elliottlib.cli.common import cli, find_default_advisory, use_default_advisory_option
from elliottlib.cli.find_bugs_cli import print_report


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
@click.option("--jira", 'use_jira',
              is_flag=True,
              default=False,
              help="Use jira instead of bugzilla (https://issues.redhat.com/browse/ART-3818)")
@click.option("--noop", "--dry-run",
              is_flag=True,
              default=False,
              help="Don't change anything")
@click.pass_obj
def attach_bugs_cli(runtime: Runtime, advisory, default_advisory_type, bug_ids, report, output, use_jira, noop):
    """Attach OCP Bugs to ADVISORY
Print bug details with --report
For attaching use --advisory, --use-default-advisory <TYPE>

    Print bug report (no attach)

\b
    $ elliott -g openshift-4.10 attach-bugs 8675309 7001337 --report


    Print bug report for jira bugs (no attach)

\b
    $ elliott -g openshift-4.10 attach-bugs OCPBUGS-10 OCPBUGS-9 --report --jira


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

    version = f'{runtime.group_config.vars.MAJOR}.{runtime.group_config.vars.MINOR}'

    if use_jira:
        jira_config = JIRABugTracker.get_config(runtime)
        jira = JIRABugTracker(jira_config)
        bug_tracker = jira
    else:
        bz_config = BugzillaBugTracker.get_config(runtime)
        bugzilla = BugzillaBugTracker(bz_config)
        bug_tracker = bugzilla

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    # Check if target release and OCP version match
    bugs = bug_tracker.get_bugs(cli_opts.id_convert_str(bug_ids))
    target_release = Bug.get_target_release(bugs)

    if version not in target_release:
        LOGGER.error('Target release version for given bugs (%s) does not match the group (%s): aborting',
                     target_release, version)
        sys.exit(1)

    LOGGER.info(f"Found {len(bugs)} bugs: ")
    LOGGER.info(", ".join(sorted(str(b.id) for b in bugs)))
    if report:
        print_report(bugs, output=output)

    if advisory:
        errata.add_bugs_with_retry(advisory, bugs, noop=noop)
