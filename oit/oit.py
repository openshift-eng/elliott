#!/usr/bin/env python

from packages import Runtime
from packages import Dir
import click
import os
import yaml
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


@cli.command("distgits:clone", help="Clone a group's distgit repos locally.")
@pass_runtime
def distgits_clone(runtime):
    runtime.initialize()
    # Never delete after clone; defeats the purpose of cloning
    runtime.remove_tmp_working_dir = False
    [r.distgit_repo() for r in runtime.images()]


@cli.command("distgits:push", short_help="Push all distgist repos in working-dir.")
@pass_runtime
def distgits_push(runtime):
    """
    Run to execute an rhpkg push on all locally cloned distgit
    repositories. This is useful following a series of modifications
    in the local clones.
    """
    runtime.initialize()

    for image in runtime.images():
        dgr = image.distgit_repo()
        dgr.push()

@cli.command("distgits:update-dockerfile", short_help="Update a group's distgit Dockerfile from metadata.")
@click.option("--stream", metavar="ALIAS REPO/NAME:TAG", nargs=2, multiple=True,
              help="Associate an image name with a given stream alias.  [multiple]")
@click.option("--version", metavar='VERSION', help="Version string to populate in Dockerfiles.", required=True)
@click.option("--release", metavar='RELEASE', default="1", help="Release string to populate in Dockerfiles.")
@option_commit_message
@option_push
@pass_runtime
def distgits_update(runtime, stream, version, release, message, push):
    """
    Updates the Dockerfile in each distgit repository with the latest metadata and
    the version/release information specified. This does not update the Dockerfile
    from any external source. For that, use distgits:rebase.
    """
    runtime.initialize()

    # If not pushing, do not clean up our work
    runtime.remove_tmp_working_dir = push

    # For each "--stream alias image" on the command line, register its existence with
    # the runtime.
    for s in stream:
        runtime.register_stream_alias(s[0], s[1])

    for image in runtime.images():
        dgr = image.distgit_repo()
        dgr.update_dockerfile(version, release)
        dgr.commit(message)

    if push:
        for image in runtime.images():
            dgr = image.distgit_repo()
            dgr.push()


@cli.command("distgits:rebase", short_help="Refresh a group's distgit content from source content.")
@click.option("--source", metavar="ALIAS PATH", nargs=2, multiple=True,
              help="Associate a path with a given source alias.  [multiple]")
@click.option("--sources", metavar="YAML_PATH",
              help="YAML dict associating sources with their alias. Same as using --source multiple times.")
@click.option("--stream", metavar="ALIAS REPO/NAME:TAG", nargs=2, multiple=True,
              help="Associate an image name with a given stream alias.  [multiple]")
@click.option("--version", metavar='VERSION', help="Version string to populate in Dockerfiles.", required=True)
@click.option("--release", metavar='RELEASE', default="1", help="Release string to populate in Dockerfiles.")
@option_commit_message
@option_push
@pass_runtime
def distgits_rebase(runtime, source, sources, stream, version, release, message, push):
    """
    Many of the Dockerfiles stored in distgit are based off of content managed in GitHub.
    For example, openshift-enterprise-node-docker should always closely reflect the changes
    being made upstream in github.com/openshift/ose/images/node. This operation
    goes out and pulls the current source Dockerfile (and potentially other supporting
    files) into distgit and applies any transformations defined in the config.yml associated
    with the distgit repo.

    This operation will also set the version and release in the file according to the
    command line arguments provided.

    If a distgit repo does not have associated source (i.e. it is managed directly in
    distgit), the Dockerfile in distgit will not be rebased, but other aspects of the
    metadata may be applied (base image, tags, etc) along with the version and release.
    """
    runtime.initialize()

    # If not pushing, do not clean up our work
    runtime.remove_tmp_working_dir = push

    # For each "--source alias path" on the command line, register its existence with
    # the runtime.
    for r in source:
        runtime.register_source_alias(r[0], r[1])

    if sources:
        with open(sources, 'r') as sf:
            source_dict = yaml.load(sf)
            if not isinstance(source_dict, dict):
                raise ValueError('--sources param must be a yaml file containing a single dict.')
            for key, val in source_dict.items():
                runtime.register_source_alias(key, val)

    # For each "--stream alias image" on the command line, register its existence with
    # the runtime.
    for s in stream:
        runtime.register_stream_alias(s[0], s[1])

    for image in runtime.images():
        dgr = image.distgit_repo()
        dgr.rebase_dir(version, release)
        dgr.commit(message)

    if push:
        for image in runtime.images():
            dgr = image.distgit_repo()
            dgr.push()


