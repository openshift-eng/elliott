import hashlib
import json
import os
import shutil
import time
import traceback
import errno
from multiprocessing import Lock
from yaml import safe_dump
import logging

from dockerfile_parse import DockerfileParser

import assertion
import constants
import exectools
from pushd import Dir
from brew import watch_task
from model import Model, Missing

OIT_COMMENT_PREFIX = '#oit##'

COMPOSE = """
# This file is managed by the OpenShift Image Tool: https://github.com/openshift/enterprise-images,
# by the OpenShift Continuous Delivery team (#aos-cd-team on IRC).
# Any manual changes will be overwritten by OIT on the next build.
#
# See https://mojo.redhat.com/docs/DOC-1159997 for more information on
# maintaining this file and the format and examples

---
"""


def recursive_overwrite(src, dest, ignore=set(), logger=None):
    """
    Use rsync to copy one file tree to a new location
    """
    exclude = ''
    for i in ignore:
        exclude += ' --exclude="{}" '.format(i)
    cmd = 'rsync -av {} {}/ {}/'.format(exclude, src, dest)
    exectools.cmd_assert(cmd.split(' '), logger=logger)


def pull_image(url, logger=None):
    logger = logger or logging.getLogger()
    logger.info("Pulling image: %s" % url)

    def wait(_):
        logger.info("Error pulling image %s -- retrying in 60 seconds" % url)
        time.sleep(60)

    exectools.retry(
        3, wait_f=wait,
        task_f=lambda: exectools.cmd_log(["docker", "pull", url], logger) == 0)


class DistGitRepo(object):
    def __init__(self, metadata, autoclone=True):
        self.metadata = metadata
        self.config = metadata.config
        self.runtime = metadata.runtime
        self.name = self.metadata.name
        self.distgit_dir = None
        self.build_status = False
        self.push_status = False

        self.branch = self.runtime.branch

        # Allow the config yaml to override branch
        # This is primarily useful for a sync only group.
        if self.config.distgit.branch is not Missing:
            self.branch = self.config.distgit.branch

        self.logger = metadata.runtime.logger.getChild(
            "[{}/{}]".format(
                self.metadata.namespace,
                self.metadata.distgit_key))

        # Initialize our distgit directory, if necessary
        if autoclone:
            self.clone(self.runtime.distgits_dir, self.branch)

    def clone(self, distgits_root_dir, distgit_branch):
        with Dir(distgits_root_dir):

            namespace_dir = os.path.join(distgits_root_dir, self.metadata.namespace)

            # It is possible we have metadata for the same distgit twice in a group.
            # There are valid scenarios (when they represent different branches) and
            # scenarios where this is a user error. In either case, make sure we
            # don't conflict by stomping on the same git directory.
            self.distgit_dir = os.path.join(namespace_dir, self.metadata.distgit_key)

            if os.path.isdir(self.distgit_dir):
                self.logger.info("Distgit directory already exists; skipping clone: %s" % self.distgit_dir)
            else:

                # Make a directory for the distgit namespace if it does not already exist
                try:
                    os.mkdir(namespace_dir)
                except OSError as e:
                    if e.errno != errno.EEXIST:
                        raise

                cmd_list = ["rhpkg"]

                if self.runtime.user is not None:
                    cmd_list.append("--user=%s" % self.runtime.user)

                cmd_list.extend(["clone", self.metadata.qualified_name, self.distgit_dir])

                self.logger.info("Cloning distgit repository [branch:%s] into: %s" % (distgit_branch, self.distgit_dir))

                # Clone the distgit repository. Occasional flakes in clone, so use retry.
                exectools.cmd_assert(cmd_list, retries=3, logger=self.runtime.logger)

            with Dir(self.distgit_dir):

                rc, out, err = exectools.cmd_gather(["git", "rev-parse", "--abbrev-ref", "HEAD"], self.runtime.logger)
                out = out.strip()

                # Only switch if we are not already in the branch. This allows us to work in
                # working directories with uncommited changes.
                if out != distgit_branch:
                    # Switch to the target branch
                    exectools.cmd_assert(["rhpkg", "switch-branch", distgit_branch], logger=self.runtime.logger)

            self._read_master_data()

    def merge_branch(self, target, allow_overwrite=False):
        self.logger.info('Switching to branch: {}'.format(target))
        exectools.cmd_assert(["rhpkg", "switch-branch", target], logger=self.runtime.logger)
        if not allow_overwrite:
            if os.path.isfile('Dockerfile') or os.path.isdir('.oit'):
                raise IOError('Unable to continue merge. Dockerfile found in target branch. Use --allow-overwrite to force.')
        self.logger.info('Merging source branch history over current branch')
        msg = 'Merge branch {} into {}'.format(self.branch, target)
        exectools.cmd_assert(['git', 'merge', '--allow-unrelated-histories', '-m', msg, self.branch], logger=self.runtime.logger)

    def source_path(self):
        """
        :return: Returns the directory containing the source which should be used to populate distgit.
        """
        alias = self.config.content.source.alias

        if alias is Missing:
            raise IOError("Can't find any source alias in config: %s" % self.metadata.config_filename)

        try:
            source_root = self.runtime.resolve_source(alias)
        except IOError as err:
            raise IOError("could not find alias {} for package {}".
                          format(alias, self.name))
        sub_path = self.config.content.source.path

        path = source_root
        if sub_path is not Missing:
            path = os.path.join(source_root, sub_path)

        assertion.isdir(path, "Unable to find path for source [%s] for config: %s" % (path, self.metadata.config_filename))
        return path

    def commit(self, commit_message, log_diff=False):
        with Dir(self.distgit_dir):
            self.logger.info("Adding commit to local repo: {}".format(commit_message))
            if log_diff:
                rc, out, err = exectools.cmd_gather(["git", "diff", "Dockerfile"], self.runtime.logger)
                assertion.success(rc, 'Failed fetching distgit diff')
                self.runtime.add_distgits_diff(self.metadata.name, out)
            exectools.cmd_assert(["git", "add", "-A", "."], logger=self.runtime.logger)
            exectools.cmd_assert(["git", "commit", "--allow-empty", "-m", commit_message], logger=self.runtime.logger)
            rc, sha, err = exectools.cmd_gather(["git", "rev-parse", "HEAD"], self.runtime.logger)
            assertion.success(rc, "Failure fetching commit SHA for {}".format(self.distgit_dir))
        return sha.strip()

    def tag(self, version, release):
        if version is None:
            return

        tag = '{}'.format(version)

        if release is not None:
            tag = '{}-{}'.format(tag, release)

        with Dir(self.distgit_dir):
            self.logger.info("Adding tag to local repo: {}".format(tag))
            exectools.cmd_gather(["git", "tag", "-f", tag, "-m", tag], self.runtime.logger)


