import click
import datetime
import elliottlib
from elliottlib.cli.common import cli
from elliottlib.cli.add_metadata_cli import add_metadata_cli
from elliottlib.cli.create_placeholder_cli import create_placeholder_cli
from elliottlib.exectools import cmd_assert
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import YMD, validate_release_date, \
    validate_email_address, exit_unauthorized, green_prefix, yellow_print
pass_runtime = click.make_pass_decorator(elliottlib.Runtime)

LOGGER = elliottlib.logutil.getLogger(__name__)


#
# Create Advisory (RPM and image)
# advisory:create
#
@cli.command("create", short_help="Create a new advisory")
@click.option("--type", '-t', 'errata_type',
              type=click.Choice(['RHBA', 'RHEA']),
              default='RHBA',
              help="Type of Advisory to create.")
@click.option("--kind", '-k', required=True,
              type=click.Choice(['rpm', 'image']),
              help="Kind of artifacts that will be attached to Advisory. Affects boilerplate text.")
@click.option("--impetus",
              type=click.Choice(elliottlib.constants.errata_valid_impetus),
              default='standard',
              help="Impetus for the advisory creation. 'standard' by default")
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
@click.option('--with-liveid', is_flag=True,
              default=True, type=bool,
              help="Request a Live ID for the advisory. Only valid if also using --yes.")
@click.option('--yes', '-y', is_flag=True,
              default=False, type=bool,
              help="Create the advisory (by default only a preview is displayed)")
@click.option("--bug", "--bugs", "-b", 'bugs', type=int, multiple=True,
              help="Bug IDs for attaching to the advisory on creation. Required for creating a security advisory.")
@pass_runtime
@click.pass_context
def create_cli(ctx, runtime, errata_type, kind, impetus, date, assigned_to, manager, package_owner, with_placeholder, with_liveid, yes, bugs):
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

The impetus option only affects the metadata added to the new
advisory and its synopsis.

The --assigned-to, --manager and --package-owner options are required.
They are the email addresses of the parties responsible for managing and
approving the advisory.

Adding a list of bug ids with one or more --bugs arguments attaches those bugs to the
advisory on creation.

Provide the '--yes' or '-y' option to confirm creation of the
advisory.

    PREVIEW an RPM Advisory 21 days from now (the default release date) for OSE 3.9:

    $ elliott --group openshift-3.9 create

    CREATE Image Advisory for the 3.5 series on the first Monday in March:

\b
    $ elliott --group openshift-3.5 create --yes -k image --date 2018-Mar-05
"""
    runtime.initialize()

    et_data = runtime.gitdata.load_data(key='erratatool').data
    bz_data = runtime.gitdata.load_data(key='bugzilla').data

    # User entered a valid value for --date, set the release date
    release_date = datetime.datetime.strptime(date, YMD)

    ######################################################################

    unique_bugs = set(bugs)

    if bugs:
        bzapi = elliottlib.bzutil.get_bzapi(bz_data)
        LOGGER.info("Fetching bugs {} from Bugzilla...".format(
            " ".join(map(str, bugs))))
        bug_objects = bzapi.getbugs(bugs)
        # assert bugs are viable for a new advisory.
        _assert_bugs_are_viable(bugs, bug_objects)

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
            package_owner=package_owner
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

        if with_liveid:
            click.echo("Requesting Live ID...")
            base_url = "https://errata.devel.redhat.com/errata/set_live_advisory_name"
            cmd_assert(
                f"curl -X POST --fail --negotiate -u : {base_url}/{erratum.errata_id}",
                retries=3,
                pollrate=10,
            )

    else:
        green_prefix("Would have created advisory: ")
        click.echo("")
        click.echo(erratum)


def _assert_bugs_are_viable(bugs, bug_objects):
    for index, bug in enumerate(bug_objects):
        bug_id = bugs[index]
        if not bug:
            raise ElliottFatalError("Couldn't find bug {}. Did you log in?".format(bug_id))
        if not elliottlib.bzutil.is_viable_bug(bug):
            raise ElliottFatalError("Bug {} is not viable: Status is {}.".format(bug_id, bug.status))
        LOGGER.info("Checking if bug {} is already attached to an advisory...".format(bug_id))
        advisories = elliottlib.errata.get_advisories_for_bug(bug_id)
        if advisories:
            raise ElliottFatalError(
                "Bug {} is already attached to advisories: {}"
                .format(bug_id, " ".join([str(item["id"]) for item in advisories])))
        LOGGER.info("Bug {} is viable.".format(bug_id))
