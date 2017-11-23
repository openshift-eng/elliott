import yaml
import shutil
import os
import tempfile
import hashlib
import time
import urllib
from multiprocessing import Lock
from dockerfile_parse import DockerfileParser
import json

from common import BREW_IMAGE_HOST, CGIT_URL, RetryException, assert_rc0, assert_file, assert_exec, assert_dir, exec_cmd, gather_exec, retry, Dir, recursive_overwrite
from model import Model, Missing

OIT_COMMENT_PREFIX = '#oit##'
EMPTY_REPO = 'http://download.lab.bos.redhat.com/rcm-guest/puddles/RHAOS/AtomicOpenShift_Empty/'


def cgit_url(name, filename, rev=None):
    ret = "/".join((CGIT_URL, name, "plain", filename))
    if rev is not None:
        ret = "{}?h={}".format(ret, rev)
    return ret


def pull_image(runtime, url):
    runtime.info("Pulling image: %s" % url)

    def wait(_):
        runtime.info("Error pulling image %s -- retrying in 60 seconds" % url)
        time.sleep(60)
    retry(
        n=3, wait_f=wait,
        f=lambda: exec_cmd(runtime, ["docker", "pull", url]) == 0)


def tag_exists(registry, name, tag, fetch_f=None):
    if fetch_f is None:
        fetch_f = lambda url: urllib.urlopen(url).code == 200
    return fetch_f("/".join((registry, "v1/repositories", name, "tags", tag)))


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
        return self.runtime.branch

    def cgit_url(self, filename):
        return cgit_url(self.qualified_name, filename, self.branch())

    def fetch_cgit_file(self, filename):
        url = self.cgit_url(filename)
        req = retry(
            3, lambda: urllib.urlopen(url),
            check_f=lambda req: req.code == 200)
        return req.read()

    def tag_exists(self, tag):
        return tag_exists("http://" + BREW_IMAGE_HOST, self.config.name, tag)

    def get_component_name(self):
        # By default, the bugzilla compnent is the name of the distgit,
        # but this can be overridden in the config.yml.
        component_name = self.name

        # For apbs, component name seems to have -apb appended.
        # ex. http://dist-git.host.prod.eng.bos.redhat.com/cgit/apbs/openshift-enterprise-mediawiki/tree/Dockerfile?h=rhaos-3.7-rhel-7
        if self.type == "apbs":
            component_name = "%s-apb" % component_name

        if self.config.repo.component is not Missing:
            component_name = self.config.repo.component

        return component_name

    def get_latest_build_release(self, dfp):

        """
        Queries brew to determine the most recently built release of the component
        associated with this image. This method does not rely on the "release"
        label needing to be present in the Dockerfile.

        :param dfp: A populated DockerFileParser
        :return: The most recently built release field string (e.g. "2")
        """

        component_name = self.get_component_name()
        version = dfp.labels["version"]

        # Brew can return all builds executed for a distgit repo. Most recent is listed last.
        # e.g. brew search build registry-console-docker-v3.6.173.0.74-*
        #     -> registry-console-docker-v3.6.173.0.74-2
        #     -> registry-console-docker-v3.6.173.0.74-3
        pattern = '{}-{}-*'.format(component_name, version)

        rc, stdout, stderr = gather_exec(self.runtime,
                                         ["brew", "search", "build", pattern])

        assert_rc0(rc, "Unable to search brew builds: %s" % stderr)

        builds = stdout.strip().splitlines()
        if not builds:
            raise IOError("No builds detected for %s using pattern: %s" % (self.qualified_name, pattern))

        last_build_id = builds[-1]  # e.g. "registry-console-docker-v3.6.173.0.75-1"
        release = last_build_id.rsplit("-", 1)[1]  # [ "registry-console-docker-v3.6.173.0.75", "1"]

        return release

    def pull_url(self):
        dfp = DockerfileParser()
        dfp.content = self.fetch_cgit_file("Dockerfile")
        # Don't trust what is the Dockerfile for "release". This field may not even be present.
        # Query brew to find the most recently built release for this component version.
        dfp.labels["release"] = self.get_latest_build_release(dfp)
        return "{host}/{l[name]}:{l[version]}-{l[release]}".format(
            host=BREW_IMAGE_HOST, l=dfp.labels)

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

                rc, out, err = gather_exec(self.runtime, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
                out = out.strip()

                # Only switch if we are not already in the branch. This allows us to work in
                # working directories with uncommited changes.
                if out != distgit_branch:
                    # Switch to the target branch
                    assert_exec(self.runtime, ["rhpkg", "switch-branch", distgit_branch])

                # Read in information about the image we are about to build
                dfp = DockerfileParser(path="Dockerfile")
                self.org_image_name = dfp.labels["name"]
                self.org_version = dfp.labels["version"]
                self.org_release = dfp.labels.get("release")  # occasionally no release given

    def copy_branch(self, to_branch):
        self.runtime.info('Copying {}: {} -> {}'.format(self.metadata.qualified_name, self.branch, to_branch))
        from_branch_copy = tempfile.mkdtemp(".tmp", "oit-copy-")
        self.runtime.info('Backing up to: {}'.format(from_branch_copy))
        recursive_overwrite(self.runtime, self.distgit_dir, from_branch_copy, ['.git'])
        self.runtime.info('Switching to branch: {}'.format(to_branch))
        assert_exec(self.runtime, ["rhpkg", "switch-branch", to_branch])
        self.runtime.info('Copying source branch contents over current branch')
        recursive_overwrite(self.runtime, from_branch_copy, self.distgit_dir, ['.git'])

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

        source_root = self.runtime.resolve_source(alias)
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
        recursive_overwrite(self.runtime, self.source_path(), self.distgit_dir)

        if dockerfile_name != "Dockerfile":
            # Does a non-distgit Dockerfile already exists from copying source; remove if so
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
            if self.config.owners is not Missing:
                owners_list = ""
            else:
                owners_list = ", ".join(self.config.owners)
            sub_path = self.config.content.source.path
            if not sub_path:
                source_dockerfile_subpath = dockerfile_name
            else:
                source_dockerfile_subpath = "{}/{}".format(sub_path, dockerfile_name)
            self.runtime.add_record("dockerfile_notify", distgit=self.metadata.qualified_name, image=self.config.name,
                                    dockerfile=os.path.abspath("Dockerfile"), owners=owners_list,
                                    source_alias=self.config.content.source.get('alias', None),
                                    source_dockerfile_subpath=source_dockerfile_subpath)

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

                        arg = kvs.pop(0).strip()

                        if arg != "enable" and arg != "enablerepo" and arg != "disable" and arg != "disablerepo":
                            continue

                        # Must be a loop because:  yum-config-manager --enable repo1 repo2 repo3
                        for repo_name in kvs:
                            df_repos.append(repo_name)

        gc_repos = self.runtime.group_config.repos
        if gc_repos is Missing:
            msg = 'group.yml must include a `repos` section to define RPM repos to load.'
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

        """
        Pushes the most recent image built for this distgit repo. This is
        accomplished by looking the 'version' field in the Dockerfile and querying
        brew for the most recent images built for that version.
        :param push_to_list: A list of registries to push the image to
        :param push_late: Whether late pushes should be included
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

        with Dir(self.distgit_dir):
            names = [self.config.name]
            # it's possible but rare that an image will have an alternate_name
            # it must be pushed with that name as well
            if self.config.alt_name is not Missing:
                names.append(self.config.alt_name)

            for image_name in names:
                # Read in information about the image we are about to build
                dfp = DockerfileParser(path="Dockerfile")
                version = dfp.labels["version"]

                # We used to rely on the "release" label being set, but this is problematic for several reasons.
                # (1) If 'release' is not set, OSBS will determine one automatically that does not conflict
                #       with a pre-existing image build. This is extremely helpful since we don't have to
                #       worry about bumping the release during refresh images. This means we generally DON'T
                #       want the release label in the file and can't, therefore, rely on it being there.
                # (2) People have logged into distgit before in order to bump the release field. This happening
                #       at the wrong time breaks the build.

                release = self.metadata.get_latest_build_release(dfp)

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
                    # Status defaults to failure until explicitly set by success. This handles raised exceptions.
                }

                try:
                    image_name_and_version = "%s:%s-%s" % (image_name, version, release)
                    brew_image_url = "/".join((BREW_IMAGE_HOST, image_name_and_version))
                    pull_image(self.runtime, brew_image_url)

                    for push_to in push_to_list:
                        for push_tag in push_tags:

                            # If someone passed in a URL with a trailing slash, prevent it from triggering our
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

    def build_container(self, repo_type, push_to_list, scratch=False, retries=3):
        """
        This method is designed to be thread-safe. Multiple builds should take place in brew
        at the same time. After a build, images are pushed serially to all mirrors.
        DONT try to change cwd during this time, all threads active will change cwd
        :param repo: Repo type to choose from group.yml
        :param push_to_list: A list of registries resultant builds should be pushed to.
        :param scratch: Whether this is a scratch build. UNTESTED.
        :param retries: Number of times the build should be retried.
        :return: True if the build was successful
        """

        action = "build"
        release = self.org_release if self.org_release is not None else '?'
        record = {
            "dir": self.distgit_dir,
            "dockerfile": "%s/Dockerfile" % self.distgit_dir,
            "image": self.org_image_name,
            "version": self.org_version,
            "release": release,
            "message": "Unknown failure",
            "status": -1,
            # Status defaults to failure until explicitly set by succcess. This handles raised exceptions.
        }

        target_tag = "-".join((self.org_version, release))
        target_image = ":".join((self.org_image_name, target_tag))

        try:
            if not scratch and self.org_release is not None \
                    and self.metadata.tag_exists(target_tag):
                self.info("Image already built for: {}".format(target_image))
            else:
                # If this image is FROM another group member, we need to wait on that group member
                if self.config["from"].member is not Missing:
                    parent_name = self.config["from"].member
                    parent_img = self.runtime.resolve_image(parent_name, False)
                    if parent_img is None:
                        self.info("Skipping parent image build since it is not included: %s" % parent_name)
                    else:
                        parent_dgr = parent_img.distgit_repo()
                        parent_dgr.wait_for_build(self.metadata.qualified_name)
                def wait(n):
                    self.info("Async error in image build thread [attempt #{}]: {}".format(n + 1, self.metadata.qualified_name))
                    # Brew does not handle an immediate retry correctly.
                    time.sleep(5 * 60)
                try:
                    retry(
                        n=3, wait_f=wait,
                        f=lambda: self._build_container(target_image, repo_type, scratch, record))
                except RetryException as err:
                    self.info(str(err))
                    return False
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
            # threaded, we should not throw an exception; instead return False.
        finally:
            self.runtime.add_record(action, **record)
            # Regardless of success, allow other images depending on this one to progress or fail.
            self.build_lock.release()

        if self.build_status:
            if push_to_list:
                # To ensure we don't overwhelm the system building, pull & push synchronously
                with self.runtime.mutex:
                    try:
                        self.push_image(push_to_list)
                    except Exception as push_e:
                        self.info("Error during push after successful build: %s" % str(push_e))
                        return False

        return self.build_status

    def _build_container(self, target_image, repo_type, scratch, record):
        """
        The part of `build_container` which actually starts the build,
        separated for clarity.
        """
        self.info("Building image: %s" % target_image)

        cmd_list = ["rhpkg", "--path=%s" % self.distgit_dir]

        if self.runtime.user is not None:
            cmd_list.append("--user=%s" % self.runtime.user)

        cmd_list += (
            "container-build",
            "--nowait",
            "--repo",
            self.metadata.cgit_url(".oit/" + repo_type + ".repo"),
        )

        if scratch:
            cmd_list.append("--scratch")

        # Run the build with --nowait so that we can immediately get information about the brew task
        rc, out, err = gather_exec(self.runtime, cmd_list)

        if rc != 0:
            # Probably no point in continuing.. can't contact brew?
            self.info("Unable to create brew task: out={}  ; err={}".format(out, err))
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

        self.info("Build running: {}".format(task_url))

        record["task_url"] = task_url

        # Now that we have the basics about the task, wait for it to complete
        rc, out, err = gather_exec(self.runtime, ["timeout", "4h", "brew", "watch-task", task_id])

        # Looking for something like the following to conclude the image has already been built:
        # "13949407 buildContainer (noarch): FAILED: BuildError: Build for openshift-enterprise-base-docker-v3.7.0-0.117.0.0 already exists, id 588961"
        if "already exists" in out:
            self.info("Image already built for: {}".format(target_image))
            rc = 0

        # Gather brew-logs
        logs_dir = "%s/%s" % (self.runtime.brew_logs_dir, self.metadata.name)
        logs_rc, logs_out, logs_err = gather_exec(self.runtime, ["brew", "download-logs", "-d", logs_dir, task_id])

        if logs_rc != 0:
            self.info("Error downloading build logs from brew for task %s: %s" % (task_id, logs_err))

        if rc != 0:
            if rc == 124:
                self.info("Timeout building image: {}\nout={}  ; err={}".format(task_url, out, err))
            else:
                # An error occurred during watch-task. We don't have a viable build.
                self.info("Error building image: {}\nout={}  ; err={}".format(task_url, out, err))
            return False

        self.info("Successfully built image: {} ; {}".format(target_image, task_url))
        return True

    def commit(self, commit_message, log_diff=False):
        with Dir(self.distgit_dir):
            self.info("Adding commit to local repo: {}".format(commit_message))
            if log_diff:
                rc, out, err = gather_exec(self.runtime, ["git", "diff", "Dockerfile"])
                assert_rc0(rc, 'Failed fetching distgit diff')
                self.runtime.add_distgits_diff(self.metadata.name, out)
            assert_exec(self.runtime, ["git", "add", "-A", "."])
            assert_exec(self.runtime, ["git", "commit", "--allow-empty", "-m", commit_message])
            rc, sha, err = gather_exec(self.runtime, ["git", "rev-parse", "HEAD"])
            assert_rc0(rc, "Failure fetching commit SHA for {}".format(self.distgit_dir))
        return sha.strip()

    def tag(self, version, release):
        if version is None:
            return

        tag = '{}'.format(version)

        if release is not None:
            tag = '{}-{}'.format(tag, release)

        with Dir(self.distgit_dir):
            self.info("Adding tag to local repo: {}".format(tag))
            gather_exec(self.runtime, ["git", "tag", "-f", tag, "-m", tag])

    def push(self):
        with Dir(self.distgit_dir):
            self.info("Pushing repository")
            assert_exec(self.runtime, ["rhpkg", "push"])
            # rhpkg will create but not push tags :(
            # Not asserting this exec since this is non-fatal if the tag already exists
            gather_exec(self.runtime, ['git', 'push', '--tags'])

    def update_dockerfile(self, version, release, ignore_missing_base=False):

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
            assert_file("Dockerfile", "Unable to find Dockerfile in distgit root")

            self._generate_repo_conf()

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

            self.runtime.log_verbose("Dockerfile contains the following labels:")
            for k, v in dfp.labels.iteritems():
                self.runtime.log_verbose("  '%s'='%s'" % (k, v))

            # Set all labels in from config into the Dockerfile content
            if self.config.labels is not Missing:
                for k, v in self.config.labels.iteritems():
                    dfp.labels[k] = v

            # Set the image name
            dfp.labels["name"] = self.config.name

            # Set the distgit repo name
            dfp.labels["com.redhat.component"] = self.metadata.get_component_name()

            # Does this image inherit from an image defined in a different distgit?
            if self.config["from"].member is not Missing:
                base = self.config["from"].member
                from_image_metadata = self.runtime.resolve_image(base, False)

                if from_image_metadata is None:
                    if not ignore_missing_base:
                        raise IOError("Unable to find base image metadata [%s] in included images. Use --ignore-missing-base to ignore." % base)
                    # Otherwise, the user is not expecting the FROM field to be updated in this Dockerfile.
                else:
                    # Everything in the group is going to be built with the uuid tag, so we must
                    # assume that it will exist for our parent.
                    dfp.baseimage = "%s:%s" % (from_image_metadata.config.name, uuid_tag)

            # Is this image FROM another literal image name:tag?
            if self.config["from"].image is not Missing:
                dfp.baseimage = self.config["from"].image

            if self.config["from"].stream is not Missing:
                stream = self.runtime.resolve_stream(self.config["from"].stream)
                # TODO: implement expriring images?
                dfp.baseimage = stream.image

            # Set image name in case it has changed
            dfp.labels["name"] = self.config.name

            # Set version if it has been specified.
            if version is not None:
                dfp.labels["version"] = version

            # If the release is specified as "+", this means the user wants to bump the release.
            if release == "+":
                self.info("Bumping release field in Dockerfile")

                # If release label is not present, default to 0, which will bump to 1
                release = dfp.labels.get("release", dfp.labels.get("Release", "0"))

                # If release has multiple fields (e.g. 0.173.0.0), increment final field
                if "." in release:
                    components = release.rsplit(".", 1)  # ["0.173","0"]
                    bumped_field = int(components[1]) + 1
                    release = "%s.%d" % (components[0], bumped_field)
                else:
                    # Otherwise, release is a single field; just increment it
                    release = "%d" % (int(release) + 1)

            # If a release is specified, set it. If it is not specified, remove the field.
            # If osbs finds the field, unset, it will choose a value automatically. This is
            # generally ideal for refresh-images where the only goal is to not collide with
            # a pre-existing image version-release.
            if release is not None:
                dfp.labels["release"] = release
            else:
                if "release" in dfp.labels:
                    self.info("Removing release field from Dockerfile")
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

    def rebase_dir(self, version, release, ignore_missing_base=False):

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
            assert_file("Dockerfile", "Unable to find Dockerfile in distgit root")

            if self.config.content.source.modifications is not Missing:
                self._run_modifications()

        self.update_dockerfile(version, release, ignore_missing_base)
