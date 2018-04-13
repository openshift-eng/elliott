#!/usr/bin/env python

from ocp_cd_tools import Runtime, Dir
from ocp_cd_tools.image import pull_image, create_image_verify_repo_file, Image
from ocp_cd_tools.common import get_watch_task_info_copy
import datetime
import click
import os
import yaml
import sys
import subprocess
import urllib
import traceback
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing import cpu_count
from dockerfile_parse import DockerfileParser

pass_runtime = click.make_pass_decorator(Runtime)
context_settings = dict(help_option_names=['-h', '--help'])


@click.group(context_settings=context_settings)
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
@click.option('--stage', default=False, is_flag=True, help='Force checkout stage branch for sources in group.yml.')
@click.option("-i", "--images", default=[], metavar='NAME', multiple=True,
              help="Name of group image member to include in operation (all by default). Can be comma delimited list.")
@click.option("-r", "--rpms", default=[], metavar='NAME', multiple=True,
              help="Name of group rpm member to include in operation (all by default). Can be comma delimited list.")
@click.option("-x", "--exclude", default=[], metavar='NAME', multiple=True,
              help="Name of group image or rpm member to exclude in operation (none by default). Can be comma delimited list.")
@click.option('--ignore-missing-base', default=False, is_flag=True,
              help='If a base image is not included, proceed and do not update FROM.')
@click.option("--quiet", "-q", default=False, is_flag=True, help="Suppress non-critical output")
@click.option('--verbose', '-v', default=False, is_flag=True, help='Enables verbose mode.')
@click.option('--no_oit_comment', default=False, is_flag=True,
              help='Do not place OIT comment in Dockerfile. Can also be set in each config yaml')
@click.option("--source", metavar="ALIAS PATH", nargs=2, multiple=True,
              help="Associate a path with a given source alias.  [multiple]")
@click.option("--sources", metavar="YAML_PATH",
              help="YAML dict associating sources with their alias. Same as using --source multiple times.")
@click.pass_context
def cli(ctx, **kwargs):
    # @pass_runtime
    ctx.obj = Runtime(**kwargs)


option_commit_message = click.option("--message", "-m", metavar='MSG', help="Commit message for dist-git.",
                                     required=True)
option_push = click.option('--push/--no-push', default=False, is_flag=True,
                           help='Pushes to distgit after local changes (--no-push by default).')


@cli.command("images:clone", help="Clone a group's image distgit repos locally.")
@pass_runtime
def images_clone(runtime):
    runtime.initialize(clone_distgits=True)
    # Never delete after clone; defeats the purpose of cloning
    runtime.remove_tmp_working_dir = False


@cli.command("rpms:clone", help="Clone a group's rpm distgit repos locally.")
@pass_runtime
def rpms_clone(runtime):
    runtime.initialize(mode='rpms', clone_distgits=True)
    # Never delete after clone; defeats the purpose of cloning
    runtime.remove_tmp_working_dir = False


@cli.command("rpms:clone-sources", help="Clone a group's rpm source repos locally and add to sources yaml.")
@click.option("--output-yml", metavar="YAML_PATH",
              help="Output yml file to write sources dict to. Can be same as --sources option but must be explicitly specified.")
@pass_runtime
def rpms_clone_sources(runtime, output_yml):
    runtime.initialize(mode='rpms')
    # Never delete after clone; defeats the purpose of cloning
    runtime.remove_tmp_working_dir = False
    [r for r in runtime.rpm_metas()]
    if output_yml:
        runtime.export_sources(output_yml)


@cli.command("rpms:build", help="Build rpms in the group or given by --rpms.")
@click.option("--version", metavar='VERSION', default=None,
              help="Version string to populate in specfile.", required=True)
@click.option("--release", metavar='RELEASE', default=None,
              help="Release label to populate in specfile.", required=True)
