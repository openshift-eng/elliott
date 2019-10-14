import click
import elliottlib
from kerberos import GSSError
from elliottlib.util import exit_unauthenticated, green_prefix, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from errata_tool import Erratum, ErrataException


#
# Create Placeholder BZ
# bugzilla:create-placeholder
#
@click.command("create-placeholder", short_help="Create a placeholder BZ")
@click.option('--kind', '-k', metavar='KIND',
              required=False, type=click.Choice(elliottlib.constants.placeholder_valid_types),
              help='KIND [{}] of placeholder bug to create. Affects BZ title.'.format(
                  ', '.join(elliottlib.constants.placeholder_valid_types)))
@click.option('--attach', '-a', 'advisory',
              default=False, metavar='ADVISORY',
              help='Attach the bug to ADVISORY')
@click.option("--use-default-advisory", 'default_advisory_type',
              metavar='ADVISORY_TYPE',
              type=click.Choice(elliottlib.constants.placeholder_valid_types),
              help="Use the default value from ocp-build-data for ADVISORY_TYPE [{}]".format(
                  ', '.join(elliottlib.constants.placeholder_valid_types)))
@click.pass_context
def create_placeholder(ctx, kind, advisory, default_advisory_type):
    """Create a placeholder bug for attaching to an advisory.

    KIND - The kind of placeholder to create ({}).
    ADVISORY - Optional. The advisory to attach the bug to.

    $ elliott --group openshift-4.1 create-placeholder --kind rpm --attach 12345
""".format('/'.join(elliottlib.constants.placeholder_valid_types))
    runtime = ctx.obj
    runtime.initialize()
    if advisory and default_advisory_type:
        raise click.BadParameter("Use only one of --use-default-advisory or --advisory")

    if default_advisory_type is not None:
        advisory = find_default_advisory(runtime, default_advisory_type)
        kind = default_advisory_type

    if kind is None:
        raise click.BadParameter("--kind must be specified when not using --use-default-advisory")

    bz_data = runtime.gitdata.load_data(key='bugzilla').data
    target_release = bz_data['target_release'][0]
    newbug = elliottlib.bzutil.create_placeholder(bz_data, kind, target_release)

    click.echo("Created BZ: {} {}".format(newbug.id, newbug.weburl))

    if advisory is not False:
        click.echo("Attaching to advisory...")

        try:
            advs = Erratum(errata_id=advisory)
        except GSSError:
            exit_unauthenticated()

        if advs is False:
            raise ElliottFatalError("Error: Could not locate advisory {advs}".format(advs=advisory))

        try:
            green_prefix("Adding placeholder bug to advisory:")
            click.echo(" {advs}".format(advs=advisory))
            advs.addBugs([newbug.id])
            advs.commit()
        except ErrataException as ex:
            raise ElliottFatalError(getattr(ex, 'message', repr(ex)))
