#!/usr/bin/env python

from packages import Runtime
from packages import Dir
from packages.image import pull_image
import click
import os
import yaml
import sys
import subprocess
import urllib
import traceback
from multiprocessing.dummy import Pool as ThreadPool
from dockerfile_parse import DockerfileParser

pass_runtime = click.make_pass_decorator(Runtime)


@click.group()
@click.option("--metadata-dir", metavar='PATH', default=os.getcwd(),
              help="Directory containing groups metadata directory if not current.")
@click.option("--working-dir", metavar='PATH', default=None,
              help="Existing directory in which file operations should be performed.")
@click.option("--user", metavar='USERNAME', default=None,
              help="Username for rhpkg.")
@click.option("--group", default=None, metavar='NAME',
              help="The group of images on which to operate.")
@click.option("--branch", default=None, metavar='BRANCH',
              help="Branch to override any default in group.yml.")
@click.option("-i", "--include", default=[], metavar='NAME', multiple=True,
              help="Name of group members to include in operation (all by default).")
@click.option("-o", "--optional-include", default=[], metavar='NAME', multiple=True,
              help="Name of group members to optionally include in operation. If not in current group, there will be no failure.")
@click.option("-x", "--exclude", default=[], metavar='NAME', multiple=True,
              help="Name of group members to exclude from operation (empty by default).")
@click.option('--verbose', '-v', default=False, is_flag=True, help='Enables verbose mode.')
@click.option('--no_oit_comment', default=False, is_flag=True,
              help='Do not place OIT comment in Dockerfile. Can also be set in each config.yml')
@click.pass_context
def cli(ctx, **kwargs):
    # @pass_runtime
    ctx.obj = Runtime(**kwargs)


option_commit_message = click.option("--message", "-m", metavar='MSG', help="Commit message for dist-git.", required=True)
option_push = click.option('--push/--no-push', default=False, is_flag=True,
                           help='Pushes to distgit after local changes (--no-push by default).')


@cli.command("distgits:clone", help="Clone a group's distgit repos locally.")
@pass_runtime
def distgits_clone(runtime):
    runtime.initialize()
    # Never delete after clone; defeats the purpose of cloning
    runtime.remove_tmp_working_dir = False
    [r.distgit_repo() for r in runtime.images()]


