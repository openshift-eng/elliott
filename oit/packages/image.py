import yaml
import shutil
import os
import filecmp
import tempfile
import re
import time
import urllib
from multiprocessing import Lock
from dockerfile_parse import DockerfileParser
import json

from common import BREW_IMAGE_HOST, CGIT_URL, assert_rc0, assert_file, assert_exec, assert_dir, exec_cmd, gather_exec, retry, Dir, recursive_overwrite
from model import Model, Missing

OIT_COMMENT_PREFIX = '#oit##'
EMPTY_REPO = 'http://download.lab.bos.redhat.com/rcm-guest/puddles/RHAOS/AtomicOpenShift_Empty/'


def cgit_url(name, filename, rev=None):
    ret = "{}/rpms/{}/plain/{}".format(CGIT_URL, name, filename)
    if rev is not None:
        ret = "{}?h={}".format(ret, rev)
    return ret


def pull_image(runtime, url):
    def wait():
        runtime.info("Error pulling image %s -- retrying in 60 seconds" % url)
        time.sleep(60)
    retry(
        n=3, wait_f=wait,
        f=lambda: exec_cmd(runtime, ["docker", "pull", url]) == 0)


class ImageMetadata(object):
    def __init__(self, runtime, dir, name):
        self.runtime = runtime
        self.dir = os.path.abspath(dir)
        self.config_path = os.path.join(self.dir, "config.yml")
        self.name = name

        runtime.log_verbose("Loading image metadata for %s from %s" % (name, self.config_path))

        assert_file(self.config_path, "Unable to find image configuration file")

        with open(self.config_path, "r") as f:
            config_yml_content = f.read()

        runtime.log_verbose(config_yml_content)
        self.config = Model(yaml.load(config_yml_content))

        # Basic config validation. All images currently required to have a name in the metadata.
        # This is required because from.member uses these data to populate FROM in images.
        # It would be possible to query this data from the distgit Dockerflie label, but
        # not implementing this until we actually need it.
        assert (self.config.name is not Missing)

        self.type = "rpms"  # default type is rpms
        if self.config.repo.type is not Missing:
            self.type = self.config.repo.type

        self.qualified_name = "%s/%s" % (self.type, name)

        self._distgit_repo = None

    def distgit_repo(self):
        if self._distgit_repo is None:
            self._distgit_repo = DistGitRepo(self)
        return self._distgit_repo

    def branch(self):
        if self.config.repo.branch is not Missing:
            return self.config.repo.branch
        return self.runtime.distgit_branch

    def cgit_url(self, filename):
        return cgit_url(self.name, filename, self.branch())

    def fetch_cgit_file(self, filename):
        url = self.cgit_url(filename)
        req = retry(
            3, lambda: urllib.urlopen(url),
            check_f=lambda req: req.code == 200)
        return req.read()

    def pull_url(self):
        p = DockerfileParser()
        p.content = self.fetch_cgit_file("Dockerfile")
        return "{host}/{l[name]}:{l[version]}-{l[release]}".format(
            host=BREW_IMAGE_HOST, l=p.labels)

    def pull_image(self):
        pull_image(self.runtime, self.pull_url())


