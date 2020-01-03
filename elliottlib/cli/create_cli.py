from __future__ import absolute_import, print_function, unicode_literals
import click
import datetime
from kerberos import GSSError
import elliottlib
from elliottlib.cli.common import cli
from elliottlib.cli.add_metadata_cli import add_metadata_cli
from elliottlib.cli.create_placeholder_cli import create_placeholder_cli
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import YMD, default_release_date, validate_release_date, \
    validate_email_address, major_from_branch, minor_from_branch, \
    exit_unauthenticated, exit_unauthorized, red_prefix, green_prefix, yellow_prefix, \
    red_print, yellow_print, green_print
pass_runtime = click.make_pass_decorator(elliottlib.Runtime)

LOGGER = elliottlib.logutil.getLogger(__name__)


#
# Create Advisory (RPM and image)
# advisory:create
#
@cli.command("create", short_help="Create a new advisory")
@click.option("--type", '-t', 'errata_type',
              type=click.Choice(['RHBA', 'RHSA', 'RHEA']),
              default='RHBA',
              help="Type of Advisory to create.")
@click.option("--kind", '-k', required=True,
              type=click.Choice(['rpm', 'image']),
              help="Kind of artifacts that will be attached to Advisory. Affects boilerplate text.")
@click.option("--impetus",
              type=click.Choice(elliottlib.constants.errata_valid_impetus),
              help="Impetus for the advisory creation [{}]".format(
                  ', '.join(elliottlib.constants.errata_valid_impetus)))
@click.option("--date", required=True,
              callback=validate_release_date,
              help="Release date for the advisory. Format: YYYY-Mon-DD.")
@click.option('--assigned-to', metavar="EMAIL_ADDR", required=True,
              envvar="ELLIOTT_ASSIGNED_TO_EMAIL",
              callback=validate_email_address,
              help="The email address group to review and approve the advisory.")
@click.option('--manager', metavar="EMAIL_ADDR", required=True,
              envvar="ELLIOTT_MANAGER_EMAIL",
              callback=validate_email_address,
              help="The email address of the manager monitoring the advisory status.")
@click.option('--package-owner', metavar="EMAIL_ADDR", required=True,
              envvar="ELLIOTT_PACKAGE_OWNER_EMAIL",
              callback=validate_email_address,
              help="The email address of the person responsible managing the advisory.")
@click.option('--with-placeholder', is_flag=True,
              default=False, type=bool,
              help="Create a placeholder bug and attach it to the advisory. Only valid if also using --yes.")
@click.option('--yes', '-y', is_flag=True,
              default=False, type=bool,
              help="Create the advisory (by default only a preview is displayed)")
@click.option("--bug", "--bugs", "-b", 'bugs', type=int, multiple=True,
              help="Bug IDs for attaching to the advisory on creation. Required for creating a security advisory.")
