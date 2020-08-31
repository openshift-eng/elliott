import asyncio
import sys
from functools import update_wrapper

import click

from elliottlib import Runtime, constants, dotconfig, version
from elliottlib.cli import cli_opts
from elliottlib.util import green_prefix, red_prefix, yellow_print


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo('Elliott v{}'.format(version()))
    click.echo("Python v{}".format(sys.version))
    ctx.exit()


context_settings = dict(help_option_names=['-h', '--help'])


@click.group(context_settings=context_settings)
@click.option(
    '--version',
    is_flag=True, callback=print_version, expose_value=False, is_eager=True)
@click.option(
    '--working-dir',
    metavar='PATH', envvar='ELLIOTT_WORKING_DIR', default=None,
    help='Existing directory in which file operations should be performed.')
@click.option(
    '--data-path',
    metavar='PATH', default=None,
    help='Git repo or directory containing groups metadata')
@click.option(
    '--group', '-g',
    default=None, metavar='NAME',
    help='The group of images on which to operate.')
@click.option(
    '--branch',
    default=None, metavar='BRANCH',
    help='Branch to override any default in group.yml.')
@click.option(
    '-i', '--images',
    default=[], metavar='NAME', multiple=True,
    help='Name of group image member to include in operation (all by default). Can be comma delimited list.')
@click.option(
    '-x', '--exclude',
    default=[], metavar='NAME', multiple=True,
    help='Name of group image or rpm member to exclude in operation (none by default). Can be comma delimited list.')
@click.option(
    '--quiet', '-q',
    default=False, is_flag=True,
    help='Suppress non-critical output')
@click.option(
    '--debug',
    default=False, is_flag=True,
    help='Show debug output on console.')
@click.pass_context
def cli(ctx, **kwargs):
    cfg = dotconfig.Config(
        'elliott', 'settings',
        template=cli_opts.CLI_CONFIG_TEMPLATE,
        envvars=cli_opts.CLI_ENV_VARS,
        cli_args=kwargs)
    ctx.obj = Runtime(cfg_obj=cfg, **cfg.to_dict())


#
# Look up a default advisory specified for the branch in ocp-build-data
# Advisory types are in elliottlib.constants.standard_advisory_types
# but this doesn't validate against that.
#
def find_default_advisory(runtime, default_advisory_type, quiet=False):
    '''The `quiet` parameter will disable printing the informational message'''
    default_advisory = runtime.group_config.advisories.get(default_advisory_type, None)
    if default_advisory is None:
        red_prefix('No value defined for default advisory:')
        click.echo(' The key advisories.{} is not defined for group {} in group.yml'.format(
            default_advisory_type, runtime.group))
        exit(1)
    if not quiet:
        green_prefix('Default advisory detected: ')
        click.echo(default_advisory)
    return default_advisory


use_default_advisory_option = click.option(
    '--use-default-advisory', 'default_advisory_type',
    metavar='ADVISORY_TYPE',
    type=click.Choice(constants.standard_advisory_types),
    help='Use the default value from group.yml for ADVISORY_TYPE [{}]'.format(
        ', '.join(constants.standard_advisory_types)))

pass_runtime = click.make_pass_decorator(Runtime)


def click_coroutine(f):
    """ A wrapper to allow to use asyncio with click.
    https://github.com/pallets/click/issues/85
    """
    f = asyncio.coroutine(f)

    def wrapper(*args, **kwargs):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(f(*args, **kwargs))
    return update_wrapper(wrapper, f)
