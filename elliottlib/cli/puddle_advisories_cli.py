from __future__ import absolute_import, print_function, unicode_literals
import click
import sys
import elliottlib
from kerberos import GSSError
from elliottlib import logutil, Runtime
from elliottlib.cli.common import cli
from elliottlib.exceptions import ElliottFatalError
from elliottlib.util import exit_unauthenticated, major_from_branch, minor_from_branch

LOGGER = logutil.getLogger(__name__)

pass_runtime = click.make_pass_decorator(Runtime)


#
# Get advisory numbers for making puddles
#
@cli.command("puddle-advisories", short_help="Get advisory numbers for making puddles")
@click.option("--filter-id", '-f',
              default=elliottlib.constants.errata_puddle_advisory_filter,
              help="A custom filter id to list from")
@click.option('--details', '-d', is_flag=True, default=False,
              help="Print details about the found advisories to STDERR")
# @click.option("-n", default=6,
#               help="Return only N latest results (default: 6)")
@pass_runtime
def puddle_advisories_cli(runtime, filter_id, details):
    """Print a comma separated list of advisory numbers which can be used
when filling in the 'errata_whitelist' parameter in a signed puddle
config.

Uses an Errata Tool filter to find in-progress and being-released
advisories for OpenShift. This list is trimmed down to only advisories
matching the given --group by parsing the ART metadata embedded in the
first comment.

    List advisories required to create a signed 4.2 puddle:

\b
    $ elliott --group=openshift-4.1 puddle-advisories
    44849, 44740
"""
    use_in_puddle_conf = []
    runtime.initialize()
    major = major_from_branch(runtime.group_config.branch)
    minor = minor_from_branch(runtime.group_config.branch)
    release = "{}.{}".format(major, minor)

    try:
        for erratum in elliottlib.errata.get_filtered_list(filter_id, limit=50):
            metadata_comments_json = elliottlib.errata.get_metadata_comments_json(erratum.errata_id)
            if not metadata_comments_json:
                # Does not contain ART metadata, skip it
                sys.stderr.write("Does not contain ART metadata: {}\n".format(erratum.errata_id))
                continue

            metadata = metadata_comments_json[0]
            if str(metadata['release']) == str(release) and (metadata['impetus'] != 'test'):
                use_in_puddle_conf.append(str(erratum.errata_id))
                if details:
                    sys.stderr.write(str(erratum))
                    sys.stderr.flush()

        click.echo(", ".join(use_in_puddle_conf))
    except GSSError:
        exit_unauthenticated()
    except elliottlib.exceptions.ErrataToolError as ex:
        raise ElliottFatalError(getattr(ex, 'message', repr(ex)))