@cli.command("distgits:list", help="List of distgits being selected.")
@pass_runtime
def distgits_list(runtime):
    runtime.initialize()

    for image in runtime.images():
        click.echo(image.qualified_name)


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
@click.option("--version", metavar='VERSION', default=None, help="Version string to populate in Dockerfiles.")
@click.option("--release", metavar='RELEASE', default=None, help="Release label to populate in Dockerfiles (or + to bump).")
@click.option('--ignore-missing-base', default=False, is_flag=True, help='If a base image is not included, proceed and do not update FROM.')
@option_commit_message
@option_push
@pass_runtime
def distgits_update_dockerfile(runtime, stream, version, release, ignore_missing_base, message, push):
    """
    Updates the Dockerfile in each distgit repository with the latest metadata and
    the version/release information specified. This does not update the Dockerfile
    from any external source. For that, use distgits:rebase.

    Version:
    - If not specified, the current version is preserved.

    Release:
    - If not specified, the release label is removed.
    - If '+', the current release will be bumped.
    - Else, the literal value will be set in the Dockerfile.
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
        dgr.update_dockerfile(version, release, ignore_missing_base)
        dgr.commit(message)
        dgr.tag(version, release)

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
@click.option("--version", metavar='VERSION', help="Version string to populate in Dockerfiles.")
@click.option("--release", metavar='RELEASE', default=None, help="Release string to populate in Dockerfiles.")
@click.option('--ignore-missing-base', default=False, is_flag=True, help='If a base image is not included, proceed and do not update FROM.')
@option_commit_message
@option_push
@pass_runtime
def distgits_rebase(runtime, source, sources, stream, version, release, ignore_missing_base, message, push):
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
        dgr.rebase_dir(version, release, ignore_missing_base)
        sha = dgr.commit(message, log_diff=True)
        dgr.tag(version, release)
        runtime.add_record("distgit_commit", distgit=dgr.metadata.qualified_name,
                           image=dgr.config.name, sha=sha)

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

    # If not pushing, do not clean up our work
    runtime.remove_tmp_working_dir = push

    cmd_str = " ".join(cmd)
    dgrs = [image.distgit_repo() for image in runtime.images()]
    for dgr in dgrs:
        with Dir(dgr.distgit_dir):
            runtime.info("Executing in %s: [%s]" % (dgr.distgit_dir, cmd_str))
            if subprocess.call(cmd_str, shell=True) != 0:
                raise IOError("Command return non-zero status")
            runtime.info("\n")

        if message is not None:
            dgr.commit(message)

    if push:
        for image in runtime.images():
            dgr = image.distgit_repo()
            dgr.push()


@cli.command("distgits:copy", help="Copy content of source branch to target.")
@click.option("--to-branch", metavar="TARGET_BRANCH", help="Branch to populate from source branch.")
@click.option("--replace", metavar="MATCH REPLACEMENT", nargs=2, multiple=True, default=None,
              help="String replacement in target Dockerfile.  [multiple]")
@option_commit_message
@option_push
@pass_runtime
def distgits_copy(runtime, to_branch, message, push, replace):
    """
    For each distgit repo, copies the content of the group's branch to a new
    branch.
    """
    runtime.initialize()

    if replace is not None:
        raise IOError("'--replace' option not yet implemented")

    # If not pushing, do not clean up our work
    runtime.remove_tmp_working_dir = push

    dgrs = [image.distgit_repo() for image in runtime.images()]
    for dgr in dgrs:
        with Dir(dgr.distgit_dir):
            runtime.info("Copying from branch {} to {}".format(dgr.branch, to_branch))
            dgr.copy_branch(to_branch)
            runtime.info("\n")

        if message is not None:
            dgr.commit(message)

    if push:
        for dgr in dgrs:
            dgr.push()


@cli.command("distgits:build-images", short_help="Build images for the group.")
@click.option("--repo_type", required=True, metavar="REPO_TYPE",
              help="Repo type (i.e. signed, unsigned).")
@click.option('--push-to-defaults', default=False, is_flag=True, help='Push to default registries when build completes.')
@click.option("--push-to", default=[], metavar="REGISTRY", multiple=True,
              help="Specific registries to push to when image build completes.  [multiple]")
@click.option('--scratch', default=False, is_flag=True, help='Perform a scratch build.')
@pass_runtime
def distgits_build_images(runtime, repo_type, push_to_defaults, push_to, scratch):
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

    push_to = list(push_to)  # In case we get a tuple
    if push_to_defaults:
        push_to.extend(runtime.default_registries)

    # Initialize all distgit directories before trying to build. This is to
    # ensure all build locks are acquired before the builds start and for
    # clarity in the logs.
    for image in runtime.images():
        items.append((image.distgit_repo(), (repo_type, push_to, scratch)))

    pool = ThreadPool(len(items))
    results = pool.map(lambda ((dgr, args)): dgr.build_container(*args), items)

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
@click.option('--to-defaults', default=False, is_flag=True, help='Push to default registries.')
@click.option("--to", default=[], metavar="REGISTRY", multiple=True,
              help="Registry to push to when image build completes.  [multiple]")
@pass_runtime
def distgits_push_images(runtime, to_defaults, to):
    """
    Each distgit repository will be cloned and the version and release information
    will be extracted. That information will be used to determine the most recently
    built image associated with the distgit repository.

    An attempt will be made to pull that image and push it to one or more
    docker registries specified on the command line.
    """

    runtime.initialize()

    to = list(to)  # In case we get a tuple
    if to_defaults:
        to.extend(runtime.default_registries)

    if len(to) == 0:
        click.echo("You need specify at least one destination registry.")
        exit(1)

    # Allow all non-late push operations to be attempted and track overall failure
    # with this boolean. Since "late" images are used as a marker for success, don't
    # push them if there are any preceding errors.
    # This error tolerance is useful primarily in synching images that our team
    # does not build but which should be kept up to date in the operations registry.
    errors = False

    # Push early images
    for image in runtime.images():
        try:
            image.distgit_repo().push_image(to)
        except Exception as err:
            print(traceback.format_exc())
            errors = True

    if errors:
        raise IOError("At least one image push failed")

    # Push all late images
    for image in runtime.images():
        image.distgit_repo().push_image(to, True)


@cli.command("distgits:pull-images", short_help="Pull latest images from pulp")
@pass_runtime
def distgits_pull_images(runtime):
    """
    Pulls latest images from pull, fetching the dockerfiles from cgit to
    determine the version/release.
    """
    runtime.initialize()
    for image in runtime.images():
        image.pull_image()


@cli.command("distgits:scan-for-cves", short_help="Scan images with openscap")
@pass_runtime
def distgits_scan_for_cves(runtime):
    """
    Pulls images and scans them for CVEs using `atomic scan` and `openscap`.
    """
    runtime.initialize()
    images = [x.pull_url() for x in runtime.images()]
    for image in images:
        pull_image(runtime, image)
    subprocess.check_call(["atomic", "scan"] + images)


@cli.command("distgits:print", short_help="Print data from each distgit.")
@click.argument("pattern", nargs=1)
@pass_runtime
def distgits_print(runtime, pattern):
    """
    Prints data from each distgit. The pattern specified should be a string
    with replacement fields:

    \b
    {type} - The type of the distgit (e.g. rpms)
    {name} - The name of the distgit repository (e.g. openshift-enterprise-docker)
    {image} - The image name in the Dockerfile
    {version} - The version field in the Dockerfile
    {release} - The release field in the Dockerfile
    {build} - Shorthand for {name}-{version}-{release} (e.g. container-engine-docker-v3.6.173.0.25-1)
    {repository} - Shorthand for {image}:{version}-{release}

    If pattern contains no braces, it will be wrapped with them automatically. For example:
    "build" will be treated as "{build}"
    """

    runtime.initialize()

    # If user omitted braces, add them.
    if "{" not in pattern:
        pattern = "{%s}" % pattern.strip()

    click.echo("")
    click.echo("------------------------------------------")
    for image in runtime.images():
        dfp = DockerfileParser()
        dfp.content = image.fetch_cgit_file("Dockerfile")
        s = pattern
        s = s.replace("{build}", "{name}-{version}-{release}")
        s = s.replace("{repository}", "{image}:{version}-{release}")
        s = s.replace("{type}", image.type)
        s = s.replace("{name}", image.name)
        s = s.replace("{image}", dfp.labels["name"])
        s = s.replace("{version}", dfp.labels["version"])
        s = s.replace("{release}", image.get_latest_build_release(dfp))

        if "{" in s:
            raise IOError("Unrecognized fields remaining in pattern: %s" % s)

        click.echo(s)

    click.echo("------------------------------------------")


@cli.command("print-config-template", short_help="Create template config.yml from distgit Dockerfile.")
@click.argument("url", nargs=1)
def distgit_config_template(url):
    """
    Pulls the specified URL (to a Dockerfile in distgit) and prints the boilerplate
    for a config.yml for the image.
    """

    f = urllib.urlopen(url)
    if f.code != 200:
        click.echo("Error fetching {}: {}".format(url, f.code), err=True)
        exit(1)

    dfp = DockerfileParser()
    dfp.content = f.read()

    if "cgit/rpms/" in url:
        type = "rpms"
    elif "cgit/apbs/" in url:
        type = "apbs"
    else:
        raise IOError("oit does not yet support that distgit repo type")

    config = {
        "repo": {
            "type": type,
        },
        "name": dfp.labels['name'],
        "from": {
            "image": dfp.baseimage
        },
        "labels": {},
        "owners": []
    }

    branch = url[url.index("?h=") + 3:]

    managed_labels = [
        'vendor',
        'License',
        'architecture',
        'io.k8s.display-name',
        'io.k8s.description',
        'io.openshift.tags'
    ]

    for ml in managed_labels:
        if ml in dfp.labels:
            config["labels"][ml] = dfp.labels[ml]

    click.echo("---")
    click.echo("# populated from branch: %s" % branch)
    yaml.safe_dump(config, sys.stdout, indent=2, default_flow_style=False)


if __name__ == '__main__':
    cli(obj={})
