from __future__ import absolute_import, print_function, unicode_literals
import click
import elliottlib
from kerberos import GSSError
from elliottlib.util import exit_unauthenticated
from elliottlib.exceptions import ElliottFatalError


#
# List Advisories (RPM and image)
# advisory:list
#
@click.command("list", short_help="List filtered RHOSE advisories")
@click.option("--filter-id", '-f',
              default=elliottlib.constants.errata_default_filter,
              help="A custom filter id to list from")
@click.option("-n", default=6,
              help="Return only N latest results (default: 6)")
@click.pass_context
def list_cli(ctx, filter_id, n):
    """Print a list of one-line informational strings of RHOSE
advisories. By default the 5 most recently created advisories are
printed. Note, they are NOT sorted by release date.

    NOTE: new filters must be created in the Errata Tool web
    interface.

Default filter definition: RHBA; Active; Product: RHOSE; Devel Group:
ENG OpenShift Enterprise; sorted by newest. Browse this filter
yourself online: https://errata.devel.redhat.com/filter/1965

    List 10 advisories instead of the default 6 with your custom
    filter #1337:

    $ elliott list -n 10 -f 1337
"""
    try:
        for erratum in elliottlib.errata.get_filtered_list(filter_id, limit=n):
            click.echo("{release_date:11s} {state:15s} {synopsis:80s} {url}".format(
                       release_date=erratum.publish_date_override,
                       state=erratum.errata_state,
                       synopsis=erratum.synopsis,
                       url=erratum.url()))
    except GSSError:
        exit_unauthenticated()
    except elliottlib.exceptions.ErrataToolError as ex:
        raise ElliottFatalError(getattr(ex, 'message', repr(ex)))