@click.option('--scratch', default=False, is_flag=True, help='Perform a scratch build.')
@pass_runtime
def rpms_build(runtime, version, release, scratch):
    """
    Attempts to build rpms for all of the defined rpms
    in a group. If an rpm has already been built, it will be treated as
    a successful operation.
    """

    if version.startswith('v'):
        version = version[1:]

    runtime.initialize(mode='rpms', clone_distgits=False)

    items = runtime.rpm_metas()
    if not items:
        runtime.info("No RPMs found. Check the arguments.")
        exit(0)

    results = runtime.parallel_exec(
        lambda (rpm, terminate_event): rpm.build_rpm(
            version, release, terminate_event, scratch),
        items)
    results = results.get()
    failed = [m.name for m, r in zip(runtime.rpm_metas(), results) if not r]
    if failed:
        runtime.info("\n".join(["Build/push failures:"] + sorted(failed)))
        exit(1)


@cli.command("images:list", help="List of distgits being selected.")
@pass_runtime
def images_list(runtime):
    runtime.initialize(clone_distgits=False)

    click.echo("------------------------------------------")
    for image in runtime.image_metas():
        click.echo(image.qualified_name)
    click.echo("------------------------------------------")
    click.echo("%s images" % len(runtime.image_metas()))


@cli.command("images:push-distgit", short_help="Push all distgist repos in working-dir.")
@pass_runtime
def images_push_distgit(runtime):
    """
    Run to execute an rhpkg push on all locally cloned distgit
    repositories. This is useful following a series of modifications
    in the local clones.
    """
    runtime.initialize(clone_distgits=True)
    runtime.push_distgits()


@cli.command("images:update-dockerfile", short_help="Update a group's distgit Dockerfile from metadata.")
@click.option("--stream", metavar="ALIAS REPO/NAME:TAG", nargs=2, multiple=True,
              help="Associate an image name with a given stream alias.  [multiple]")
@click.option("--version", metavar='VERSION', default=None,
              help="Version string to populate in Dockerfiles. \"auto\" gets version from atomic-openshift RPM")
@click.option("--release", metavar='RELEASE', default=None,
              help="Release label to populate in Dockerfiles (or + to bump).")
@click.option("--repo-type", default=None, metavar="REPO_TYPE",
              help="Repo group type to use for version autodetection scan (e.g. signed, unsigned).")
