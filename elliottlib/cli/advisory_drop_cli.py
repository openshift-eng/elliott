import click
import requests
from requests_kerberos import HTTPKerberosAuth
import sys

from elliottlib.constants import errata_drop_url
from elliottlib.cli.common import cli


@cli.command("advisory-drop", short_help="Drop advisory")
@click.argument("advisory", nargs=1)
def advisory_drop_cli(advisory):
    """Drop advisory

    Advisories can only be dropped by the creators, and program management.
    This script can get run on buildvm with the credentials of the creator of
    ART's advisories, so the bot account can drop them.
    """

    url = errata_drop_url.format(id=advisory)
    data = 'utf8=%E2%9C%93&reason=Dropping+unused+advisory%21&commit=Dropping+unused+advisory'
    headers = {"Content-Type": "text/plain"}

    r = requests.post(url, auth=HTTPKerberosAuth(), data=data, headers=headers)
    if r.status_code == 200:
        click.echo(f'Succesfully dropped advisory {advisory}')
        sys.exit(0)
    elif "ERROR: Validation failed: Previous - Transition DROPPED_NO_SHIP =&gt; DROPPED_NO_SHIP is invalid" in r.text:
        click.echo(f'Advisory {advisory} already seems dropped')
        sys.exit(0)
    else:
        click.echo(f'Failed to drop advisory {advisory}. Got status code {r.status_code}')
        click.echo(r.text)
        sys.exit(1)
