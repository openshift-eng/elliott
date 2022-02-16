import datetime

from errata_tool import Erratum, ErrataException
from spnego.exceptions import GSSError
import click

from elliottlib.cli.common import cli
from elliottlib import logutil, Runtime
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import exit_unauthorized, green_prefix, validate_release_date, \
    YMD, validate_email_address
import elliottlib

LOGGER = logutil.getLogger(__name__)

pass_runtime = click.make_pass_decorator(Runtime)

#
# Create Text only advisory
# advisory:create-textonly


@cli.command('create-textonly',
             short_help='Create a textonly advisory along with notification bug attached')
@click.option("--type", '-t', 'errata_type',
              type=click.Choice(['RHBA', 'RHSA', 'RHEA']),
              default='RHBA',
              help="Type of Advisory to create.")
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
@click.option('--topic', required=True,
              help="Topic value for text only advisory")
@click.option('--synopsis', required=True,
              help="Synopsis value for text only advisory")
@click.option('--description', required=True,
              help="Description value for text only advisory")
@click.option('--solution', required=True,
              help="Solution value for text only advisory")
@click.option('--bugtitle', required=True,
              help="Bug title value for bug attached to text only advisory")
@click.option('--bugdescription', required=True,
              help="Description value for bug attached to text only advisory")
@click.option('--yes', '-y', is_flag=True,
              default=False, type=bool,
              help="Create the advisory (by default only a preview is displayed)")
@pass_runtime
@click.pass_context
def create_textonly_cli(ctx, runtime, errata_type, date, assigned_to, manager, package_owner, topic, synopsis, description, solution, bugtitle, bugdescription, yes):
    """
    Create a text only advisory with all required input passed from args, need to manually decide the statement for each release.
    Also will create the notification bug along with the text only advisory, the bug also need some special comment and title.
    These args need to be designated manually for text only advisory:
    - topic
    - synopsis
    - description
    - solution
    - assigned
    These args need to be designated manually for text only bug:
    - bugtitle
    - bugdescription
    """

    runtime.initialize()

    # create textonly bug
    bz_data = runtime.gitdata.load_data(key='bugzilla').data
    newbug = elliottlib.bzutil.create_textonly(bz_data, bugtitle, bugdescription)
    click.echo("Created BZ: {} {}".format(newbug.id, newbug.weburl))

    # create textonly advisory
    et_data = runtime.gitdata.load_data(key='erratatool').data
    try:
        erratum = Erratum(
            product=et_data['product'],
            release=et_data['release'],
            qe_group=et_data['quality_responsibility_name'],
            synopsis=synopsis,
            topic=topic,
            description=description,
            solution=solution,
            qe_email=assigned_to,
            errata_type=errata_type,
            owner_email=package_owner,
            manager_email=manager,
            date=date,
            text_only=1,
        )
    except elliottlib.exceptions.ErrataToolUnauthorizedException:
        exit_unauthorized()
    except elliottlib.exceptions.ErrataToolError as ex:
        raise repr(ex)

    erratum.addBugs(newbug.id)
    cdn_repos = et_data.get('cdn_repos')
    if cdn_repos:
        click.echo(f"Configuring CDN repos {', '.join(cdn_repos)}...")
        erratum.textOnlyRepos(enable=cdn_repos)
    if yes:
        erratum.commit()
        green_prefix("Created new text only advisory: ")
        click.echo(str(erratum))
    else:
        green_prefix("Would have created advisory: ")
        click.echo("")
        click.echo(erratum)
