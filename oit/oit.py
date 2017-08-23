#!/usr/bin/env python

from packages import Runtime
from packages import Dir
import click
import os

pass_runtime = click.make_pass_decorator(Runtime)


@click.group()
@click.option("--metadata-dir", default=None, metavar='PATH', help="Directory containing groups metadata directory if not current.")
@click.option("--user", default=None, metavar='USERNAME', help="Username for rhpkg.")
@click.option('--verbose', '-v', default=False, is_flag=True, help='Enables verbose mode.')
@click.version_option("0.1")
@click.pass_context
def cli(ctx, metadata_dir, user, verbose):
    if metadata_dir is None:
        metadata_dir = os.getcwd()

    # @pass_runtime
    ctx.obj = Runtime(metadata_dir, user, verbose)


option_working_dir = click.option("--working-dir", metavar='PATH',
                                  help="Existing directory in which operations should be performed.", required=True)
option_group = click.option("--group", default=None, metavar='NAME',
                            help="The group of images on which to operate.", required=True)
option_branch = click.option("--branch", default=None, metavar='NAME',
                             help="The distgit branch each group member must switch to.", required=True)

option_dry_run = click.option("--message", "-m", metavar='MSG', help="Commit message for dist-git.", required=True)
option_commit_message = click.option('--dry-run', default=False, is_flag=True, help='Perform changes locally, but do not push.')


@cli.command("distgits:clone", help="Clone a group's distgit repos.")
@option_working_dir
@option_group
@option_branch
@pass_runtime
def distgits_clone(runtime, working_dir, group, branch):
    runtime.working_dir = working_dir
    runtime.group = group
    runtime.distgit_branch = branch
    runtime.info("Cloning all distgit repos into: %s" % runtime.distgits_dir)
    runtime.clone_distgit()


@cli.command("distgits:update", help="Update a group's distgit content/Dockerfile.")
@option_working_dir
@option_group
@option_branch
@option_dry_run
@option_commit_message
@click.option("--source", metavar="ALIAS PATH", nargs=2, multiple=True, help="Associate a path with a given source alias.  [multiple]")
@pass_runtime
def distgits_update(runtime, working_dir, group, branch, source, message, dry_run):
    runtime.working_dir = working_dir
    runtime.group = group
    runtime.distgit_branch = branch

    # For each "--repo alias path" on the command line, register its existence with
    # the runtime.
    for r in source:
        runtime.register_source_alias(r[0], r[1])

    runtime.clone_distgits()

    for image in runtime.images.values():
        image.populate_distgit_dir()


# rm -rf working ; mkdir working ; ./oit/oit.py distgits:foreach -m Test --dry-run --working-dir=working --group=ocp-3.7 --branch=rhaos-3.7-rhel-7 -- echo -n hello
@cli.command("distgits:foreach", help="Run a command relative to each distgit dir.")
@option_working_dir
@option_group
@option_branch
@option_dry_run
@option_commit_message
@click.argument("cmd", nargs=-1)
@pass_runtime
def distgits_foreach(runtime, working_dir, group, branch, message, dry_run, cmd):
    """
    Clones all distgit repos found in the specified group and runs an arbitrary
    command once for each local distgit directory. If the command runs without
    error for all directories, a commit will be made. If not a dry_run,
    the repo will be pushed.
    """
    runtime.working_dir = working_dir
    runtime.group = group
    runtime.distgit_branch = branch

    runtime.clone_distgits()

    for image in runtime.images.values():
        with Dir(image.distgit_dir):
            # TODO
            click.echo("Should run %s in distgit directory: %s" % (cmd, os.getcwd()))


if __name__ == '__main__':
    cli(obj={})
