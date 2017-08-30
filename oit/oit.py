#!/usr/bin/env python

from packages import Runtime
from packages import Dir
import click
import os
from multiprocessing.dummy import Pool as ThreadPool

pass_runtime = click.make_pass_decorator(Runtime)


@click.group()
@click.option("--metadata-dir", metavar='PATH', default=None,
              help="Directory containing groups metadata directory if not current.")
@click.option("--working-dir", metavar='PATH', default=None,
              help="Existing directory in which file operations should be performed.")
@click.option("--user", metavar='USERNAME', default=None,
              help="Username for rhpkg.")
@click.option("--group", default=None, metavar='NAME',
              help="The group of images on which to operate.")
@click.option("--branch", default=None, metavar='NAME',
              help="The distgit branch each group member must switch to.")
@click.option('--verbose', '-v', default=False, is_flag=True, help='Enables verbose mode.')
@click.pass_context
def cli(ctx, metadata_dir, working_dir, group, branch, user, verbose):
    if metadata_dir is None:
        metadata_dir = os.getcwd()

    # @pass_runtime
    ctx.obj = Runtime(metadata_dir, working_dir, group, branch, user, verbose)


option_commit_message = click.option("--message", "-m", metavar='MSG', help="Commit message for dist-git.", required=True)
option_push = click.option('--push/--no-push', default=True, is_flag=True,
                           help='Pushes to distgit after local changes by default.')


@cli.command("distgits:clone", help="Clone a group's distgit repos.")
@pass_runtime
def distgits_clone(runtime):
    runtime.initialize()
    # Never delete after clone; defeats the purpose of cloning
    runtime.remove_working_dir = False
    [r.distgit_repo() for r in runtime.images()]


@cli.command("distgits:push", help="Push a group of distgits previously populated in working directory.")
# Unlike other actions, message is optional. If not specified, assume that a commit was already made and only push.
@click.option("--message", "-m", metavar='MSG', help="Add a commit message for the push.")
@pass_runtime
def distgits_push(runtime):
    runtime.initialize()

    # TODO: implement
    click.echo("Not yet implemented")


@cli.command("distgits:update", help="Update a group's distgit content/Dockerfile.")
@option_push
@option_commit_message
@click.option("--source", metavar="ALIAS PATH", nargs=2, multiple=True,
              help="Associate a path with a given source alias.  [multiple]")
@click.option("--stream", metavar="ALIAS REPO/NAME:TAG", nargs=2, multiple=True,
              help="Associate an image name with a given stream alias.  [multiple]")
@click.option("--version", metavar='VERSION', help="Version string to populate in Dockerfiles.", required=True)
@click.option("--release", metavar='RELEASE', default="1", help="Release string to populate in Dockerfiles.")
@pass_runtime
def distgits_update(runtime, source, stream, message, version, release, push):
    runtime.initialize()

    # If not pushing, do not clean up our work
    runtime.remove_tmp_working_dir = push

    # For each "--source alias path" on the command line, register its existence with
    # the runtime.
    for r in source:
        runtime.register_source_alias(r[0], r[1])

    # For each "--stream alias image" on the command line, register its existence with
    # the runtime.
    for s in stream:
        runtime.register_stream_alias(s[0], s[1])

    for image in runtime.images():
        dgr = image.distgit_repo()
        dgr.update_distgit_dir(version, release)


# ./oit/oit.py --group=ocp-3.7 --branch=rhaos-3.7-rhel-7 distgits:foreach -m Test --dry-run -- echo -n hello
@cli.command("distgits:foreach", help="Run a command relative to each distgit dir.")
@option_push
@option_commit_message
@click.argument("cmd", nargs=-1)
@pass_runtime
def distgits_foreach(runtime, message, push, cmd):
    """
    Clones all distgit repos found in the specified group and runs an arbitrary
    command once for each local distgit directory. If the command runs without
    error for all directories, a commit will be made. If not a dry_run,
    the repo will be pushed.
    """
    runtime.initialize()

    # TODO: implement
    click.echo("Not yet implemented")

    # If not pushing, do not clean up our work
    runtime.remove_tmp_working_dir = push

    dgrs = [image.distgit_repo() for image in runtime.images()]
    for dgr in dgrs:
        with Dir(dgr.distgit_dir):
            # TODO
            click.echo("Should run %s in distgit directory: %s" % (cmd, os.getcwd()))


@cli.command("distgits:copy", help="Copy content of source branch to target.")
@option_push
@option_commit_message
@click.option("--to-branch", metavar="TARGET_BRANCH", help="Branch to populate from source branch.")
@click.option('--overwrite', default=False, is_flag=True, help='Overwrite files found in target.')
@click.option("--replace", metavar="MATCH REPLACEMENT", nargs=2, multiple=True,
              help="String replacement in target Dockerfile.  [multiple]")
@pass_runtime
def distgits_copy(runtime, message, push, to_branch, overwrite, cmd):
    runtime.initialize()

    # TODO: implement
    click.echo("Not yet implemented")


def build_image(tuple):
    image = tuple[0]
    repo_conf = tuple[1]
    push_to = tuple[2]
    scratch = tuple[3]

    dgr = image.distgit_repo()
    if not dgr.build_distgit_dir(repo_conf, push_to, scratch):
        image.runtime.info("Error building: %s" % image.qualified_name)
        return False
    return True


@cli.command("distgits:build", help="Build images for the group.")
@click.option("--repo-conf", default=[], metavar="URL", multiple=True,
              help="Repo configuration file.  [multiple]")
@click.option("--push-to", default=[], metavar="REGISTRY", multiple=True,
              help="Registry to push to when image build completes.  [multiple]")
@click.option('--scratch', default=False, is_flag=True, help='Perform a scratch build.')
@pass_runtime
def distgits_build(runtime, repo_conf, push_to, scratch):
    runtime.initialize()

    items = []

    # Initialize all distgit directories before trying to build. This is
    # for clarity in the logs.
    for image in runtime.images():
        image.distgit_repo()
        items.append((image, repo_conf, push_to, scratch))

    pool = ThreadPool(len(items))
    results = pool.map(build_image, items)

    # Wait for results
    pool.close()
    pool.join()

    for result in results:
        if not result:
            runtime.info("At least one image build/push failed")
            exit(1)

@cli.command("distgits:push", help="Push the images referenced in distgit to mirrors.")
@click.option("--to", metavar="REGISTRY", multiple=True,
              help="Registry to push to when image build completes.  [multiple]")
@pass_runtime
def distgits_push(runtime, to):
    runtime.initialize()

    for image in runtime.images():
        dgr = image.distgit_repo()
        dgr.push_distgit_image(to)


if __name__ == '__main__':
    cli(obj={})
