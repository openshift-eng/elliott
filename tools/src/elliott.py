#!/bin/env python
"""
Elliott is a CLI tool for managing Red Hat release advisories using the Erratatool
web service.
"""

# -----------------------------------------------------------------------------
# Module dependencies
# -----------------------------------------------------------------------------

# Prepare for Python 3
# stdlib
from __future__ import print_function
import datetime
import os

# ours
from ocp_cd_tools import Runtime
import ocp_cd_tools.constants
import ocp_cd_tools.bugzilla
import ocp_cd_tools.brew

# 3rd party
import click

# -----------------------------------------------------------------------------
# Constants and defaults
# -----------------------------------------------------------------------------
release_date = datetime.datetime.now() + datetime.timedelta(days=21)

pass_runtime = click.make_pass_decorator(Runtime)
context_settings = dict(help_option_names=['-h', '--help'])


@click.group(context_settings=context_settings)
@click.option("--metadata-dir", metavar='PATH', default=os.getcwd(),
              help="Directory containing groups metadata directory if not current.")
@click.option("--working-dir", metavar='PATH', default=None,
              help="Existing directory in which file operations should be performed.")
@click.option("--user", metavar='USERNAME', default=None,
              help="Username for rhpkg.")
@click.option("--group", default=None, metavar='NAME',
              help="The group of images on which to operate.")
@click.option("--branch", default=None, metavar='BRANCH',
              help="Branch to override any default in group.yml.")
@click.option('--stage', default=False, is_flag=True, help='Force checkout stage branch for sources in group.yml.')
@click.option("-i", "--images", default=[], metavar='NAME', multiple=True,
              help="Name of group image member to include in operation (all by default). Can be comma delimited list.")
@click.option("-r", "--rpms", default=[], metavar='NAME', multiple=True,
              help="Name of group rpm member to include in operation (all by default). Can be comma delimited list.")
@click.option("-x", "--exclude", default=[], metavar='NAME', multiple=True,
              help="Name of group image or rpm member to exclude in operation (none by default). Can be comma delimited list.")
@click.option('--ignore-missing-base', default=False, is_flag=True, help='If a base image is not included, proceed and do not update FROM.')
@click.option("--quiet", "-q", default=False, is_flag=True, help="Suppress non-critical output")
@click.option('--verbose', '-v', default=False, is_flag=True, help='Enables verbose mode.')
@click.option('--no_oit_comment', default=False, is_flag=True,
              help='Do not place OIT comment in Dockerfile. Can also be set in each config yaml')
@click.option("--source", metavar="ALIAS PATH", nargs=2, multiple=True,
              help="Associate a path with a given source alias.  [multiple]")
@click.option("--sources", metavar="YAML_PATH",
              help="YAML dict associating sources with their alias. Same as using --source multiple times.")
@click.pass_context
def cli(ctx, **kwargs):
    # @pass_runtime
    ctx.obj = Runtime(**kwargs)


# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------
def validate_release_date(ctx, param, value):
    """Ensures dates are provided in the correct format"""
    try:
        datetime.datetime.strptime(value, '%Y-%m-%d')
        return value
    except ValueError:
        raise click.BadParameter('Release date (--date) must be in YYYY-MM-DD format')

def minor_from_branch(ver):
    """Parse the minor version from the provided version (or 'branch').

For example, if --group=openshift-3.9 then runtime.group_config.branch
will have the value rhaos-3.9-rhel-7. When passed to this function the
return value would be the number 9, where in considering '3.9' then
'9' is the MINOR version.

I.e., this gives you the Y component if 3.9 => X.Y.

This behavior is HIGHLY dependant on the format of the input
argument. Hence, why this function indicates the results are based on
the 'branch' variable. Arbitrary input will fail. Use of this implies
you read the docs.
    """
    return ver.split('-')[1].split('.')[1]

# -----------------------------------------------------------------------------
# CLI Commands - Please keep these in alphabetical order
# -----------------------------------------------------------------------------


#
# Set advisory state
# advisory:state
#
@cli.command("advisory:change-state", short_help="Change ADVISORY state")
@click.option("--state", '-s', type=click.Choice(['NEW_FILES', 'QE', 'REL_PREP']),
              help="New state for the Advisory. NEW_FILES, QE, REL_PREP.")