@pass_runtime
@click.pass_context
def create_cli(ctx, runtime, errata_type, kind, impetus, date, assigned_to, manager, package_owner, with_placeholder, yes, bugs):
    """Create a new advisory. The kind of advisory must be specified with
'--kind'. Valid choices are 'rpm' and 'image'.

    You MUST specify a group (ex: "openshift-3.9") manually using the
    --group option. See examples below.

You must set a Release Date by providing a YYYY-Mon-DD formatted string to the
--date option.

The default behavior for this command is to show what the generated
advisory would look like. The raw JSON used to create the advisory
will be printed to the screen instead of posted to the Errata Tool
API.

The impetus option only effects the metadata added to the new
advisory and its synopsis.

The --assigned-to, --manager and --package-owner options are required.
They are the email addresses of the parties responsible for managing and
approving the advisory.

Adding a list of bug ids with one or more --bugs arguments attaches those bugs to the
advisory on creation. When creating a security advisory, the list of bugs will also be checked for any CVE flaw
bugs which they are blocking, and those will be added as well. Any CVE flaw bugs
being added will also calculate the Impact for the release if it's type is RHSA.

Provide the '--yes' or '-y' option to confirm creation of the
advisory.

    PREVIEW an RPM Advisory 21 days from now (the default release date) for OSE 3.9:

    $ elliott --group openshift-3.9 create

    CREATE Image Advisory for the 3.5 series on the first Monday in March:

\b
    $ elliott --group openshift-3.5 create --yes -k image --date 2018-Mar-05
"""
    # perform sanity checks and provide default values
    if errata_type == 'RHSA':
        if not bugs:
            raise ElliottFatalError(
                "When creating an RHSA, you must provide a list of bug id(s) using one or more `--bug` options.")
        if not impetus:
            impetus = 'cve'
        elif impetus != 'cve':
            raise ElliottFatalError("Invalid impetus")
    elif not impetus:
        impetus = 'standard'

    runtime.initialize()

    et_data = runtime.gitdata.load_data(key='erratatool').data
    bz_data = runtime.gitdata.load_data(key='bugzilla').data

    impact = None

    # User entered a valid value for --date, set the release date
    release_date = datetime.datetime.strptime(date, YMD)

    ######################################################################

    flaw_cve_map = {}
    impact = None
    unique_bugs = set(bugs)

    if bugs:
        bzapi = elliottlib.bzutil.get_bzapi(bz_data)
        LOGGER.info("Fetching bugs {} from Bugzilla...".format(
            " ".join(map(str, bugs))))
        bug_objects = bzapi.getbugs(bugs)
        # assert bugs are viable for a new advisory.
        _assert_bugs_are_viable(errata_type, bugs, bug_objects)
        if errata_type == 'RHSA':
            LOGGER.info("Fetching flaw bugs for trackers {}...".format(" ".join(map(str, bugs))))
            tracker_flaws_map = elliottlib.bzutil.get_tracker_flaws_map(bzapi, bug_objects)
            impact = elliottlib.bzutil.get_highest_impact(bug_objects, tracker_flaws_map)
            flaw_bugs = [flaw for tracker, flaws in tracker_flaws_map.items() for flaw in flaws]
            flaw_cve_map = elliottlib.bzutil.get_flaw_aliases(flaw_bugs)
            unique_bugs |= set(flaw_cve_map.keys())

    ######################################################################

    try:
        erratum = elliottlib.errata.new_erratum(
            et_data,
            errata_type=errata_type,
            kind=kind,
            boilerplate_name=(impetus if impetus != "standard" else kind),
            release_date=release_date.strftime(YMD),
            assigned_to=assigned_to,
            manager=manager,
            package_owner=package_owner,
            impact=impact,
            cves=' '.join((alias) for alias in flaw_cve_map.values())
        )
    except elliottlib.exceptions.ErrataToolUnauthorizedException:
        exit_unauthorized()
    except elliottlib.exceptions.ErrataToolError as ex:
        raise ElliottFatalError(getattr(ex, 'message', repr(ex)))

    erratum.addBugs(unique_bugs)

    if yes:
        erratum.commit()
        green_prefix("Created new advisory: ")
        click.echo(str(erratum))
        if errata_type == 'RHSA':
            yellow_print("Remember to manually set the Security Reviewer in the Errata Tool Web UI")

        # This is a little strange, I grant you that. For reference you
        # may wish to review the click docs
        #
        # http://click.pocoo.org/5/advanced/#invoking-other-commands
        #
        # You may be thinking, "But, add_metadata doesn't take keyword
        # arguments!" and that would be correct. However, we're not
        # calling that function directly. We actually use the context
        # 'invoke' method to call the _command_ (remember, it's wrapped
        # with click to create a 'command'). 'invoke' ensures the correct
        # options/arguments are mapped to the right parameters.
        ctx.invoke(add_metadata_cli, kind=kind, impetus=impetus, advisory=erratum.errata_id)
        click.echo(str(erratum))

        if with_placeholder:
            click.echo("Creating and attaching placeholder bug...")
            ctx.invoke(create_placeholder_cli, kind=kind, advisory=erratum.errata_id)
    else:
        green_prefix("Would have created advisory: ")
        click.echo("")
        click.echo(erratum)


def _assert_bugs_are_viable(errata_type, bugs, bug_objects):
    for index, bug in enumerate(bug_objects):
        bug_id = bugs[index]
        if not bug:
            raise ElliottFatalError("Couldn't find bug {}. Did you log in?".format(bug_id))
        if not elliottlib.bzutil.is_viable_bug(bug):
            raise ElliottFatalError("Bug {} is not viable: Status is {}.".format(bug_id, bug.status))
        if errata_type == 'RHSA' and not elliottlib.bzutil.is_cve_tracker(bug):
            raise ElliottFatalError("Bug {} is not a CVE tracker: Keywords are {}.".format(bug_id, bug.keywords))
        LOGGER.info("Checking if bug {} is already attached to an advisory...".format(bug_id))
        advisories = elliottlib.errata.get_advisories_for_bug(bug_id)
        if advisories:
            raise ElliottFatalError(
                "Bug {} is already attached to advisories: {}"
                .format(bug_id, " ".join([str(item["id"]) for item in advisories])))
        LOGGER.info("Bug {} is viable.".format(bug_id))