@option_commit_message
@option_push
@pass_runtime
def images_update_dockerfile(runtime, stream, version, release, repo_type, message, push):
    """
    Updates the Dockerfile in each distgit repository with the latest metadata and
    the version/release information specified. This does not update the Dockerfile
    from any external source. For that, use images:rebase.

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

    # Get the version from the atomic-openshift package in the RPM repo
    if version == "auto":
        version = runtime.auto_version(repo_type)

    if version and not runtime.valid_version(version):
        raise ValueError(
            "invalid version string: {}, expecting like v3.4 or v1.2.3".format(version)
        )

    runtime.clone_distgits()
    for image in runtime.image_metas():
        dgr = image.distgit_repo()
        (real_version, real_release) = dgr.update_dockerfile(version, release)
        dgr.commit(message)
        dgr.tag(real_version, real_release)

    if push:
        runtime.push_distgits()


@cli.command("images:verify", short_help="Run some smoke tests to verify produced images")
@click.option("--image", "-i", metavar="REPO/NAME:TAG", multiple=True,
              help="Run a manual scan of one or more specific images [multiple]")
@click.option("--no-pull", is_flag=True,
              help="Assume image has already been pulled (Just-in-time pulling)")
@click.option("--repo-type", default='signed',
              help="Repo type (e.g. signed, unsigned). Use 'unsigned' for newer releases like 3.9 until they're GA")
@click.option('--check-orphans', default=None, is_flag=True,
              help="Verify no packages are orphaned (installed without a source repo) [SLOW]")
@click.option('--check-sigs', default=None, is_flag=True,
              help="Verify that all installed packages are signed with a valid key")
@click.option('--check-versions', default=None, is_flag=True,
              help="Verify that installed package versions match the target release")
@pass_runtime
def images_verify(runtime, image, no_pull, repo_type, **kwargs):
    """Catches mistakes in images (see the --check-FOO options) before we
    ship them on to QE for further verification. This command roughly
    approximates the image check job ran on the QE Jenkins.

    Ensure you provide a `--working-dir` if you want to retain the
    test reports. Some useful artifacts are produced in the
    `working-dir`: debug.log: The full verbose log of all
    operations. verify_fail_log.yml: Failed images check
    details. verify_full_log.yml: Full image check details.

    EXAMPLES

    * Run all checks on all the lastest openshift-3.9 group images:

      $ oit.py --group openshift-3.9 images:verify

    * ONLY the package signature check:

      $ oit.py --group openshift-3.9 images:verify --check-sigs

    * All tests on a SPECIFIC image:

      \b
      $ oit.py --group openshift-3.4 images:verify --image reg.rh.com:8888/openshift3/ose:v3.4.1.44.38-12

    Exit code is the number of images that failed the image check

    """
    # * Job: https://openshift-qe-jenkins.rhev-ci-vms.eng.rdu2.redhat.com/job/v3-errata-image-test/
    # * Source: git://git.app.eng.bos.redhat.com/openshift-misc.git/openshift-misc/v3-errata-image-test/v3-errata-image-test.sh
    runtime.initialize(clone_distgits=False)
    # Parse those check options. All None indicates we run everything,
    # True then we only run the True checks.
    if not any(kwargs.values()):
        enabled_checks = kwargs.keys()
    else:
        enabled_checks = list(k for k, v in kwargs.items() if v)

    repo_file = create_image_verify_repo_file(runtime, repo_type=repo_type)

    # Doing this manually, or automatic on a group?
    if len(image) == 0:
        images = [Image(runtime, x.pull_url(), repo_file, enabled_checks) for x in runtime.image_metas()]
    else:
        images = [Image(runtime, img, repo_file, enabled_checks) for img in image]

    # Don't pre-pull images, useful during development iteration. If
    # --no-pull isn't given, then we will pre-pull all images.
    if not no_pull:
        for image in images:
            pull_image(runtime, image.pull_url)

    count_images = len(images)
    runtime.info("[Verify] Running verification checks on {count} images: {chks}".format(count=count_images, chks=", ".join(enabled_checks)))

    pool = ThreadPool(cpu_count())
    results = pool.map(
        lambda img: img.verify_image(),
        images)
    # Wait for results
    pool.close()
    pool.join()

    ######################################################################
    # Done! Let's begin accounting and recording
    failed_images = [img for img in results if img['status'] == 'failed']
    failed_images_count = len(failed_images)

    fail_log = os.path.join(runtime.working_dir, 'verify_fail_log.yml')

    runtime.info("[Verify] Checks finished. {fail_count} failed".format(fail_count=failed_images_count))

    if failed_images_count > 0:
        runtime.remove_tmp_working_dir = False
        fail_log_data = {
            'test_date': str(datetime.datetime.now()),
            'data': failed_images
        }

        with open(fail_log, 'w') as fp:
            fp.write(yaml.safe_dump(fail_log_data, indent=4, default_flow_style=False))
            runtime.info("[Verify] Failed images check details: {fail_log}".format(fail_log=fail_log))

    exit(failed_images_count)


@cli.command("images:rebase", short_help="Refresh a group's distgit content from source content.")
@click.option("--stream", metavar="ALIAS REPO/NAME:TAG", nargs=2, multiple=True,
              help="Associate an image name with a given stream alias.  [multiple]")
@click.option("--version", metavar='VERSION', default=None,
              help="Version string to populate in Dockerfiles. \"auto\" gets version from atomic-openshift RPM")
@click.option("--release", metavar='RELEASE', default=None, help="Release string to populate in Dockerfiles.")
@click.option("--repo-type", default=None, metavar="REPO_TYPE",
              help="Repo group type to use for version autodetection scan (e.g. signed, unsigned).")
@option_commit_message
@option_push
@pass_runtime
def images_rebase(runtime, stream, version, release, repo_type, message, push):
    """
    Many of the Dockerfiles stored in distgit are based off of content managed in GitHub.
    For example, openshift-enterprise-node-docker should always closely reflect the changes
    being made upstream in github.com/openshift/ose/images/node. This operation
    goes out and pulls the current source Dockerfile (and potentially other supporting
    files) into distgit and applies any transformations defined in the config yaml associated
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

    # For each "--stream alias image" on the command line, register its existence with
    # the runtime.
    for s in stream:
        runtime.register_stream_alias(s[0], s[1])

    # Get the version from the atomic-openshift package in the RPM repo
    if version == "auto":
        version = runtime.auto_version(repo_type)

    if not runtime.valid_version(version):
        raise ValueError(
            "invalid version string: {}, expecting like v3.4 or v1.2.3".format(version)
        )

    runtime.clone_distgits()
    for image in runtime.image_metas():
        dgr = image.distgit_repo()
        (real_version, real_release) = dgr.rebase_dir(version, release)
        sha = dgr.commit(message, log_diff=True)
        dgr.tag(real_version, real_release)
        runtime.add_record("distgit_commit", distgit=dgr.metadata.qualified_name,
                           image=dgr.config.name, sha=sha)

    if push:
        runtime.push_distgits()