@click.argument('advisory', type=int)
@click.pass_context
def change_state(runtime, state, advisory):
    """Change the state of ADVISORY. Additional permissions may be
required to change an advisory to certain states.

An advisory may not move between some states until all criteria have
been met. For example, an advisory can not move from NEW_FILES to QE
unless Bugzilla Bugs or JIRA Issues have been attached.

See the advisory:find-bugs help for additional information on adding
Bugzilla Bugs.

    Move the advisory 123456 from NEW_FILES to QE state:

    $ elliott advisory:change-state --state QE 123456

    Move the advisory 123456 back to NEW_FILES (short option flag):

    $ elliott advisory:change-state -s NEW_FILES 123456
    """
    erratum = ocp_cd_tools.errata.get_erratum(advisory)
    click.echo("Changing state for {id} to {state}".format(id=advisory, state=state))
    click.echo(erratum)
    erratum.change_state(state)
    click.echo("Ran change state")
    click.echo(erratum)


#
# Create Advisory (RPM and image)
# advisory:create
#
@cli.command("advisory:create", short_help="Create a new advisory")
@click.option("--kind", '-k', default='rpm',
              type=click.Choice(['rpm', 'image']),
              help="Kind of Advisory to create. Affects boilerplate text.")
@click.option("--date", required=False,
              default=release_date.strftime('%Y-%m-%d'),
              callback=validate_release_date,
              help="Release date for the advisory. Optional. Format: YYYY-MM-DD. Defaults to NOW + 3 weeks")
@click.option('--yes', '-y', is_flag=True,
              default=False, type=bool,
              help="Create the advisory (by default only a preview is displayed)")
@pass_runtime
def create(runtime, kind, date, yes):
    """Create a new advisory. By default an RPM Advisory is created. You
may also create an Image Update Advisory.

    You MUST specify a group (ex: "openshift-3.9") manually using the
    --group option. See examples below.

New advisories will be created with a Release Date set to 3 weeks (21
days) from now. You may customize this (especially if that happens to
fall on a weekend) by providing a YYYY-MM-DD formatted string to the
--date option.

The default behavior for this command is to show what the generated
advisory would look like. The raw JSON used to create the advisory
will be printed to the screen instead of posted to the Errata Tool
API.

Provide the '--yes' or '-y' option to confirm creation of the
advisory.

    PREVIEW an RPM Advisory 21 days from now (the default release date) for OSE 3.9:

    $ elliott --group openshift-3.9 advisory:create

    CREATE Image Advisory for the 3.5 series on the first Monday in March:

\b
    $ elliott --group openshift-3.5 advisory:create --yes -k image --date 2018-03-05
    """
    runtime.initialize(clone_distgits=False)
    minor = minor_from_branch(runtime.group_config.branch)
    erratum = ocp_cd_tools.errata.new_erratum(kind=kind, release_date=date, create=yes, minor=minor)
    click.echo(erratum)


#
# Collect bugs
# advisory:find-bugs
#
@cli.command("advisory:find-bugs", short_help="Find or add MODIFED bugs to ADVISORY")
@click.argument('advisory', type=int)
@click.option("--add", "-a",
              default=False, is_flag=True,
              help="Add found bugs to ADVISORY. Applies to bug flags as well. (by default only a list of discovered bugs are displayed)")
@click.option("--auto",
              required=False,
              default=False, is_flag=True,
              help="AUTO mode, adds bugs based on --group")
@click.option("--id", type=int, metavar='BUGID',
              multiple=True, required=False,
              help="Bugzilla IDs to add, conflicts with --auto [MULTIPLE]")
@click.option("--flag", metavar='FLAG',
              required=False, multiple=True,
              help="Optional flag to apply to found bugs [MULTIPLE]")