@cli.command("distgits:foreach", help="Run a command relative to each distgit dir.")
@click.argument("cmd", nargs=-1)
@click.option("--message", "-m", metavar='MSG', help="Commit message for dist-git.", required=False)
@option_push
@pass_runtime
def distgits_foreach(runtime, cmd, message, push):
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

        if message is not None:
            dgr.commit(message)

    if push:
        for image in runtime.images():
            dgr = image.distgit_repo()
            dgr.push()


@cli.command("distgits:copy", help="Copy content of source branch to target.")
@click.option("--to-branch", metavar="TARGET_BRANCH", help="Branch to populate from source branch.")
@click.option('--overwrite', default=False, is_flag=True, help='Overwrite files found in target.')
@click.option("--replace", metavar="MATCH REPLACEMENT", nargs=2, multiple=True,
              help="String replacement in target Dockerfile.  [multiple]")
@option_commit_message
@option_push
@pass_runtime
def distgits_copy(runtime, to_branch, overwrite, cmd, message, push):
    runtime.initialize()

    # TODO: implement
    click.echo("Not yet implemented")


def build_image(tuple):
    image = tuple[0]
    repo_conf = tuple[1]
    push_to = tuple[2]
    scratch = tuple[3]

    dgr = image.distgit_repo()
    if not dgr.build_container(repo_conf, push_to, scratch):
        dgr.info("Async error in image build thread: %s" % image.qualified_name)
        return False
    return True


@cli.command("distgits:build-images", short_help="Build images for the group.")
@click.option("--repo-conf", default=[], metavar="URL", multiple=True,
              help="Repo configuration file.  [multiple]")
@click.option("--push-to", default=[], metavar="REGISTRY", multiple=True,
              help="Registry to push to when image build completes.  [multiple]")
@click.option('--scratch', default=False, is_flag=True, help='Perform a scratch build.')
@pass_runtime
def distgits_build_images(runtime, repo_conf, push_to, scratch):
    """
    Attempts to build container images for all of the distgit repositories
    in a group. If an image has already been built, it will be treated as
    a successful operation.

    If docker registries as specified, this action will push resultant
    images to those mirrors as they become available. Note that this should
    be more performant than running distgits:push-images since pushes can
    be performed in parallel with other images building.
    """

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

    # Push all late images
    for image in runtime.images():
        image.distgit_repo().push_image(push_to, True)


@cli.command("distgits:push-images", short_help="Push the most recent images to mirrors.")
@click.option("--to", default=[], metavar="REGISTRY", multiple=True,
              help="Registry to push to when image build completes.  [multiple]")
@pass_runtime
def distgits_push_images(runtime, to):
    """
    Each distgit repository will be cloned and the version and release information
    will be extracted. That information will be used to determine the most recently
    built image associated with the distgit repository.

    An attempt will be made to pull that image and push it to one or more
    docker registries specified on the command line.
    """

    runtime.initialize()

    if len(to) == 0:
        click.echo("You need specify at least one destination registry.")
        exit(1)

    # Push early images
    for image in runtime.images():
        image.distgit_repo().push_image(to)

    # Push all late images
    for image in runtime.images():
        image.distgit_repo().push_image(to, True)


if __name__ == '__main__':
    cli(obj={})
