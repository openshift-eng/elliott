from __future__ import absolute_import, print_function, unicode_literals
import json

import elliottlib
from elliottlib import constants, logutil, Runtime
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import exit_unauthenticated, exit_unauthorized, ensure_erratatool_auth
from elliottlib.util import release_from_branch, green_prefix, green_print, red_print

from errata_tool import Erratum, ErrataException
from kerberos import GSSError
import requests
import click

LOGGER = logutil.getLogger(__name__)

pass_runtime = click.make_pass_decorator(Runtime)
#
# Add metadata comment to an Advisory
# advisory:add-metadata
#


@cli.command("add-metadata", short_help="Add metadata comment to an advisory")
@click.argument('advisory', type=int)
@click.option('--kind', '-k', required=True,
              type=click.Choice(['rpm', 'image']),
              help="KIND of advisory [rpm, image]")
@click.option('--impetus', default='standard',
              type=click.Choice(elliottlib.constants.errata_valid_impetus),
              help="Impetus for the advisory creation [standard, cve, ga, test]")
@pass_runtime
def add_metadata_cli(runtime, kind, impetus, advisory):
    """Add metadata to an advisory. This is usually called by
create immediately after creation. It is only useful to you if
you are going back and adding metadata to older advisories.

    Note: Requires you provide a --group

Example to add standard metadata to a 3.10 images release

\b
    $ elliott --group=openshift-3.10 add-metadata --impetus standard --kind image
"""
    runtime.initialize()
    release = release_from_branch(runtime.group_config.branch)

    try:
        advisory = Erratum(errata_id=advisory)
    except GSSError:
        exit_unauthenticated()

    result = elliottlib.errata.add_comment(
        advisory.errata_id, {'release': release, 'kind': kind, 'impetus': impetus})

    if result.status_code == 201:
        green_prefix("Added metadata successfully")
        click.echo()
    elif result.status_code == 403:
        exit_unauthorized()
    else:
        red_print("Something weird may have happened")
        raise ElliottFatalError(
            "Unexpected response from ET API: {code}".format(code=result.status_code))
