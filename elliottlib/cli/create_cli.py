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
@click.option("--impetus", default='standard',
              type=click.Choice(elliottlib.constants.errata_valid_impetus),
              help="Impetus for the advisory creation [{}]".format(
                  ', '.join(elliottlib.constants.errata_valid_impetus)))
@click.option("--date", required=False,
              default=default_release_date.strftime(YMD),
              callback=validate_release_date,
              help="Release date for the advisory. Optional. Format: YYYY-Mon-DD. Defaults to 3 weeks after the release with the highest date for that series")
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
@click.option("--bugs", "-b", 'bugs', multiple=True)
@pass_runtime
@click.pass_context
def create_cli(ctx, runtime, errata_type, kind, impetus, date, assigned_to, manager, package_owner, with_placeholder, yes, bugs):
    """Create a new advisory. The kind of advisory must be specified with
'--kind'. Valid choices are 'rpm' and 'image'.

    You MUST specify a group (ex: "openshift-3.9") manually using the
    --group option. See examples below.

New advisories will be created with a Release Date set to 3 weeks (21
days) from now. You may customize this (especially if that happens to
fall on a weekend) by providing a YYYY-Mon-DD formatted string to the
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
advisory on creation. The list of bugs will also be checked for any CVE flaw
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
    runtime.initialize()

    if errata_type == 'RHSA' and not bugs:
        raise ElliottFatalError("When creating an RHSA, you must provide a list of bug id(s)")

    et_data = runtime.gitdata.load_data(key='erratatool').data
    bz_data = runtime.gitdata.load_data(key='bugzilla').data

    major = major_from_branch(runtime.group_config.branch)
    minor = minor_from_branch(runtime.group_config.branch)
    impact = None

    if date == default_release_date.strftime(YMD):
        # User did not enter a value for --date, default is determined
        # by looking up the latest erratum in a series
        try:
            latest_advisory = elliottlib.errata.find_latest_erratum(kind, major, minor)
        except GSSError:
            exit_unauthenticated()
        except elliottlib.exceptions.ErrataToolUnauthorizedException:
            exit_unauthorized()
        except elliottlib.exceptions.ErrataToolError as ex:
            raise ElliottFatalError(getattr(ex, 'message', repr(ex)))
        else:
            if latest_advisory is None:
                red_print("No metadata discovered")
                raise ElliottFatalError("No advisory for {x}.{y} has been released in recent history, can not auto "
                                        "determine next release date".format(x=major, y=minor))

        green_prefix("Found an advisory to calculate new release date from: ")
        click.echo("{synopsis} - {rel_date}".format(
            synopsis=latest_advisory.synopsis,
            rel_date=str(latest_advisory.release_date)))
        release_date = latest_advisory.release_date + datetime.timedelta(days=21)

        # We want advisories to issue on Tuesdays. Using strftime
        # Tuesdays are '2' with Sunday indexed as '0'
        day_of_week = int(release_date.strftime('%w'))
        if day_of_week != 2:
            # How far from our target day of the week?
            delta = day_of_week - 2
            release_date = release_date - datetime.timedelta(days=delta)
            yellow_print("Adjusted release date to land on a Tuesday")

        green_prefix("Calculated release date: ")
        click.echo("{}".format(str(release_date)))
    else:
        # User entered a valid value for --date, set the release date
        release_date = datetime.datetime.strptime(date, YMD)

    ######################################################################

    flaw_cve_map = {}
    impact = None
    unique_bugs = set(bugs)

    if bugs:
        bzapi = elliottlib.bzutil.get_bzapi(bz_data)
        LOGGER.info("Fetching bugs {} from Bugzilla...".format(" ".join(map(str, bugs))))
        bug_objects = bzapi.getbugs(bugs)
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
            kind=(impetus if impetus in ['extras', 'metadata'] else kind),
            release_date=release_date.strftime(YMD),
            create=yes,
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

    if yes:
        green_prefix("Created new advisory: ")
        click.echo(str(erratum.synopsis))

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

        erratum.addBugs(unique_bugs)

        if errata_type == 'RHSA':
            click.echo("Automatically attaching CVE flaw bugs ...")
            erratum.addBugs(flaw_cve_map.keys())

            yellow_print("Remember to manually set the Security Reviewer in the Errata Tool Web UI")

        erratum.commit()

        if with_placeholder:
            click.echo("Creating and attaching placeholder bug...")
            ctx.invoke(create_placeholder_cli, kind=kind, advisory=erratum.errata_id)
    else:
        green_prefix("Would have created advisory: ")
        click.echo("")
        click.echo(erratum)
