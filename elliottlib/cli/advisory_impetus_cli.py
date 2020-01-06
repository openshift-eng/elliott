from __future__ import unicode_literals, print_function, with_statement
import click
import sys

from elliottlib import Runtime
from elliottlib.cli.common import cli, use_default_advisory_option, find_default_advisory
from elliottlib import errata

pass_runtime = click.make_pass_decorator(Runtime)


@cli.command('advisory-impetus', short_help='Get advisory impetus')
@click.option(
    '--advisory', '-a', 'advisory', type=int, default=None, metavar='ADVISORY',
    help='Explicitly define advisory ID to be used instead of the default')
@use_default_advisory_option
@pass_runtime
def advisory_impetus_cli(runtime, advisory, default_advisory_type):
    """Get advisory impetus.

    $ elliott advisory-impetus --advisory 48465

    or

    $ elliott -g openshift-4.2 advisory-impetus --use-default-advisory extras
    """
    if advisory and default_advisory_type:
        raise click.BadParameter('Use only one of --use-default-advisory or --advisory')

    runtime.initialize(no_group=(advisory is not None))

    if advisory is None:
        advisory = find_default_advisory(runtime, default_advisory_type)

    comments = errata.get_metadata_comments_json(advisory)
    if not comments or 'impetus' not in comments[0]:
        print('Error! impetus not found for advisory {}'.format(advisory), file=sys.stderr)
        print(comments, file=sys.stderr)
        exit(1)

    print(comments[0]['impetus'])