@cli.command("images:foreach", help="Run a command relative to each distgit dir.")
@click.argument("cmd", nargs=-1)
@click.option("--message", "-m", metavar='MSG', help="Commit message for dist-git.", required=False)
@option_push
@pass_runtime
def images_foreach(runtime, cmd, message, push):
    """
    Clones all distgit repos found in the specified group and runs an arbitrary
    command once for each local distgit directory. If the command runs without
    error for all directories, a commit will be made. If not a dry_run,
    the repo will be pushed.
    """
    runtime.initialize(clone_distgits=True)

    # If not pushing, do not clean up our work
    runtime.remove_tmp_working_dir = push

    cmd_str = " ".join(cmd)
    dgrs = [image.distgit_repo() for image in runtime.image_metas()]
    for dgr in dgrs:
        with Dir(dgr.distgit_dir):
            runtime.info("Executing in %s: [%s]" % (dgr.distgit_dir, cmd_str))
            if subprocess.call(cmd_str, shell=True) != 0:
                raise IOError("Command return non-zero status")
            runtime.info("\n")

        if message is not None:
            dgr.commit(message)

    if push:
        runtime.push_distgits()


@cli.command("images:revert", help="Revert a fixed number of commits in each distgit.")
@click.argument("count", nargs=1)
@click.option("--message", "-m", metavar='MSG', help="Commit message for dist-git.", default=None, required=False)
@option_push
@pass_runtime
def images_revert(runtime, count, message, push):
    """
    Revert a particular number of commits in each distgit repository. If
    a message is specified, a new commit will be made.
    """
    runtime.initialize()

    # If not pushing, do not clean up our work
    runtime.remove_tmp_working_dir = push

    count = int(count) - 1
    if count < 0:
        runtime.info("Revert count must be >= 1")

    if count == 0:
        commit_range = "HEAD"
    else:
        commit_range = "HEAD~%s..HEAD" % count

    cmd = ["git", "revert", "--no-commit", commit_range]

    cmd_str = " ".join(cmd)
    runtime.clone_distgits()
    dgrs = [image.distgit_repo() for image in runtime.image_metas()]
    for dgr in dgrs:
        with Dir(dgr.distgit_dir):
            runtime.info("Running revert in %s: [%s]" % (dgr.distgit_dir, cmd_str))
            if subprocess.call(cmd_str, shell=True) != 0:
                raise IOError("Command return non-zero status")
            runtime.info("\n")

        if message is not None:
            dgr.commit(message)

    if push:
        runtime.push_distgits()