@pass_runtime
def find_bugs(runtime, add, auto, id, flag, advisory):
    """Find Red Hat Bugzilla bugs or add them to ADVISORY. Bugs can be
"swept" into the advisory either automatically (--auto), or by
manually specifying one or more bugs using the --id option. Mixing
--auto with --id is an invalid use-case. The two use cases are
described below:

    Note: Using --id without --add is basically pointless

AUTOMATIC: For this use-case the --group option MUST be provided. The
--group automatically determines the correct target-releases to search
for MODIFIED bugs in.

MANUAL: The --group option is not required if you are specifying bugs
manually. Provide one or more --id's for manual bug addition.

    Automatically add bugs with target-release matching 3.7.Z or 3.7.0
    to advisory 123456:

\b
    $ elliott --group openshift-3.7 advisory:find-bugs --auto --add 123456

    List bugs that would be added to advisory 123456 and set the bro_ok flag on the bugs (NOOP):

\b
    $ elliott --group openshift-3.7 advisory:find-bugs --auto --flag bro_ok 123456

    Add two bugs to advisory 123456. Note that --group is not
    required because we're not auto searching:

\b
    $ elliott advisory:find-bugs --id 8675309 --id 7001337 --add 123456
    """
    if auto and len(id) > 0:
        click.echo("Mixing automatic (--auto, default) bug attachment and manual (--id) options is not supported")
        exit(1)

    if auto:
        # Initialization ensures a valid group was provided
        runtime.initialize(clone_distgits=False)
        # Parse the Y component from the group version
        minor = minor_from_branch(runtime.group_config.branch)
        target_releases = ["3.{y}.Z".format(y=minor), "3.{y}.0".format(y=minor)]
        click.echo("Adding bugs to {advs} for target releases: {tr}".format(advs=advisory, tr=", ".join(target_releases)))
    elif len(id) == 0:
        # No bugs were provided
        click.echo("Error: If not using --auto then one or more --id's must be provided")
        exit(1)

    # Fetch the advisory to ensure it exists
    advs = ocp_cd_tools.errata.get_erratum(advisory)
    if advs is False:
        click.echo("Error: Could not locate advisory {advs}".format(advs=advisory))
        exit(1)

    if auto:
        bug_ids = ocp_cd_tools.bugzilla.search_for_bugs(target_releases)
    else:
        bug_ids = [ocp_cd_tools.bugzilla.Bug(id=i) for i in id]

    bug_count = len(bug_ids)

    if add:
        if len(flag) > 0:
            for bug in bug_ids:
                bug.add_flags(flag)

        advs.add_bugs(bug_ids)
    else:
        click.echo("Would have added {n} bugs: {bugs}".format(n=bug_count, bugs=", ".join([str(b) for b in bug_ids])))


#
# Attach Builds
# advisory:find-builds
#
@cli.command('advisory:find-builds',
             short_help='Find or attach builds to ADVISORY')
@click.option('--attach', '-a', is_flag=True,
              default=False, type=bool,
              help='Attach the builds (by default only a list of builds are displayed)')
@click.option('--build', '-b', metavar='NVR_OR_ID',
              multiple=True,
              help='Add build NVR_OR_ID to ADVISORY [MULTIPLE]')
@click.option('--kind', '-k', metavar='KIND',
              required=True, type=click.Choice(['rpm', 'image']),
              help='Find builds of the given KIND [rpm, image]')