class ImageDistGitRepo(DistGitRepo):
    def __init__(self, metadata):
        super(ImageDistGitRepo, self).__init__(metadata)
        self.build_lock = Lock()
        self.build_lock.acquire()

    def _generate_compose_conf(self):
        """
        Generates a compose conf file in container.yml
        """
        self.runtime.logger.debug("Generating compose file for Dockerfile {}".format(self.metadata.name))

        if self.config.compose is not Missing:
            # generate yaml data with header
            compose_yml_str = safe_dump(self.config.compose.primitive(), default_flow_style=False)
            compose_yml = COMPOSE + compose_yml_str
            with open('containers.yml', 'w') as rc:
                rc.write(compose_yml)

    def _generate_repo_conf(self):
        """
        Generates a repo file in .oit/repo.conf
        """

        dfp = DockerfileParser(path="Dockerfile")

        self.runtime.logger.debug("Generating repo file for Dockerfile {}".format(self.metadata.name))

        df_repos = []
        for entry in json.loads(dfp.json):
            if isinstance(entry, dict) and 'RUN' in entry:
                run_line = entry['RUN']

                # "cmd1 --o=x && cmd2 --o=y"  ->  [ "cmd1 --o=x ", "cmd2 --o=y" ]
                invokes = run_line.replace('&', ';').replace('|', ';').split(";")

                for invoke_line in invokes:
                    parsed_invoke = invoke_line.split("--")  # e.g. ["cmd1", "o=x"]

                    if len(parsed_invoke) < 2:
                        # This is too short for a yum repo management command
                        continue

                    cmd = parsed_invoke.pop(0).strip()

                    if not cmd.startswith("yum"):  # allow yum and yum-config-manager
                        # No repo action here either
                        continue

                    for comp in parsed_invoke:  # For the remaining elements; e.g. [ "o=x "]
                        # turn arguments like "o=x" or "o x" into a consistent list ["o", "x"]
                        kvs = comp.strip().replace('=', ' ').split()

                        if len(kvs) < 2:
                            # This can't be an enable, so skip it
                            continue

                        arg = kvs.pop(0).strip()

                        if arg != "enable" and arg != "enablerepo" and arg != "disable" and arg != "disablerepo":
                            continue

                        if cmd == 'yum-config-manager':
                            # Must be a loop because:  yum-config-manager --enable repo1 repo2 repo3
                            for repo_name in kvs:
                                df_repos.append(repo_name)
                        else:
                            # No loop because yum --enablerepo allows only one
                            df_repos.append(kvs[0])

        # Make our metadata directory if it does not exist
        if not os.path.isdir(".oit"):
            os.mkdir(".oit")

        repos = self.runtime.repos
        enabled_repos = self.config.get('enabled_repos', [])
        for t in repos.repotypes:
            with open('.oit/{}.repo'.format(t), 'w') as rc:
                content = repos.repo_file(t, enabled_repos=enabled_repos, empty_repos=df_repos)
                rc.write(content)

        with open('content_sets.yml', 'w') as rc:
            rc.write(repos.content_sets(enabled_repos=enabled_repos))

    def _read_master_data(self):
        with Dir(self.distgit_dir):
            self.org_image_name = None
            self.org_version = None
            self.org_release = None
            # Read in information about the image we are about to build
            dockerfile = os.path.join(Dir.getcwd(), 'Dockerfile')
            if os.path.isfile(dockerfile):
                dfp = DockerfileParser(path=dockerfile)
                self.org_image_name = dfp.labels.get("name")
                self.org_version = dfp.labels.get("version")
                self.org_release = dfp.labels.get("release")  # occasionally no release given

    def push_image(self, tag_list, push_to_defaults, additional_registries=[], version_release_tuple=None,
                   push_late=False, dry_run=False):

        """
        Pushes the most recent image built for this distgit repo. This is
        accomplished by looking at the 'version' field in the Dockerfile or
        the version_release_tuple argument and querying
        brew for the most recent images built for that version.
        :param tag_list: The list of tags to apply to the image (overrides default tagging pattern).
        :param push_to_defaults: Boolean indicating whether group/image yaml defined registries should be pushed to.
        :param additional_registries: A list of non-default registries (optional namespace included) to push the image to.
        :param version_release_tuple: Specify a version/release to pull as the source (if None, the latest build will be pulled).
        :param push_late: Whether late pushes should be included.
        :param dry_run: Will only print the docker operations that would have taken place.
        """

        # Late pushes allow certain images to be the last of a group to be
        # pushed to mirrors. CI/CD systems may initiate operations based on the
        # update a given image and all other images need to be in place
        # when that special image is updated. The special images are there
        # pushed "late"
        # Actions that need to push all images need to push all images
        # need to make two passes/invocations of this method: one
        # with push_late=False and one with push_late=True.

        is_late_push = False
        if self.config.push.late is not Missing:
            is_late_push = self.config.push.late

        if push_late != is_late_push:
            return

        push_names = []

        if push_to_defaults:
            push_names.extend(self.metadata.get_default_push_names())

        push_names.extend(self.metadata.get_additional_push_names(additional_registries))

        # Nothing to push to? We are done.
        if not push_names:
            return

        with Dir(self.distgit_dir):

            if version_release_tuple:
                version = version_release_tuple[0]
                release = version_release_tuple[1]
            else:

                # History
                # We used to rely on the "release" label being set in the Dockerfile, but this is problematic for several reasons.
                # (1) If 'release' is not set, OSBS will determine one automatically that does not conflict
                #       with a pre-existing image build. This is extremely helpful since we don't have to
                #       worry about bumping the release during refresh images. This means we generally DON'T
                #       want the release label in the file and can't, therefore, rely on it being there.
                # (2) People have logged into distgit before in order to bump the release field. This happening
                #       at the wrong time breaks the build.

                # If the version & release information was not specified,
                # try to detect latest build from brew.
                # Read in version information from the Distgit dockerfile
                _, version, release = self.metadata.get_latest_build_info()

            try:
                record = {
                    "distgit_key": self.metadata.distgit_key,
                    "distgit": '{}/{}'.format(self.metadata.namespace, self.metadata.name),
                    "image": self.config.name,
                    "version": version,
                    "release": release,
                    "message": "Unknown failure",
                    "status": -1,
                    # Status defaults to failure until explicitly set by success. This handles raised exceptions.
                }

                # pull just the main image name first
                image_name_and_version = "%s:%s-%s" % (self.config.name, version, release)
                brew_image_url = "/".join((constants.BREW_IMAGE_HOST, image_name_and_version))
                pull_image(brew_image_url, self.runtime.logger)
                record['message'] = "Successfully pulled image"
                record['status'] = 0
            except Exception as err:
                record["message"] = "Exception occurred: %s" % str(err)
                self.logger.info("Error pulling %s: %s" % (self.metadata.name, err))
                raise
            finally:
                self.runtime.add_record('pull', **record)

            push_tags = list(tag_list)

            # If no tags were specified, build defaults
            if not push_tags:
                push_tags = self.metadata.get_default_push_tags(version, release)

            for image_name in push_names:
                try:

                    repo = image_name.split('/', 1)

                    action = "push"
                    record = {
                        "distgit_key": self.metadata.distgit_key,
                        "distgit": '{}/{}'.format(self.metadata.namespace, self.metadata.name),
                        "repo": repo,  # ns/repo
                        "name": image_name,  # full registry/ns/repo
                        "version": version,
                        "release": release,
                        "message": "Unknown failure",
                        "tags": ", ".join(push_tags),
                        "status": -1,
                        # Status defaults to failure until explicitly set by success. This handles raised exceptions.
                    }

                    for push_tag in push_tags:
                        push_url = '{}:{}'.format(image_name, push_tag)

                        if dry_run:
                            rc = 0
                            self.info('Would have tagged {} as {}'.format(brew_image_url, push_url))
                            self.info('Would have pushed {}'.format(push_url))
                        else:
                            rc, out, err = exectools.cmd_gather(["docker", "tag", brew_image_url, push_url], self.runtime.logger)

                            if rc != 0:
                                # Unable to tag the image
                                raise IOError("Error tagging image as: %s" % push_url)

                            for r in range(10):
                                self.logger.info("Pushing image to mirror [retry=%d]: %s" % (r, push_url))
                                rc, out, err = exectools.cmd_gather(["docker", "push", push_url], self.runtime.logger)
                                if rc == 0:
                                    break
                                self.logger.info("Error pushing image -- retrying in 60 seconds")
                                time.sleep(60)

                        if rc != 0:
                            # Unable to push to registry
                            raise IOError("Error pushing image: %s" % push_url)

                    record["message"] = "Successfully pushed all tags"
                    record["status"] = 0

                except Exception as err:
                    record["message"] = "Exception occurred: %s" % str(err)
                    self.logger.info("Error pushing %s: %s" % (self.metadata.name, err))
                    raise

                finally:
                    self.runtime.add_record(action, **record)

    def wait_for_build(self, who_is_waiting):
        """
        Blocks the calling thread until this image has been built by oit or throws an exception if this
        image cannot be built.
        :param who_is_waiting: The caller's distgit_key (i.e. the waiting image).
        :return: Returns when the image has been built or throws an exception if the image could not be built.
        """
        self.info("Member waiting for me to build: %s" % who_is_waiting)
        # This lock is in an acquired state until this image definitively succeeds or fails.
        # It is then released. Child images waiting on this image should block here.
        with self.build_lock:
            if not self.build_status:
                raise IOError(
                    "Error building image: %s (%s was waiting)" % (self.metadata.qualified_name, who_is_waiting))
            else:
                self.logger.info("Member successfully waited for me to build: %s" % who_is_waiting)

    def build_container(
            self, repo_type, repo, push_to_defaults, additional_registries, terminate_event,
            scratch=False, retries=3):
        """
        This method is designed to be thread-safe. Multiple builds should take place in brew
        at the same time. After a build, images are pushed serially to all mirrors.
        DONT try to change cwd during this time, all threads active will change cwd
        :param repo_type: Repo type to choose from group.yml
        :param repo: A list/tuple of custom repo URLs to include for build
        :param push_to_defaults: If default registries should be pushed to.
        :param additional_registries: A list of non-default registries resultant builds should be pushed to.
        :param terminate_event: Allows the main thread to interrupt the build.
        :param scratch: Whether this is a scratch build. UNTESTED.
        :param retries: Number of times the build should be retried.
        :return: True if the build was successful
        """
        if self.org_image_name is None or self.org_version is None:
            if not os.path.isfile(os.path.join(self.distgit_dir, 'Dockerfile')):
                self.logger.info('No Dockerfile found in {}'.format(self.distgit_dir))
            else:
                self.logger.info('Unknown error loading Dockerfile information')
            return False

        action = "build"
        release = self.org_release if self.org_release is not None else '?'
        record = {
            "dir": self.distgit_dir,
            "dockerfile": "%s/Dockerfile" % self.distgit_dir,
            "distgit": self.metadata.name,
            "image": self.org_image_name,
            "version": self.org_version,
            "release": release,
            "message": "Unknown failure",
            "task_id": "n/a",
            "task_url": "n/a",
            "status": -1,
            "push_status": -1,
            # Status defaults to failure until explicitly set by success. This handles raised exceptions.
        }

        target_tag = "-".join((self.org_version, release))
        target_image = ":".join((self.org_image_name, target_tag))

        try:
            if not scratch and self.org_release is not None \
                    and self.metadata.tag_exists(target_tag):
                self.logger.info("Image already built for: {}".format(target_image))
            else:
                # If this image is FROM another group member, we need to wait on that group member
                # Use .get('from',None) since from is a reserved word.
                image_from = Model(self.config.get('from', None))
                if image_from.member is not Missing:
                    parent_name = image_from.member
                    parent_img = self.runtime.resolve_image(parent_name, False)
                    if parent_img is None:
                        self.logger.info("Skipping parent image build since it is not included: %s" % parent_name)
                    else:
                        parent_dgr = parent_img.distgit_repo()
                        parent_dgr.wait_for_build(self.metadata.qualified_name)
                        if terminate_event.is_set():
                            raise KeyboardInterrupt()

                # Allow an image to wait on an arbitrary image in the group. This is presently
                # just a workaround for: https://projects.engineering.redhat.com/browse/OSBS-5592
                if self.config.wait_for is not Missing:
                    wait_on_key = self.config.wait_for
                    wait_img = self.runtime.resolve_image(wait_on_key, False)
                    if wait_img is None:
                        self.info("Skipping wait_for image build since it is not included: %s" % wait_on_key)
                    else:
                        wait_dgr = wait_img.distgit_repo()
                        wait_dgr.wait_for_build(self.metadata.qualified_name)
                        if terminate_event.is_set():
                            raise KeyboardInterrupt()

                def wait(n):
                    self.logger.info("Async error in image build thread [attempt #{}]".format(n + 1))
                    # Brew does not handle an immediate retry correctly, wait
                    # before trying another build, terminating if interrupted.
                    if terminate_event.wait(timeout=5 * 60):
                        raise KeyboardInterrupt()

                exectools.retry(
                    n=3, wait_f=wait,
                    f=lambda: self._build_container(
                        target_image, repo_type, repo, terminate_event,
                        scratch, record))

            # Just in case someone else is building an image, go ahead and find what was just
            # built so that push_image will have a fixed point of reference and not detect any
            # subsequent builds.
            _, push_version, push_release = self.metadata.get_latest_build_info()
            record["message"] = "Success"
            record["status"] = 0
            self.build_status = True

        except (Exception, KeyboardInterrupt):
            tb = traceback.format_exc()
            record["message"] = "Exception occurred:\n{}".format(tb)
            self.logger.info("Exception occurred during build:\n{}".format(tb))
            # This is designed to fall through to finally. Since this method is designed to be
            # threaded, we should not throw an exception; instead return False.
        finally:
            # Regardless of success, allow other images depending on this one to progress or fail.
            self.build_lock.release()

        self.push_status = True  # if if never pushes, the status is True
        if not scratch and self.build_status and additional_registries:
            # If this is a scratch build, we aren't going to be pushing. We might be able to determine the
            # image name by parsing the build log, but not worth the effort until we need scratch builds.
            # The image name for a scratch build looks something like:
            # brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift3/ose-base:rhaos-3.7-rhel-7-docker-candidate-16066-20170829214444

            # To ensure we don't overwhelm the system building, pull & push synchronously
            with self.runtime.mutex:
                self.push_status = False
                try:
                    self.push_image([], push_to_defaults, additional_registries, version_release_tuple=(push_version, push_release))
                    self.push_status = True
                except Exception as push_e:
                    self.logger.info("Error during push after successful build: %s" % str(push_e))
                    self.push_status = False

        record['push_status'] = '0' if self.push_status else '-1'

        self.runtime.add_record(action, **record)
        return self.build_status and self.push_status

    def _build_container(
            self, target_image, repo_type, repo_list, terminate_event,
            scratch, record):
        """
        The part of `build_container` which actually starts the build,
        separated for clarity.
        """
        self.logger.info("Building image: %s" % target_image)
        cmd_list = ["rhpkg", "--path=%s" % self.distgit_dir]

        if self.runtime.user is not None:
            cmd_list.append("--user=%s" % self.runtime.user)

        cmd_list += (
            "container-build",
            "--nowait",
        )

        if repo_type:
            repo_list = list(repo_list)  # In case we get a tuple
            repo_list.append(self.metadata.cgit_url(".oit/" + repo_type + ".repo"))

        if repo_list:
            # rhpkg supports --repo-url [URL [URL ...]]
            cmd_list.append("--repo-url")
            cmd_list.extend(repo_list)

        if scratch:
            cmd_list.append("--scratch")

        # Run the build with --nowait so that we can immediately get information about the brew task
        rc, out, err = exectools.cmd_gather(cmd_list, self.runtime.logger)

        if rc != 0:
            # Probably no point in continuing.. can't contact brew?
            self.logger.info("Unable to create brew task: out={}  ; err={}".format(out, err))
            return False

        # Otherwise, we should have a brew task we can monitor listed in the stdout.
        out_lines = out.splitlines()

        # Look for a line like: "Created task: 13949050" . Extract the identifier.
        task_id = next((created_line.split(":")[1]).strip() for created_line in out_lines if
                       created_line.startswith("Created task:"))

        record["task_id"] = task_id

        # Look for a line like: "Task info: https://brewweb.engineering.redhat.com/brew/taskinfo?taskID=13948942"
        task_url = next((info_line.split(":", 1)[1]).strip() for info_line in out_lines if
                        info_line.startswith("Task info:"))

        self.logger.info("Build running: {}".format(task_url))

        record["task_url"] = task_url

        # Now that we have the basics about the task, wait for it to complete
        error = watch_task(self.logger.info, task_id, terminate_event)

        # Looking for something like the following to conclude the image has already been built:
        # BuildError: Build for openshift-enterprise-base-v3.7.0-0.117.0.0 already exists, id 588961
        if error is not None and "already exists" in error:
            self.logger.info("Image already built against this dist-git commit (or version-release tag): {}".format(target_image))
            error = None

        # Gather brew-logs
        logs_dir = "%s/%s" % (self.runtime.brew_logs_dir, self.metadata.name)
        logs_rc, _, logs_err = exectools.cmd_gather(["brew", "download-logs", "-d", logs_dir, task_id], self.runtime.logger)

        if logs_rc != 0:
            self.logger.info("Error downloading build logs from brew for task %s: %s" % (task_id, logs_err))

        if error is not None:
            # An error occurred. We don't have a viable build.
            self.logger.info("Error building image: {}, {}".format(task_url, error))
            return False

        self.logger.info("Successfully built image: {} ; {}".format(target_image, task_url))
        return True

    def push(self):
        with Dir(self.distgit_dir):
            self.logger.info("Pushing repository")
            exectools.cmd_assert(["rhpkg", "push"], retries=3, logger=self.runtime.logger)
            # rhpkg will create but not push tags :(
            # Not asserting this exec since this is non-fatal if the tag already exists
            exectools.cmd_gather(['git', 'push', '--tags'], self.runtime.logger)

    def update_dockerfile(self, version, release):
        ignore_missing_base = self.runtime.ignore_missing_base
        # A collection of comment lines that will be included in the generated Dockerfile. They
        # will be prefix by the OIT_COMMENT_PREFIX and followed by newlines in the Dockerfile.
        oit_comments = []

        if not self.runtime.no_oit_comment and not self.config.get('no_oit_comments', False):
            oit_comments.extend([
                "This file is managed by the OpenShift Image Tool: https://github.com/openshift/enterprise-images",
                "by the OpenShift Continuous Delivery team (#aos-cd-team on IRC).",
                "",
                "Any yum repos listed in this file will effectively be ignored during CD builds.",
                "Yum repos must be enabled in the oit configuration files.",
            ])

            if self.config.content.source is not Missing:
                oit_comments.extend(["The content of this file is managed from an external source.",
                                     "Changes made directly in distgit will be lost during the next",
                                     "reconciliation process.",
                                     ""])
            else:
                oit_comments.extend([
                    "Some aspects of this file may be managed programmatically. For example, the image name, labels (version,",
                    "release, and other), and the base FROM. Changes made directly in distgit may be lost during the next",
                    "reconciliation.",
                    ""])

        with Dir(self.distgit_dir):
            # Source or not, we should find a Dockerfile in the root at this point or something is wrong
            assertion.isfile("Dockerfile", "Unable to find Dockerfile in distgit root")

            self._generate_repo_conf()
            self._generate_compose_conf()

            dfp = DockerfileParser(path="Dockerfile")

            # If no version has been specified, we will leave the version in the Dockerfile. Extract it.
            if version is None:
                version = dfp.labels.get("version", dfp.labels.get("Version", None))
                if version is None:
                    raise IOError("No version found in Dockerfile for %s" % self.metadata.qualified_name)

            uuid_tag = "%s.%s" % (version, self.runtime.uuid)

            with open('additional-tags', 'w') as at:
                at.write("%s\n" % uuid_tag)  # The uuid which we ensure we get the right FROM tag
                at.write("%s\n" % version)
                vsplit = version.split(".")
                if len(vsplit) > 1:
                    at.write("%s.%s\n" % (vsplit[0], vsplit[1]))  # e.g. "v3.7.0" -> "v3.7"

            self.runtime.logger.debug("Dockerfile contains the following labels:")
            for k, v in dfp.labels.iteritems():
                self.runtime.logger.debug("  '%s'='%s'" % (k, v))

            # Set all labels in from config into the Dockerfile content
            if self.config.labels is not Missing:
                for k, v in self.config.labels.iteritems():
                    dfp.labels[k] = v

            # Set the image name
            dfp.labels["name"] = self.config.name

            # Set the distgit repo name
            dfp.labels["com.redhat.component"] = self.metadata.get_component_name()

            if 'from' in self.config:
                image_from = Model(self.config.get('from', None))
                # Does this image inherit from an image defined in a different distgit?
                if image_from.member is not Missing:
                    base = image_from.member
                    from_image_metadata = self.runtime.resolve_image(base, False)

                    if from_image_metadata is None:
                        if not ignore_missing_base:
                            raise IOError("Unable to find base image metadata [%s] in included images. Use --ignore-missing-base to ignore." % base)
                        elif self.runtime.latest_parent_version:
                            self.runtime.info('[{}] parent image {} not included. Looking up FROM tag.'.format(self.config.name, base))
                            base_meta = self.runtime.late_resolve_image(base)
                            _, v, r = base_meta.get_latest_build_info()
                            dfp.baseimage = "{}:{}-{}".format(base_meta.config.name, v, r)
                        # Otherwise, the user is not expecting the FROM field to be updated in this Dockerfile.
                    else:
                        # Everything in the group is going to be built with the uuid tag, so we must
                        # assume that it will exist for our parent.
                        dfp.baseimage = "%s:%s" % (from_image_metadata.config.name, uuid_tag)

                # Is this image FROM another literal image name:tag?
                if image_from.image is not Missing:
                    dfp.baseimage = image_from.image

                if image_from.stream is not Missing:
                    stream = self.runtime.resolve_stream(image_from.stream)
                    # TODO: implement expriring images?
                    dfp.baseimage = stream.image

            # Set image name in case it has changed
            dfp.labels["name"] = self.config.name

            # Set version if it has been specified.
            if version is not None:
                dfp.labels["version"] = version

            # If the release is specified as "+", this means the user wants to bump the release.
            if release == "+":

                # If release label is not present, default to 0, which will bump to 1
                release = dfp.labels.get("release", dfp.labels.get("Release", None))

                if release:
                    self.logger.info("Bumping release field in Dockerfile")

                    # If release has multiple fields (e.g. 0.173.0.0), increment final field
                    if "." in release:
                        components = release.rsplit(".", 1)  # ["0.173","0"]
                        bumped_field = int(components[1]) + 1
                        release = "%s.%d" % (components[0], bumped_field)
                    else:
                        # If release is specified and a single field, just increment it
                        release = "%d" % (int(release) + 1)
                else:
                    # When 'release' is not specified in the Dockerfile, OSBS will automatically
                    # find a valid value for each build. This means OSBS is effectively auto-bumping.
                    # This is better than us doing it, so let it.
                    self.logger.info("No release label found in Dockerfile; bumping unnecessary -- osbs will automatically select unique release value at build time")

            # If a release is specified, set it. If it is not specified, remove the field.
            # If osbs finds the field, unset, it will choose a value automatically. This is
            # generally ideal for refresh-images where the only goal is to not collide with
            # a pre-existing image version-release.
            if release is not None:
                dfp.labels["release"] = release
            else:
                if "release" in dfp.labels:
                    self.logger.info("Removing release field from Dockerfile")
                    del dfp.labels['release']

            # Delete differently cased labels that we override or use newer versions of
            for deprecated in ["Release", "Architecture", "BZComponent"]:
                if deprecated in dfp.labels:
                    del dfp.labels[deprecated]

            # Remove any programmatic oit comments from previous management
            df_lines = dfp.content.splitlines(False)
            df_lines = [line for line in df_lines if not line.strip().startswith(OIT_COMMENT_PREFIX)]

            df_content = "\n".join(df_lines)

            with open('Dockerfile', 'w') as df:
                for comment in oit_comments:
                    df.write("%s %s\n" % (OIT_COMMENT_PREFIX, comment))
                df.write(df_content)

            self._reflow_labels()

            return (version, release)

    def _reflow_labels(self, filename="Dockerfile"):
        """
        The Dockerfile parser we are presently using writes all labels on a single line
        and occasionally make multiple LABEL statements. Calling this method with a
        Dockerfile in the current working directory will rewrite the file with
        labels at the end in a single statement.
        """

        dfp = DockerfileParser(path=filename)
        labels = dict(dfp.labels)  # Make a copy of the labels we need to add back

        # Delete any labels from the modeled content
        for key in dfp.labels:
            del dfp.labels[key]

        # Capture content without labels
        df_content = dfp.content.strip()

        # Write the file back out and append the labels to the end
        with open(filename, 'w') as df:
            df.write("%s\n\n" % df_content)
            if labels:
                df.write("LABEL")
                for k, v in labels.iteritems():
                    df.write(" \\\n")  # All but the last line should have line extension backslash "\"
                    escaped_v = v.replace('"', '\\"')  # Escape any " with \"
                    df.write("        %s=\"%s\"" % (k, escaped_v))
                df.write("\n\n")

    def _merge_source(self):
        """
        Pulls source defined in content.source and overwrites most things in the distgit
        clone with content from that source.
        """

        # See if the config is telling us a file other than "Dockerfile" defines the
        # distgit image content.
        if self.config.content.source.dockerfile is not Missing:
            dockerfile_name = self.config.content.source.dockerfile
        else:
            dockerfile_name = "Dockerfile"

        # The path to the source Dockerfile we are reconciling against
        source_dockerfile_path = os.path.join(self.source_path(), dockerfile_name)

        # Clean up any files not special to the distgit repo
        for ent in os.listdir("."):

            # Do not delete anything that is hidden
            # protects .oit, .gitignore, others
            if ent.startswith("."):
                continue

            # Skip special files that aren't hidden
            if ent in ["additional-tags"]:
                continue

            # Otherwise, clean up the entry
            if os.path.isfile(ent):
                os.remove(ent)
            else:
                shutil.rmtree(ent)

        # Copy all files and overwrite where necessary
        recursive_overwrite(self.source_path(), self.distgit_dir, logger=self.runtime.logger)

        if dockerfile_name != "Dockerfile":
            # Does a non-distgit Dockerfile already exist from copying source; remove if so
            if os.path.isfile("Dockerfile"):
                os.remove("Dockerfile")

            # Rename our distgit source Dockerfile appropriately
            os.rename(dockerfile_name, "Dockerfile")

        # Clean up any extraneous Dockerfile.* that might be distractions (e.g. Dockerfile.centos)
        for ent in os.listdir("."):
            if ent.startswith("Dockerfile."):
                os.remove(ent)

        notify_owner = False

        # In a previous implementation, we tracked a single file in .oit/Dockerfile.source.last
        # which provided a reference for the last time a Dockerfile was reconciled. If
        # we reconciled a file that did not match the Dockerfile.source.last, we would send
        # an email the Dockerfile owner that a fundamentally new reconciliation had taken place.
        # There was a problem with this approach:
        # During a sprint, we might have multiple build streams running side-by-side.
        # e.g. builds from a master branch and builds from a stage branch. If the
        # Dockerfile in these two branches happened to differ, we would notify the
        # owner as we toggled back and forth between the two versions for the alternating
        # builds. Instead, we now keep around an history of all past reconciled files.

        source_dockerfile_hash = hashlib.sha256(open(source_dockerfile_path, 'rb').read()).hexdigest()

        if not os.path.isdir(".oit/reconciled"):
            os.mkdir(".oit/reconciled")

        dockerfile_already_reconciled_path = '.oit/reconciled/{}.Dockerfile'.format(source_dockerfile_hash)

        # If the file does not exist, the source file has not been reconciled before.
        if not os.path.isfile(dockerfile_already_reconciled_path):
            # Something has changed about the file in source control
            notify_owner = True
            # Record that we've reconciled against this source file so that we do not notify the owner again.
            shutil.copy(source_dockerfile_path, dockerfile_already_reconciled_path)

        # Leave a record for external processes that owners will need to notified.

        if notify_owner:
            with Dir(self.source_path()):
                author_email = None
                err = None
                rc, sha, err = exectools.cmd_gather('git log -n 1 --pretty=format:%H {}'.format(dockerfile_name), self.runtime.logger)
                if rc == 0:
                    rc, ae, err = exectools.cmd_gather('git show -s --pretty=format:%ae {}'.format(sha), self.runtime.logger)
                    if rc == 0:
                        if ae.lower().endswith('@redhat.com'):
                            self.logger.info('Last Dockerfile commiter: {}'.format(ae))
                            author_email = ae
                        else:
                            err = 'Last commiter email found, but is not @redhat.com address: {}'.format(ae)
                if err:
                    self.logger.info('Unable to get author email for last {} commit: {}'.format(dockerfile_name, err))

            owners = []
            if self.config.owners is not Missing and isinstance(self.config.owners, list):
                owners = list(self.config.owners)
            if author_email:
                owners.append(author_email)
            sub_path = self.config.content.source.path
            if not sub_path:
                source_dockerfile_subpath = dockerfile_name
            else:
                source_dockerfile_subpath = "{}/{}".format(sub_path, dockerfile_name)
            self.runtime.add_record("dockerfile_notify", distgit=self.metadata.qualified_name, image=self.config.name,
                                    dockerfile=os.path.abspath("Dockerfile"), owners=','.join(owners),
                                    source_alias=self.config.content.source.get('alias', None),
                                    source_dockerfile_subpath=source_dockerfile_subpath)

    def _run_modifications(self):
        """
        Interprets and applies content.source.modify steps in the image metadata.
        """

        with open("Dockerfile", 'r') as df:
            dockerfile_data = df.read()

        self.runtime.logger.debug(
            "About to start modifying Dockerfile [%s]:\n%s\n" %
            (self.metadata.name, dockerfile_data))

        for modification in self.config.content.source.modifications:
            if modification.action == "replace":
                match = modification.match
                assert (match is not Missing)
                replacement = modification.replacement
                assert (replacement is not Missing)
                if replacement is None:  # Nothing follows colon in config yaml; user attempting to remove string
                    replacement = ""
                pre = dockerfile_data
                dockerfile_data = pre.replace(match, replacement)
                if dockerfile_data == pre:
                    raise IOError("Replace (%s->%s) modification did not make a change to the Dockerfile content" % (
                        match, replacement))
                self.runtime.logger.debug(
                    "Performed string replace '%s' -> '%s':\n%s\n" %
                    (match, replacement, dockerfile_data))
            else:
                raise IOError("Don't know how to perform modification action: %s" % modification.action)

        with open('Dockerfile', 'w') as df:
            df.write(dockerfile_data)

    def rebase_dir(self, version, release):

        with Dir(self.distgit_dir):

            if version is None:
                # Extract the current version in order to preserve it
                dfp = DockerfileParser("Dockerfile")
                version = dfp.labels["version"]

            # Make our metadata directory if it does not exist
            if not os.path.isdir(".oit"):
                os.mkdir(".oit")

            # If content.source is defined, pull in content from local source directory
            if self.config.content.source is not Missing:
                self._merge_source()

            # Source or not, we should find a Dockerfile in the root at this point or something is wrong
            assertion.isfile("Dockerfile", "Unable to find Dockerfile in distgit root")

            if self.config.content.source.modifications is not Missing:
                self._run_modifications()

        (real_version, real_release) = self.update_dockerfile(version, release)

        return (real_version, real_release)


class RPMDistGitRepo(DistGitRepo):
    def __init__(self, metadata):
        super(RPMDistGitRepo, self).__init__(metadata)
        self.source = self.config.content.source
        if self.source.specfile is Missing:
            raise ValueError('Must specify spec file name for RPMs.')

    def _read_master_data(self):
        with Dir(self.distgit_dir):
            # Read in information about the rpm we are about to build
            pass  # placeholder for now. nothing to read