@cli.command("images:merge-branch", help="Copy content of source branch to target.")
@click.option("--target", metavar="TARGET_BRANCH", help="Branch to populate from source branch.")
@click.option('--allow-overwrite', default=False, is_flag=True,
              help='Merge in source branch even if Dockerfile already exists in distgit')
@option_push
@pass_runtime
def images_merge(runtime, target, push, allow_overwrite):
    """
    For each distgit repo, copies the content of the group's branch to a new
    branch.
    """
    runtime.initialize()

    # If not pushing, do not clean up our work
    runtime.remove_tmp_working_dir = push

    runtime.clone_distgits()
    dgrs = [image.distgit_repo() for image in runtime.image_metas()]
    for dgr in dgrs:
        with Dir(dgr.distgit_dir):
            dgr.info("Merging from branch {} to {}".format(dgr.branch, target))
            dgr.merge_branch(target, allow_overwrite)
            runtime.info("\n")

    if push:
        runtime.push_distgits()


def print_build_metrics(runtime):
    watch_task_info = get_watch_task_info_copy()
    runtime.info("\nImage build metrics:")
    runtime.info("Number of brew tasks: {}".format(len(watch_task_info)))

    # Make sure all the tasks have the expected timestamps:
    # https://github.com/openshift/enterprise-images/pull/178#discussion_r173812940
    for task_id in watch_task_info.keys():
        info = watch_task_info[task_id]
        runtime.log_verbose("Watch task info:\n {}\n\n".format(info))
        if 'create_ts' not in info or 'completion_ts' not in info or 'create_ts' not in info or 'id' not in info:
            runtime.info("Error finding timestamps in task info: {}".format(info))
            del watch_task_info[task_id]

    # An estimate of how long the build time was extended due to FREE state (i.e. waiting for capacity)
    elapsed_wait_minutes = 0

    # If two builds each take one minute of actual active CPU time to complete, this value will be 2.
    aggregate_build_secs = 0

    # If two jobs wait 1m for in FREE state, this value will be '2' even if
    # the respective wait periods overlap. This is different from elapsed_wait_minutes
    # which is harder to calculate.
    aggregate_wait_secs = 0

    # Will be populated with earliest creation timestamp found in all the koji tasks; initialize with
    # infinity to support min() logic.
    min_create_ts = float('inf')

    # Will be populated with the latest completion timestamp found in all the koji tasks
    max_completion_ts = 0

    # Loop through all koji task infos and calculate min
    for task_id, info in watch_task_info.iteritems():
        create_ts = info['create_ts']
        completion_ts = info['completion_ts']
        start_ts = info['start_ts']
        min_create_ts = min(create_ts, min_create_ts)
        max_completion_ts = max(completion_ts, max_completion_ts)
        build_secs = completion_ts - start_ts
        aggregate_build_secs += build_secs
        wait_secs = start_ts - create_ts
        aggregate_wait_secs += wait_secs

        runtime.info('Task {} took {:.1f}m of active build and was waiting to start for {:.1f}m'.format(task_id,
                                                                                                 build_secs / 60.0,
                                                                                                 wait_secs / 60.0)
                     )
    runtime.info('Aggregate time all builds spent building {:.1f}m'.format(aggregate_build_secs / 60.0))
    runtime.info('Aggregate time all builds spent waiting {:.1f}m'.format(aggregate_wait_secs / 60.0))

    # If we successfully found timestamps
    if watch_task_info:

        # For each minute which elapsed between the first build created (min_create_ts) to the
        # last build to complete (max_completion_ts), check whether there was any build that
        # was created but still waiting to start (i.e. in FREE state). If there is a build
        # waiting, include that minute in the elapsed wait time.

        for ts in xrange(int(min_create_ts), int(max_completion_ts), 60):
            # See if any of the tasks were created but not started during this minute
            for info in watch_task_info.itervalues():
                create_ts = int(info['create_ts'])
                start_ts = int(info['start_ts'])
                # Was the build waiting to start during this minute?
                if create_ts <= ts <= start_ts:
                    # Increment and exit; we don't want to count overlapping wait periods
                    # since it would not accurately reflect the overall time savings we could
                    # expect with more capacity.
                    elapsed_wait_minutes += 1
                    break

        runtime.info("Approximate elapsed time (wasted) waiting: {}m".format(elapsed_wait_minutes))
        elapsed_total_minutes = (max_completion_ts - min_create_ts) / 60.0
        runtime.info("Elapsed time (from first submit to last completion) for all builds: {:.1f}m".format(elapsed_total_minutes))

        runtime.add_record("image_build_metrics", elapsed_wait_minutes=int(elapsed_wait_minutes),
                           elapsed_total_minutes=int(elapsed_total_minutes), task_count=len(watch_task_info))
    else:
        runtime.info('Unable to determine timestamps from collected info: {}'.format(watch_task_info))


