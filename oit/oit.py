#!/usr/bin/env python

from packages import Runtime
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


@cli.command("clone-distgits", help="Clone a group's distgit repos.")
@option_working_dir
@option_group
@option_branch
@pass_runtime
def clone_distgits(runtime, working_dir, group, branch):
    runtime.working_dir = working_dir
    runtime.group = group
    runtime.distgit_branch = branch
    runtime.info("Cloning all distgit repos into: %s" % runtime.distgits_dir)
    runtime.clone_distgit()


@cli.command("update-dockerfiles", help="Update a group's distgit Dockerfiles.")
@option_working_dir
@option_group
@option_branch
@click.option("--repo", metavar="ALIAS PATH", nargs=2, multiple=True, help="Associated a path with a given repo alias.  [multiple]")
@pass_runtime
def update_dockerfiles(runtime, working_dir, group, branch, repo):
    runtime.working_dir = working_dir
    runtime.group = group
    runtime.distgit_branch = branch

    # For each "--repo alias path" on the command line, register its existence with
    # the runtime.
    for r in repo:
        runtime.register_repo(r[0], r[1])

    runtime.clone_distgits()


if __name__ == '__main__':
    cli(obj={})
