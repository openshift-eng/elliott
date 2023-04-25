import itertools

import click
import requests
from errata_tool import Erratum
from requests_gssapi import HTTPSPNEGOAuth

from elliottlib.cli.common import cli
from elliottlib.constants import errata_drop_url
from elliottlib.exceptions import ElliottFatalError
from elliottlib.errata import remove_dependent_advisories


@cli.command("advisory-drop", short_help="Drop advisory")
@click.argument("advisory", nargs=1)
def advisory_drop_cli(advisory):
    """Drop advisory

    Advisories can only be dropped by the creators, and program management.
    This script can get run on buildvm with the credentials of the creator of
    ART's advisories, so the bot account can drop them.
    """
    adv = Erratum(errata_id=advisory)
    if adv.errata_state == "DROPPED_NO_SHIP":
        click.echo(f'Advisory {advisory} is already dropped')
        return

    # move advisory status to NEW_FILES
    if adv.errata_state != "NEW_FILES":
        adv.setState("NEW_FILES")
        adv.commit()

    # Remove bugs and builds before dropping the advisory
    all_bugs = adv.errata_bugs
    all_jiras = adv.jira_issues
    all_builds = list(set(itertools.chain.from_iterable(adv.errata_builds.values())))
    if all_bugs or all_jiras or all_builds:
        if all_bugs:
            adv.removeBugs(all_bugs)
        if all_jiras:
            adv.removeJIRAIssues(all_jiras)
        if all_builds:
            adv.removeBuilds(all_builds)
        remove_dependent_advisories(advisory)
        adv.commit()

    # Drop advisory
    url = errata_drop_url.format(id=advisory)
    data = 'utf8=%E2%9C%93&reason=Dropping+unused+advisory%21&commit=Dropping+unused+advisory'
    headers = {"Content-Type": "text/plain"}
    r = requests.post(url, auth=HTTPSPNEGOAuth(), data=data, headers=headers)
    adv.refresh()
    if adv.errata_state != "DROPPED_NO_SHIP":
        raise ElliottFatalError(f'Failed to drop advisory {advisory}. Got status code {r.status_code}. Are you the owner of advisory {advisory}?')

    click.echo(f'Successfully dropped advisory {advisory}')