@cli.command("images:build", short_help="Build images for the group.")
@click.option("--repo-type", default=None, metavar="REPO_TYPE",
              help="Repo type (e.g. signed, unsigned).")
@click.option("--repo", default=[], metavar="REPO_URL",
              multiple=True, help="Custom repo URL to supply to brew build.")
@click.option('--push-to-defaults', default=False, is_flag=True,
              help='Push to default registries when build completes.')
@click.option("--push-to", default=[], metavar="REGISTRY", multiple=True,
              help="Specific registries to push to when image build completes.  [multiple]")
@click.option('--scratch', default=False, is_flag=True, help='Perform a scratch build.')
@pass_runtime
def images_build_image(runtime, repo_type, repo, push_to_defaults, push_to, scratch):
    """
    Attempts to build container images for all of the distgit repositories
    in a group. If an image has already been built, it will be treated as
    a successful operation.

    If docker registries as specified, this action will push resultant
    images to those mirrors as they become available. Note that this should
    be more performant than running images:push since pushes can
    be performed in parallel with other images building.

    Tips on using custom --repo.
    1. Upload a .repo file into a public repository on github.com (it must end in .repo)
       with your desired yum repos enabled.
    2. Specify the raw URL for the build.
    3. You will probably want to use --scratch since it is unlikely you want your
        custom build tagged.
    """
    # Initialize all distgit directories before trying to build. This is to
    # ensure all build locks are acquired before the builds start and for
    # clarity in the logs.
    runtime.initialize(clone_distgits=True)

    push_to = list(push_to)  # In case we get a tuple
    if push_to_defaults:
        push_to.extend(runtime.default_registries)

    items = [m.distgit_repo() for m in runtime.image_metas()]
    if not items:
        runtime.info("No images found. Check the arguments.")
        exit(1)

    # Without one of these two arguments, brew would not enable any repos.
    if not repo_type and not repo:
        runtime.info("No repos specified. --repo-type or --repo is required.")
        exit(1)

    results = runtime.parallel_exec(
        lambda (dgr, terminate_event): dgr.build_container(
            repo_type, repo, push_to, terminate_event, scratch),
        items)
    results = results.get()
    failed = [m.name for m, r in zip(runtime.image_metas(), results) if not r]
    if failed:
        runtime.info("\n".join(["Build/push failures:"] + sorted(failed)))
        exit(1)

    # Push all late images
    for image in runtime.image_metas():
        image.distgit_repo().push_image([], push_to, push_late=True)

    try:
        print_build_metrics(runtime)
    except:
        # Never kill a build because of bad logic in metrics
        traceback.print_exc()
        runtime.info("Error trying to show build metrics")


@cli.command("images:push", short_help="Push the most recent images to mirrors.")
@click.option('--tag', default=[], metavar="PUSH_TAG", multiple=True,
              help='Push to registry using these tags instead of default set.')
@click.option('--to-defaults', default=False, is_flag=True, help='Push to default registries.')
@click.option('--late-only', default=False, is_flag=True, help='Push only "late" images.')
@click.option("--to", default=[], metavar="REGISTRY", multiple=True,
              help="Registry to push to when image build completes.  [multiple]")