class DistGitRepo(object):
    def __init__(self, metadata):
        self.metadata = metadata
        self.config = metadata.config
        self.runtime = metadata.runtime
        self.distgit_dir = None
        self.build_status = False
        self.build_lock = Lock()
        self.build_lock.acquire()

        self.branch = self.runtime.branch

        # Allow the config.yml to override branch
        # This is primarily useful for a sync only group.
        if self.config.repo.branch is not Missing:
            self.branch = self.config.repo.branch

        # Initialize our distgit directory, if necessary
        self.clone(self.runtime.distgits_dir, self.branch)

    def info(self, msg, debug=None):
        msg = "[%s] %s" % (self.metadata.qualified_name, msg)
        self.runtime.info(msg, debug)

    def clone(self, distgits_root_dir, distgit_branch):
        with Dir(distgits_root_dir):

            self.distgit_dir = os.path.abspath(os.path.join(os.getcwd(), self.metadata.name))
            if os.path.isdir(self.distgit_dir):
                self.info("Distgit directory already exists; skipping clone: %s" % self.distgit_dir)
            else:
                cmd_list = ["rhpkg"]

                if self.runtime.user is not None:
                    cmd_list.append("--user=%s" % self.runtime.user)

                cmd_list.extend(["clone", self.metadata.qualified_name])

                self.info("Cloning distgit repository [branch:%s] into: %s" % (distgit_branch, self.distgit_dir))

                # Clone the distgit repository
                assert_exec(self.runtime, cmd_list)

            with Dir(self.distgit_dir):

                out, err, rc = gather_exec(self.runtime, ["git", "rev-parse", "--abbrev-ref", "HEAD"])

                # Only switch if we are not already in the branch. This allows us to work in
                # working directories with uncommit changes.
                if out != distgit_branch:
                    # Switch to the target branch
                    assert_exec(self.runtime, ["rhpkg", "switch-branch", distgit_branch])

                # Read in information about the image we are about to build
                dfp = DockerfileParser(path="Dockerfile")
                self.org_image_name = dfp.labels["name"]
                self.org_version = dfp.labels["version"]
                self.org_release = dfp.labels.get("release", "0")  # occasionally no release given

    def copy_branch(self, to_branch):
        self.runtime.info('Copying {}: {} -> {}'.format(self.metadata.qualified_name, self.branch, to_branch))
        from_branch_copy = tempfile.mkdtemp(".tmp", "oit-copy-")
        self.runtime.info('Backing up to: {}'.format(from_branch_copy))
        recursive_overwrite(self.distgit_dir, from_branch_copy, ['.git'])
        self.runtime.info('Switching to branch: {}'.format(to_branch))
        assert_exec(self.runtime, ["rhpkg", "switch-branch", to_branch])
        self.runtime.info('Copying source branch contents over current branch')
        recursive_overwrite(from_branch_copy, self.distgit_dir, ['.git'])

        # os.removedirs(from_branch_copy)


    def source_path(self):
        """
        :return: Returns the directory containing the source which should be used to populate distgit.
        """
        alias = self.config.content.source.alias

        # TODO: enable source to be something other than an alias?
        #       A fixed git URL and branch for example?
        if alias is Missing:
            raise IOError("Can't find source alias in image config: %s" % self.metadata.dir)

        if alias not in self.runtime.source_alias:
            raise IOError(
                "Required source alias has not been registered [%s] for image config: %s" % (alias, self.metadata.dir))

        source_root = self.runtime.source_alias[alias]
        sub_path = self.config.content.source.path

        path = source_root
        if sub_path is not Missing:
            path = os.path.join(source_root, sub_path)

        assert_dir(path, "Unable to find path within source [%s] for config: %s" % (path, self.metadata.dir))
        return path

    def _merge_source(self):
        """
        Pulls source defined in content.source and overwrites most things in the distgit
        clone with content from that source.
        """

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
        recursive_overwrite(self.source_path(), self.distgit_dir)

        # See if the config is telling us a file other than "Dockerfile" defines the
        # distgit image content.
        dockerfile_name = self.config.content.source.dockerfile
        if dockerfile_name is not Missing and dockerfile_name != "Dockerfile":

            # Does a non-distgit Dockerfile already exists from copying source; remove if so
            if os.path.isfile("Dockerfile"):
                os.remove("Dockerfile")

            # Rename our distgit source Dockerfile appropriately
            os.rename(dockerfile_name, "Dockerfile")

        # Clean up any extraneous Dockerfile.* that might be distractions (e.g. Dockerfile.centos)
        for ent in os.listdir("."):
            if ent.startswith("Dockerfile."):
                os.remove(ent)

        dockerfile_git_last_path = ".oit/Dockerfile.git.last"

        notify_owner = False

        # Do we have a copy of the last time we reconciled?
        if os.path.isfile(dockerfile_git_last_path):
            # See if it equals the Dockerfile we just pulled from source control
            if not filecmp.cmp(dockerfile_git_last_path, "Dockerfile", False):
                # Something has changed about the file in source control
                notify_owner = True
                # Update our .oit copy so we can detect the next change of this reconciliation
                os.remove(dockerfile_git_last_path)
                shutil.copy("Dockerfile", dockerfile_git_last_path)
        else:
            # We've never reconciled, so let the owner know about the change
            notify_owner = True

        # Leave a record for external processes that owners will need to notified.
        if notify_owner and self.config.owners is not Missing:
            owners_list = ", ".join(self.config.owners)
            self.runtime.add_record("dockerfile_notify", distgit=self.metadata.qualified_name, image=self.config.name,
                                    dockerfile=os.path.abspath("Dockerfile"), owners=owners_list,
                                    source_alias=self.config.content.source.get('alias', None))

    def _run_modifications(self):
        """
        Interprets and applies content.source.modify steps in the image metadata.
        """

        with open("Dockerfile", 'r') as df:
            dockerfile_data = df.read()

        self.runtime.log_verbose("\nAbout to start modifying Dockerfile [%s]:\n%s\n" %
                                 (self.metadata.name, dockerfile_data))

        for modification in self.config.content.source.modifications:
            if modification.action == "replace":
                match = modification.match
                assert (match is not Missing)
                replacement = modification.replacement
                assert (replacement is not Missing)
                pre = dockerfile_data
                dockerfile_data = pre.replace(match, replacement)
                if dockerfile_data == pre:
                    raise IOError("Replace (%s->%s) modification did not make a change to the Dockerfile content" % (
                        match, replacement))
                self.runtime.log_verbose("\nPerformed string replace '%s' -> '%s':\n%s\n" %
                                         (match, replacement, dockerfile_data))
            else:
                raise IOError("Don't know how to perform modification action: %s" % modification.action)

        with open('Dockerfile', 'w') as df:
            df.write(dockerfile_data)

    def _generate_repo_conf(self):
        """
        Generates a repo file in .oit/repo.conf
        """

        dfp = DockerfileParser(path="Dockerfile")

        self.runtime.log_verbose("\nGenerating repo file for Dockerfile {}".format(self.metadata.name))

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

                        arg = kvs[0].strip()
                        val = kvs[1].strip()

                        if arg != "enable" and arg != "enablerepo":
                            continue

                        repo_name = val
                        df_repos.append(repo_name)

        gc_repos = self.runtime.group_config.repos
        if gc_repos is Missing:
            msg = 'group.yml must include a `repos` section to define RPM repos to load.'
            self.runtime.error(msg)
            raise ValueError(msg)

        def resolve_repo(name, cfg):
            cfg['name'] = cfg.get('name', name)
            cfg['enabled'] = cfg.get('enabled', 0)
            cfg['gpgcheck'] = cfg.get('gpgcheck', 0)
            return cfg

        repo_types = list(gc_repos.keys())
        repo_types.remove('common')

        # Make our metadata directory if it does not exist
        if not os.path.isdir(".oit"):
            os.mkdir(".oit")

        for t in repo_types:
            type_repos = {}
            for name, cfg in gc_repos[t].items():
                cfg = resolve_repo(name, cfg)
                type_repos[name] = cfg

            for name, cfg in gc_repos['common'].items():
                cfg = resolve_repo(name, cfg)
                type_repos[name] = cfg

            if self.config.enabled_repos is not Missing:
                for er in self.config.enabled_repos:
                    if er in type_repos:
                        type_repos[er]['enabled'] = 1
                    else:
                        raise ValueError('{} must be added to group.yml:repos'.format(er))

            for r in df_repos:
                if r not in type_repos:
                    type_repos[r] = resolve_repo(r, {'enabled': 1, 'baseurl': EMPTY_REPO})

            with open('.oit/{}.repo'.format(t), 'w') as rc:
                for name, cfg in type_repos.items():
                    rc.write('[{}]\n'.format(name))
                    for k, v in cfg.items():
                        rc.write('{} = {}\n'.format(k, v))
                    rc.write('\n')

    def push_image(self, push_to_list, push_late=False):

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

        with Dir(self.distgit_dir):

            # Read in information about the image we are about to build
            dfp = DockerfileParser(path="Dockerfile")
            image_name = dfp.labels["name"]
            version = dfp.labels["version"]
            release = dfp.labels["release"]

            push_tags = [
                "%s-%s" % (version, release),  # e.g. "v3.7.0-0.114.0.0"
                "%s" % version,  # e.g. "v3.7.0"
            ]

            # In v3.7, we use the last .0 in the release as a bump field to differentiate
            # image refreshes. Strip this off since OCP will have no knowledge of it when reaching
            # out for its node image.
            if "." in release:
                # Strip off the last field; "0.114.0.0" -> "0.114.0"
                push_tags.append("%s-%s" % (version, release.rsplit(".", 1)[0]))

            # Push as v3.X; "v3.7.0" -> "v3.7"
            push_tags.append("%s" % (version.rsplit(".", 1)[0]))

            action = "push"
            record = {
                "dir": self.distgit_dir,
                "dockerfile": "%s/Dockerfile" % self.distgit_dir,
                "image": image_name,
                "version": version,
                "release": release,
                "message": "Unknown failure",
                "tags": ",".join(push_tags),
                "registries": ",".join(push_to_list),
                "status": -1,
                # Status defaults to failure until explicitly set by succcess. This handles raised exceptions.
            }

            try:
                image_name_and_version = "%s:%s-%s" % (image_name, version, release)
                brew_image_url = "/".join((BREW_IMAGE_HOST, image_name_and_version))
                pull_image(self.runtime, brew_image_url)

                for push_to in push_to_list:
                    for push_tag in push_tags:

                        # If someone passed in a URL with a trailling slash, prevent it from triggering our
                        # namespace override logic.
                        push_to = push_to.rstrip("/")

                        if "/" not in push_to:
                            push_url = "%s/%s:%s" % (push_to, image_name, push_tag)
                        else:
                            # This is not typical at the moment, but we support it. If there is a slash in the push
                            # url, we override the namespace/project into which we push the image.
                            # For example, if the image is openshift3/node and the registry url is
                            # "registry.reg-aws.openshift.com:443/online", we would push to
                            # "registry.reg-aws.openshift.com:443/online/node".
                            push_url = "%s/%s:%s" % (push_to, image_name.split("/", 1)[1], push_tag)

                        rc, out, err = gather_exec(self.runtime, ["docker", "tag", brew_image_url, push_url])

                        if rc != 0:
                            # Unable to tag the image
                            raise IOError("Error tagging image as: %s" % push_url)

                        for retry in range(10):
                            self.info("Pushing image to mirror [retry=%d]: %s" % (retry, push_url))
                            rc, out, err = gather_exec(self.runtime, ["docker", "push", push_url])
                            if rc == 0:
                                break
                            self.info("Error pushing image -- retrying in 60 seconds")
                            time.sleep(60)

                        if rc != 0:
                            # Unable to push to registry
                            raise IOError("Error pushing image: %s" % push_url)

                record["message"] = "Successfully pushed all tags"
                record["status"] = 0

            except Exception as err:
                record["message"] = "Exception occurred: %s" % str(err)
                self.info("Error pushing %s: %s" % (self.metadata.name, err))
                raise err

            finally:
                self.runtime.add_record(action, **record)

    def wait_for_build(self, who_is_waiting):
        # This lock is in an acquired state until this image definitively succeeds or fails.
        # It is then released. Child images waiting on this image should block here.
        with self.build_lock:
            if not self.build_status:
                raise IOError(
                    "Error building image: %s (%s was waiting)" % (self.metadata.qualified_name, who_is_waiting))
            else:
                self.info("repo successfully waited for me to build: %s" % who_is_waiting)

    def build_container(self, repo_type, push_to_list, scratch=False):
        """
        This method is designed to be thread-safe. Multiple builds should take place in brew
        at the same time. After a build, images are pushed serially to all mirrors.
        DONT try to change cwd during this time, all threads active will change cwd
        :param repo: Repo type to choose from group.yml
        :param push_to_list: A list of registries resultant builds should be pushed to.
        :param scratch: Whether this is a scratch build. UNTESTED.
        :return: True if the build was successful
        """

        action = "build"
        record = {
            "dir": self.distgit_dir,
            "dockerfile": "%s/Dockerfile" % self.distgit_dir,
            "image": self.org_image_name,
            "version": self.org_version,
            "release": self.org_release,
            "message": "Unknown failure",
            "status": -1,
            # Status defaults to failure until explicitly set by succcess. This handles raised exceptions.
        }

        target_image = "%s:%s-%s" % (self.org_image_name, self.org_version, self.org_release)

        try:

            # If this image is FROM another group member, we need to wait on that group member
            if self.config["from"].member is not Missing:
                parent_name = self.config["from"].member
                parent_img = self.runtime.resolve_image(parent_name, False)
                if parent_img is None:
                    self.info("Skipping parent image build since it is not included: %s" % parent_name)
                else:
                    parent_dgr = parent_img.distgit_repo()
                    parent_dgr.wait_for_build(self.metadata.qualified_name)

            self.info("Building image: %s" % target_image)

            cmd_list = ["rhpkg", "--path=%s" % self.distgit_dir]

            if self.runtime.user is not None:
                cmd_list.append("--user=%s" % self.runtime.user)

            cmd_list.append("container-build")

            cmd_list.append("--nowait")

            if scratch:
                cmd_list.append("--scratch")

            repo_url_base = "http://pkgs.devel.redhat.com/cgit/{}/plain/.oit/{}.repo?h={}"

            cmd_list.append("--repo")
            cmd_list.append(repo_url_base.format(self.metadata.qualified_name, repo_type, self.branch))

            # Run the build with --nowait so that we can immdiately get information about the brew task
            rc, out, err = gather_exec(self.runtime, cmd_list)

            if rc != 0:
                # Probably no point in continuing.. can't contact brew?
                raise IOError("Unable to create brew task: out={}  ; err={}".format(out, err))

            # Otherwise, we should have a brew task we can monitor listed in the stdout.
            out_lines = out.splitlines()

            # Look for a line like: "Created task: 13949050" . Extract the identifier.
            task_id = next((created_line.split(":")[1]).strip() for created_line in out_lines if
                           created_line.startswith("Created task:"))

            record["task_id"] = task_id

            # Look for a line like: "Task info: https://brewweb.engineering.redhat.com/brew/taskinfo?taskID=13948942"
            task_url = next((info_line.split(":", 1)[1]).strip() for info_line in out_lines if
                            info_line.startswith("Task info:"))

            self.info("Build running: {}".format(task_url))

            record["task_url"] = task_url

            # Now that we have the basics about the task, wait for it to complete
            rc, out, err = gather_exec(self.runtime, ["brew", "watch-task", task_id])

            # Looking for somethine like the following to conclude the image has already been built:
            # "13949407 buildContainer (noarch): FAILED: BuildError: Build for openshift-enterprise-base-docker-v3.7.0-0.117.0.0 already exists, id 588961"
            if "already exists" in out:
                self.info("Image already built for: {}".format(target_image))
                rc = 0

            if rc != 0:
                # An error occurred during watch-task. We don't have a viable build.
                raise IOError("Error building image: {}\nout={}  ; err={}".format(task_url, out, err))

            self.info("Successfully built image: {} ; {}".format(target_image, task_url))
            record["message"] = "Success"
            record["status"] = 0
            self.build_status = True

            if scratch:
                # If this is a scratch build, we aren't going to be pushing. We might be able to determine the
                # image name by parsing the build log, but not worth the effort until we need scratch builds.
                # The image name for a scratch build looks something like:
                # brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888/openshift3/ose-base:rhaos-3.7-rhel-7-docker-candidate-16066-20170829214444
                return True

        except Exception as err:
            record["message"] = "Exception occurred: {}".format(err)
            self.info("Exception occurred during build: {}".format(err))
            # This is designed to fall through to finally. Since this method is designed to be
            # threaded, we should throw and exception; instead return False.
        finally:
            self.runtime.add_record(action, **record)
            # Regardless of success, allow other images depending on this one to progress or fail.
            self.build_lock.release()

        if self.build_status:
            if len(push_to_list) > 0:
                # To ensure we don't overwhelm the system building, pull & push synchronously
                with self.runtime.mutex:
                    try:
                        self.push_image(push_to_list)
                    except Exception as push_e:
                        self.info("Error during push after successful build: %s" % str(push_e))
                        return False

        return self.build_status

    def commit(self, commit_message, log_diff=False):
        with Dir(self.distgit_dir):
            self.info("Adding commit to local repo: %s" % commit_message)
            if log_diff:
                rc, out, err = gather_exec(self.runtime, ["git", "diff", "Dockerfile"])
                assert_rc0(rc, 'Failed fetching distgit diff')
                self.runtime.add_distgits_diff(self.metadata.name, out)
            assert_exec(self.runtime, ["git", "add", "-A", "."])
            assert_exec(self.runtime, ["git", "commit", "-m", commit_message])
            rc, sha, err = gather_exec(self.runtime, ["git", "rev-parse", "HEAD"])
            assert_rc0(rc, "Failure fetching commit SHA for {}".format(self.distgit_dir))
        return sha.strip()

    def push(self):
        with Dir(self.distgit_dir):
            self.info("Pushing repository")
            assert_exec(self.runtime, ["rhpkg", "push"])

    def bump_dockerfile(self):
        with Dir(self.distgit_dir):
            # Source or not, we should find a Dockerfile in the root at this point or something is wrong
            assert_file("Dockerfile", "Unable to find Dockerfile in distgit root")

            dfp = DockerfileParser(path="Dockerfile")
            version = dfp.labels["version"]
            release = dfp.labels["release"]

            # If release has multiple fields (e.g. 0.173.0), increment final field
            if "." in release:
                components = release.rsplit(".", 1)  # ["0.173","0"]
                bumped_field = int(components[1]) + 1
                new_release = "%s.%d" % (components[0], bumped_field)
            else:
                # Otherwise, release is a single field; just increment it
                new_release = "%d" % (int(release) + 1)

            dfp.labels["release"] = new_release

            # Found that content had to be created before opening Dockerfile for
            # writing. Otherwise dfp loses content.
            df_content = dfp.content

            with open('Dockerfile', 'w') as df:
                df.write(df_content)

            self.commit("Bumping version to %s-%s" % (version, new_release))

    def update_dockerfile(self, version, release, ignore_missing_base=False):

        # A collection of comment lines that will be included in the generated Dockerfile. They
        # will be prefix by the OIT_COMMENT_PREFIX and followed by newlines in the Dockerfile.
        oit_comments = []

        if not self.runtime.no_oit_comment and not self.config.get('no_oit_comment', False):
            oit_comments.extend([
                "This file is managed by the OpenShift Image Tool: github.com/openshift/enterprise-images",
                "by the OpenShift Continuous Delivery team (#aos-cd-team on IRC).",
                "",
                "Any yum repos listed in this file will effectively be ignored.",
                "Instead enabled repos are managed by the OpenShift Image Tool when the build",
                "details are passed to the image build system."
            ])

            if self.config.content.source is not Missing:
                oit_comments.extend(["The content of this file is managed from external source.",
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
            assert_file("Dockerfile", "Unable to find Dockerfile in distgit root")

            self._generate_repo_conf()

            dfp = DockerfileParser(path="Dockerfile")

            self.runtime.log_verbose("Dockerfile has parsed labels:")
            for k, v in dfp.labels.iteritems():
                self.runtime.log_verbose("  '%s'='%s'" % (k, v))

            # Set all labels in from config into the Dockerfile content
            if self.config.labels is not Missing:
                for k, v in self.config.labels.iteritems():
                    dfp.labels[k] = v

            # Set the image name
            dfp.labels["name"] = self.config.name

            # Set the distgit repo name
            dfp.labels["com.redhat.component"] = self.metadata.name

            # Does this image inherit from an image defined in a different distgit?
            if self.config["from"].member is not Missing:
                base = self.config["from"].member
                from_image_metadata = self.runtime.resolve_image(base, False)

                if from_image_metadata is None:
                    if not ignore_missing_base:
                        raise IOError("Unable to find base image metadata [%s] in included images. Use --ignore-missing-base to ignore." % base)
                    # Otherwise, the user is not expecting the FROM field to be updated in this Dockerfile.
                else:
                    # Everything in the group is going to be built with the same version and release,
                    # so just assume it will exist with the version-release we are using for this
                    # repo.
                    dfp.baseimage = "%s:%s-%s" % (from_image_metadata.config.name, version, release)

            # Is this image FROM another literal image name:tag?
            if self.config["from"].image is not Missing:
                dfp.baseimage = self.config["from"].image

            if self.config["from"].stream is not Missing:
                stream = self.runtime.resolve_stream(self.config["from"].stream)
                # TODO: implement expriring images?
                dfp.baseimage = stream.image

            # Set image name in case it has changed
            dfp.labels["name"] = self.config.name

            # Set version and release fields
            dfp.labels["version"] = version
            dfp.labels["release"] = release

            # Remove any programmatic oit comments from previous management
            df_lines = dfp.content.splitlines(False)
            df_lines = [line for line in df_lines if not line.strip().startswith(OIT_COMMENT_PREFIX)]

            df_content = "\n".join(df_lines)

            if len(oit_comments):
                with open('Dockerfile', 'w') as df:
                    for comment in oit_comments:
                        df.write("%s %s\n" % (OIT_COMMENT_PREFIX, comment))
                    df.write(df_content)

    def rebase_dir(self, version, release):

        with Dir(self.distgit_dir):

            # Make our metadata directory if it does not exist
            if not os.path.isdir(".oit"):
                os.mkdir(".oit")

            # If content.source is defined, pull in content from local source directory
            if self.config.content.source is not Missing:
                self._merge_source()

            # Source or not, we should find a Dockerfile in the root at this point or something is wrong
            assert_file("Dockerfile", "Unable to find Dockerfile in distgit root")

            if self.config.content.source.modifications is not Missing:
                self._run_modifications()

        self.update_dockerfile(version, release)