@click.argument('advisory', type=int)
@pass_runtime
def find_builds(runtime, attach, build, kind, advisory):
    """Automatically or manually find or attach viable rpm or image builds
to ADVISORY. Default behavior searches Brew for viable builds in the
given group. Provide builds manually by giving one or more --build
(-b) options. Manually provided builds are verified against the Errata
Tool API.

  * Attach the builds to ADVISORY by giving --attach

Example: Assuming --group=openshift-3.7, then a build is a VIABLE
BUILD IFF it meets ALL of the following criteria:

\b
  * HAS the tag in brew: rhaos-3.7-rhel7-candidate
  * DOES NOT have the tag in brew: rhaos-3.7-rhel7
  * IS NOT attached to ANY existing RHBA, RHSA, or RHEA

That is to say, a viable build is tagged as a "candidate", has NOT
received the "shipped" tag yet, and is NOT attached to any PAST or
PRESENT advisory. Here are some examples:

    SHOW the latest OSE 3.6 image builds that would be attached to
    advisory 123456:

    $ elliott --group openshift-3.6 advisory:find-builds -k image 123456

    ATTACH the latest OSE 3.6 rpm builds to advisory 123456:

\b
    $ elliott --group openshift-3.6 advisory:find-builds -k rpm --attach 123456

    VERIFY (no --attach) that the manually provided NVR and build ID
    are viable builds:

\b
    $ elliott --group openshift-3.6 advisory:find-builds 123456 -k rpm -b megafrobber-1.0.1-2.el7 -b 93170"""
    runtime.initialize(clone_distgits=False)
    minor = minor_from_branch(runtime.group_config.branch)
    product_version = 'RHEL-7-OSE-3.{Y}'.format(Y=minor)
    base_tag = "rhaos-3.{minor}-rhel-7".format(minor=minor)

    if len(build) > 0:
        click.echo("Using provided build NVR list, verifying builds exist")
        try:
            unshipped_builds = [ocp_cd_tools.brew.get_brew_build(b, product_version) for b in build]
        except ocp_cd_tools.brew.BrewBuildException as e:
            click.secho("Error locating all builds", fg='red', bold=True)
            click.echo(e)
            exit(1)
    else:
        click.echo("Hold on a moment, searching Brew for build candidates")
        unshipped_builds = ocp_cd_tools.brew.find_unshipped_builds(runtime, base_tag, product_version, kind=kind)

    build_count = len(unshipped_builds)

    if attach:
        erratum = ocp_cd_tools.errata.get_erratum(advisory)
        try:
            erratum.add_builds(unshipped_builds)
            click.secho("Attached build(s) successfully", fg='green', bold=True)
        except ocp_cd_tools.brew.BrewBuildException as e:
            click.secho("Error attaching builds:", fg='red', bold=True)
            click.echo(str(e))
    else:
        click.echo("The following {n} builds ".format(n=build_count), nl=False)
        click.secho("may be attached ", bold=True, nl=False)
        click.echo("to an advisory:")
        for b in sorted(unshipped_builds):
            click.echo(" " + str(b.to_json()))


#
# Get an Advisory
# advisory:get
#
@cli.command("advisory:get", short_help="Get the ADVISORY")
@click.argument('advisory', type=int)
@click.option('--json', is_flag=True, default=False,
              help="Print the full JSON object of the advisory")
@click.pass_context
def get(runtime, json, advisory):
    """Get details about a specific advisory from the Errata Tool. By
default a brief one-line informational string is printed. Use the
--json option to fetch and print the full details of the advisory.

Fields for the short format: Release date, State, Synopsys, URL

    Basic one-line output for advisory 123456:

\b
    $ elliott advisory:get 123456
    2018-02-23T18:34:40 NEW_FILES OpenShift Container Platform 3.9 bug fix and enhancement update - https://errata.devel.redhat.com/advisory/123456

    Get the full JSON advisory object, use `jq` to print just the
    errata portion of the advisory:

\b
    $ elliott advisory:get --json 123456 | jq '.errata'
    {
      "rhba": {
        "actual_ship_date": null,
        "assigned_to_id": 3002255,
        "batch_id": null,
        ...
"""
    advisory = ocp_cd_tools.errata.get_erratum(advisory)
    if json:
        click.echo(advisory.to_json())
    else:
        click.echo(advisory)


#
# List Advisories (RPM and image)
# advisory:list
#
@cli.command("advisory:list", short_help="List filtered RHOSE advisories")
@click.option("--filter-id", '-f',
              default=ocp_cd_tools.constants.errata_default_filter,
              help="A custom filter id to list from")
@click.option("-n", default=5,
              help="Return only N latest results (default: 5)")
@click.pass_context
def list(runtime, filter_id, n):
    """Print a list of one-line informational strings of RHOSE
advisories. By default the 5 most recently created advisories are
printed. Note, they are NOT sorted by release date.

    NOTE: new filters must be created in the Errata Tool web
    interface.

Default filter definition: RHBA; Active; Product: RHOSE; Devel Group:
ENG OpenShift Enterprise; sorted by newest. Browse this filter
yourself online: https://errata.devel.redhat.com/filter/1965

    List 10 advisories instead of the default 5 with your custom
    filter #1337:

    $ elliott advisory:list -n 10 -f 1337
"""
    try:
        for erratum in ocp_cd_tools.errata.get_filtered_list(filter_id, limit=n):
            click.echo(erratum)
    except ValueError:
        click.echo("No filter matched #{fn}".format(fn=filter_id))

#
# Generate a puddle for image builds (unsigned, signed)
# rpmrepo:create
#


# -----------------------------------------------------------------------------
# CLI Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Invoke the Click CLI wrapper function
    cli(obj={})