@pass_runtime
def images_push(runtime, tag, to_defaults, late_only, to):
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
    runtime.clone_distgits()

    # late-only is useful if we are resuming a partial build in which not all images
    # can be built/pushed. Calling images:push can end up hitting the same
    # push error, so, without late-only, there is no way to push "late" images and
    # deliver the partial build's last images.
    if not late_only:
        # Allow all non-late push operations to be attempted and track failures
        # with this list. Since "late" images are used as a marker for success,
        # don't push them if there are any preceding errors.
        # This error tolerance is useful primarily in synching images that our
        # team does not build but which should be kept up to date in the
        # operations registry.
        failed = []
        # Push early images
        for image in runtime.image_metas():
            try:
                image.distgit_repo().push_image(tag, to)
            except Exception:
                traceback.print_exc()
                failed.append(image.name)

        if failed:
            runtime.info("\n".join(["Push failures:"] + sorted(failed)))
            exit(1)

    # Push all late images
    for image in runtime.image_metas():
        # Check if actually a late image to prevent cloning all distgit on --late-only
        if image.config.push.late is True:
            image.distgit_repo().push_image(tag, to, push_late=True)


@cli.command("images:pull", short_help="Pull latest images from pulp")
@pass_runtime
def images_pull_image(runtime):
    """
    Pulls latest images from pull, fetching the dockerfiles from cgit to
    determine the version/release.
    """
    runtime.initialize(clone_distgits=True)
    for image in runtime.image_metas():
        image.pull_image()


@cli.command("images:scan-for-cves", short_help="Scan images with openscap")
@pass_runtime
def images_scan_for_cves(runtime):
    """
    Pulls images and scans them for CVEs using `atomic scan` and `openscap`.
    """
    runtime.initialize(clone_distgits=True)
    images = [x.pull_url() for x in runtime.image_metas()]
    for image in images:
        pull_image(runtime, image)
    subprocess.check_call(["atomic", "scan"] + images)


@cli.command("images:print", short_help="Print data from each distgit.")
@click.option(
    "--short", default=False, is_flag=True,
    help="Suppress all output other than the data itself")
@click.option('--show-non-release', default=False, is_flag=True,
              help='Include images which have been marked as non-release.')
@click.argument("pattern", nargs=1)
@pass_runtime
def images_print(runtime, short, show_non_release, pattern):
    """
    Prints data from each distgit. The pattern specified should be a string
    with replacement fields:

    \b
    {type} - The type of the distgit (e.g. rpms)
    {name} - The name of the distgit repository (e.g. openshift-enterprise-docker)
    {component} - The component identified in the Dockerfile
    {image} - The image name in the Dockerfile
    {version} - The version field in the Dockerfile
    {release} - The release field in the Dockerfile
    {build} - Shorthand for {component}-{version}-{release} (e.g. container-engine-docker-v3.6.173.0.25-1)
    {repository} - Shorthand for {image}:{version}-{release}

    If pattern contains no braces, it will be wrapped with them automatically. For example:
    "build" will be treated as "{build}"
    """

    runtime.initialize(clone_distgits=True)

    # If user omitted braces, add them.
    if "{" not in pattern:
        pattern = "{%s}" % pattern.strip()

    count = 0
    if short:
        echo_verbose = lambda _: None
    else:
        echo_verbose = click.echo

    echo_verbose("")
    echo_verbose("------------------------------------------")

    non_release_images = runtime.group_config.get('non_release', [])
    if not show_non_release:
        images = [i for i in runtime.image_metas() if i.name not in non_release_images]
    else:
        images = list(runtime.image_metas())

    for image in images:
        dfp = DockerfileParser()
        dfp.content = image.fetch_cgit_file("Dockerfile")

        s = pattern
        s = s.replace("{build}", "{component}-{version}-{release}")
        s = s.replace("{repository}", "{image}:{version}-{release}")
        s = s.replace("{namespace}", image.namespace)
        s = s.replace("{name}", image.name)
        s = s.replace("{component}", image.get_component_name())
        s = s.replace("{image}", dfp.labels["name"])
        s = s.replace("{version}", dfp.labels["version"])

        # Since querying release takes time, check before executing replace
        if "{release}" in s:
            _, _, release = image.get_latest_build_info()
            s = s.replace("{release}", release)

        if "{" in s:
            raise IOError("Unrecognized fields remaining in pattern: %s" % s)

        click.echo(s)
        count += 1

    echo_verbose("------------------------------------------")
    echo_verbose("{} images".format(count))

    if not show_non_release:
        echo_verbose("\nThe following {} non-release images were excluded; use --show-non-release to include them:".format(
                len(non_release_images)))
        for image in non_release_images:
            echo_verbose("    {}".format(image))


@cli.command("images:print-config-template", short_help="Create template package yaml from distgit Dockerfile.")
@click.argument("url", nargs=1)
def distgit_config_template(url):
    """
    Pulls the specified URL (to a Dockerfile in distgit) and prints the boilerplate
    for a config yaml for the image.
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

    if "Architecture" in dfp.labels:
        dfp.labels["architecture"] = dfp.labels["Architecture"]

    component = dfp.labels.get("com.redhat.component", dfp.labels.get("BZComponent", None))

    if component is not None:
        config["repo"]["component"] = component

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
    click.echo("# populated from branch: {}".format(branch))
    yaml.safe_dump(config, sys.stdout, indent=2, default_flow_style=False)


@cli.command(
    "completion", short_help="Output bash completion function",
    help="""\
Generate a bash function for auto-completion on the command line. The output
is formatted so that it can be fed to the shell's `source` command directly:

    $ source <(/path/to/oit completion)
""")
def completion():
    basename = os.path.basename(sys.argv[0])
    click.echo("""\
_oit_completion() {
    local cmd word prev mdir group types
    cmd=$1; word=$2; prev=$3
    set -- "${COMP_WORDS[@]}"
    mdir=groups; group=
    while [[ "${#}" -gt 0 ]]; do
        case "${1}" in
            --metadata-dir) mdir=${2}; shift; shift; ;;
            --group) group=${2}; shift; shift; ;;
            *) shift;
        esac
    done
    case "${prev}" in
        -i|--images) types=images ;;
        -r|--rpms) types=rpms ;;
        -x|--exclude) types='images rpms' ;;
        --group)
            if [ -d "${mdir}" ]; then
                COMPREPLY=( $(compgen -W "$(ls "${mdir}")" -- "${word}") )
            fi
            return ;;
        *) COMPREPLY=( $(env \
                COMP_WORDS="${COMP_WORDS[*]}" \
                COMP_CWORD=$COMP_CWORD \
                _%s_COMPLETE=complete "${cmd}") )
            return ;;
    esac
    group=$(echo "${group}" | tr , '\n')
    group=$( \
        cd "${mdir}" \
        && for g in ${group:-*}; do \
            for t in ${types}; do \
                if [[ -d "${g}/${t}" ]]; then \
                    basename --multiple --suffix .yml "${g}/${t}"/*; \
                fi \
            done \
        done \
        | sort -u)
    COMPREPLY=( $(compgen -W "${group}" -- "${word}") )
}
complete -F _oit_completion -o default %s
""" % (basename.replace("-", "_").upper(), basename))


@cli.command("images:query-rpm-version", short_help="Find the OCP version from the atomic-openshift RPM")
@click.option("--repo-type", required=True, metavar="REPO_TYPE",
              help="Repo group to scan for the RPM (e.g. signed, unsigned).")
@pass_runtime
def query_rpm_version(runtime, repo_type):
    """
    Retrieve the version number of the atomic-openshift RPM in the indicated
    repository. This is the version number that will be applied to new images
    created from this build.
    """
    runtime.initialize(clone_distgits=False)

    version = runtime.auto_version(repo_type)
    click.echo("version: {}".format(version))


if __name__ == '__main__':
    cli(obj={})
