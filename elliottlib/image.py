import os
import json
import bashlex
from dockerfile_parse import DockerfileParser
from metadata import Metadata
from model import Missing
from pushd import Dir

import assertion
import constants
import logutil
import exectools
import container
import logutil

logger = logutil.getLogger(__name__)


YUM_NON_FLAGS = [
    '-c', '--config',
    '--installroot',
    '--enableplugin',
    '--disableplugin',
    '--setopt',
    '-R', '--randomwait',
    '-d', '--debuglevel',
    '-e', '--errorlevel',
    '--rpmverbosity',
    '--enablerepo',
    '--disablerepo',
    '--repo', '--repoid',
    '-x', '--exclude', '--excludepkgs',
    '--disableexcludes', '--disableexcludepkgs',
    '--repofrompath',
    '--destdir', '--downloaddir',
    '--comment',
    '--advisory', '--advisories',
    '--bzs', '--cves', '--sec-severity',
    '--forearch'
]


class ImageMetadata(Metadata):

    def __init__(self, runtime, data_obj):
        super(ImageMetadata, self).__init__('image', runtime, data_obj)
        self.image_name = self.config.name
        self.image_name_short = self.image_name.split('/')[-1]

    @property
    def base_only(self):
        """
        Some images are marked base-only.  Return the flag from the config file
        if present.
        """
        return self.config.base_only

    def get_rpm_install_list(self, valid_pkg_list=None):
        """Parse dockerfile and find any RPMs that are being installed
        It will automatically do any bash variable replacement during this parse
        """
        if self._distgit_repo:
            # Already cloned, load from there
            with Dir(self._distgit_repo.distgit_dir):
                dfp = DockerfileParser('Dockerfile')

        else:
            # not yet cloned, just download it
            dfp = DockerfileParser()
            dfp.content = self.fetch_cgit_file("Dockerfile")

        def env_replace(envs, val):
            # find $VAR and ${VAR} style replacements
            for k, v in envs.iteritems():
                opts = ['${}'.format(k), '${{{}}}'.format(k)]
                for opt in opts:
                    if opt in val:
                        val = val.replace(opt, v)
            return val

        def is_assignment(line):
            # if this is an assignment node we need to add
            # to env dict for later replacement in commands
            try:
                parts = bashlex.parse(line)
            except:
                # bashlex does not get along well with some inline
                # conditionals and may emit ParsingError
                # if that's the case, it's not an assigment, so move along
                return None
            for ast in parts:
                if ast.kind != 'compound':  # ignore multi part commands
                    for part in ast.parts:
                        if part.kind == 'assignment':
                            return part.word.split('=')
            return None

        envs = dict(dfp.envs)
        run_lines = []
        for entry in json.loads(dfp.json):
            if isinstance(entry, dict) and 'RUN' in entry:
                line = entry['RUN']
                for line in line.split("&"):
                    line = line.strip()
                    if line:
                        line = env_replace(envs, line)
                        assign = is_assignment(line)
                        if assign:
                            envs[assign[0]] = assign[1]
                        run_lines.append(line)

        rpms = []
        for line in run_lines:
            split = list(bashlex.split(line))
            if 'yum' in split and 'install' in split:
                # remove as to not mess with checking below
                split.remove('yum')
                split.remove('install')

                i = 0
                rpm_start = 0
                while i < len(split):
                    sub = split[i]
                    if sub.startswith('-'):
                        if sub in YUM_NON_FLAGS:
                            i += 1
                            continue
                    else:
                        rpm_start = i
                        break  # found start of rpm names, exit
                    i += 1

                rpms.extend(split[rpm_start:])

        return [str(r) for r in rpms]  # strip unicode

    def get_latest_build_info(self):

        """
        Queries brew to determine the most recently built release of the component
        associated with this image. This method does not rely on the "release"
        label needing to be present in the Dockerfile.

        :return: A tuple: (component name, version, release); e.g. ("registry-console-docker", "v3.6.173.0.75", "1")
        """

        component_name = self.get_component_name()

        tag = "{}-candidate".format(self.branch())

        rc, stdout, stderr = exectools.cmd_gather(["brew", "latest-build", tag, component_name])

        assertion.success(rc, "Unable to search brew builds: %s" % stderr)

        latest = stdout.strip().splitlines()[-1].split(' ')[0]

        if not latest.startswith(component_name):
            # If no builds found, `brew latest-build` output will appear as:
            # Build                                     Tag                   Built by
            # ----------------------------------------  --------------------  ----------------
            raise IOError("No builds detected for %s using tag: %s" % (self.qualified_name, tag))

        # latest example: "registry-console-docker-v3.6.173.0.75-1""
        name, version, release = latest.rsplit("-", 2)  # [ "registry-console-docker", "v3.6.173.0.75", "1"]

        return name, version, release

    def pull_url(self):
        # Don't trust what is the Dockerfile for version & release. This field may not even be present.
        # Query brew to find the most recently built release for this component version.
        _, version, release = self.get_latest_build_info()
        return "{host}/{name}:{version}-{release}".format(
            host=constants.BREW_IMAGE_HOST, name=self.config.name, version=version, release=release)

    def get_default_push_tags(self, version, release):
        push_tags = [
            "%s-%s" % (version, release),  # e.g. "v3.7.0-0.114.0.0"
            "%s" % version,  # e.g. "v3.7.0"
        ]

        # it's possible but rare that an image will have an alternate
        # tags along with the regular ones
        # append those to the tag list.
        if self.config.push.additional_tags is not Missing:
            push_tags.extend(self.config.push.additional_tags)

        # In v3.7, we use the last .0 in the release as a bump field to differentiate
        # image refreshes. Strip this off since OCP will have no knowledge of it when reaching
        # out for its node image.
        if "." in release:
            # Strip off the last field; "0.114.0.0" -> "0.114.0"
            push_tags.append("%s-%s" % (version, release.rsplit(".", 1)[0]))

        # Push as v3.X; "v3.7.0" -> "v3.7"
        push_tags.append("%s" % (version.rsplit(".", 1)[0]))
        return push_tags

    def get_default_repos(self):
        """
        :return: Returns a list of ['ns/repo', 'ns/repo'] found in the image config yaml specified for default pushes.
        """
        # Repos default to just the name of the image (e.g. 'openshift3/node')
        default_repos = [self.config.name]

        # Unless overridden in the config.yml
        if self.config.push.repos is not Missing:
            default_repos = self.config.push.repos.primitive()

        return default_repos

    def get_default_push_names(self):
        """
        :return: Returns a list of push names that should be pushed to for registries defined in
        group.yml and for additional repos defined in image config yaml.
        (e.g. ['registry/ns/repo', 'registry/ns/repo', ...]).
        """

        # Will be built to include a list of 'registry/ns/repo'
        push_names = []

        default_repos = self.get_default_repos()  # Get a list of [ ns/repo, ns/repo, ...]

        default_registries = []
        if self.runtime.group_config.push.registries is not Missing:
            default_registries = self.runtime.group_config.push.registries.primitive()

        for registry in default_registries:
            registry = registry.rstrip("/")   # Remove any trailing slash to avoid mistaking it for a namespace
            for repo in default_repos:
                namespace, repo_name = repo.split('/')
                if '/' in registry:  # If registry overrides namespace
                    registry, namespace = registry.split('/')
                push_names.append('{}/{}/{}'.format(registry, namespace, repo_name))

        # image config can contain fully qualified image names to push to (registry/ns/repo)
        if self.config.push.also is not Missing:
            push_names.extend(self.config.push.also)

        return push_names

    def get_additional_push_names(self, additional_registries):
        """
        :return: Returns a list of push names based on a list of additional registries that
        need to be pushed to (e.g. ['registry/ns/repo', 'registry/ns/repo', ...]).
        """

        if not additional_registries:
            return []

        # Will be built to include a list of 'registry/ns/repo'
        push_names = []

        default_repos = self.get_default_repos()  # Get a list of [ ns/repo, ns/repo, ...]

        for registry in additional_registries:
            registry = registry.rstrip("/")   # Remove any trailing slash to avoid mistaking it for a namespace
            for repo in default_repos:
                namespace, repo_name = repo.split('/')
                if '/' in registry:  # If registry overrides namespace
                    registry, namespace = registry.split('/')
                push_names.append('{}/{}/{}'.format(registry, namespace, repo_name))

        return push_names


def create_image_verify_repo_file(runtime, repo_type='signed'):
    """Create a repo file to copy into a container. The repos that are
    added come from the selected group YAML config file.

    :param string repo_type: Currently one of 'signed' or
    'unsigned'. Determines which OSE repo will be installed. Reference
    the repos defined in the group config yaml file for other possible
    values

    :return string repo_file: The full path to the created repo file

    """
    # Use the running container ID to keep the repo files unique
    repo_file = os.path.join(runtime.working_dir, 'verify.repo')
    repos = {
        'rhel-server-rpms': runtime.repos['rhel-server-rpms'],
        'rhel-server-extras-rpms': runtime.repos['rhel-server-extras-rpms'],
        'rhel-server-rhscl-rpms': runtime.repos['rhel-server-rhscl-rpms'],
        'rhel-server-optional-rpms': runtime.repos['rhel-server-optional-rpms'],
        'rhel-fast-datapath-rpms': runtime.repos['rhel-fast-datapath-rpms'],
        'rhel-server-ose-rpms': runtime.repos['rhel-server-ose-rpms'],
    }

    with open(repo_file, 'w') as fp:
        for repo in repos.keys():
            fp.write(repos[repo].conf_section(repo_type, enabled=True))
    return repo_file


class Image(object):
    """This is an image. We're going to launch a container from it and
    verify the contents.
    """

    def __init__(self, runtime, pull_url, repo_file, enabled_checks, distgit=''):
        """
        :param Runtime runtime: Program runtime object

        :param string pull_url: The host/name:tag URL of the image to verify

        :param string repo_file: The full path to the repo file which
        is installed in the container later

        :param list enabled_checks: List of check names to run on the
        image. Each check is an Image() method.
        """
        self.runtime = runtime
        self.pull_url = pull_url
        self.enabled_checks = enabled_checks
        # registry.redhat.com:8888/openshift3/ose:v3.4.1.44.38-12 => ose:v3.4.1.44.38-12
        self.name_tag = pull_url.split('/')[-1]
        self.logger = logutil.EntityLoggingAdapter(logger=logger, extra={'entity': '{}'.format(self.name_tag)})
        self.distgit = distgit

        # I must apologize for this...... Trim the version. Remove any
        # possible leaving 'v' characters, split on hyphen to isolate
        # the image release (-NN), take first item
        self.image_version = self.name_tag.split(':')[-1].lstrip('v').split('-')[0]
        self.container = container.DockerContainer(pull_url)
        # Full and abbreviated container IDs once started
        self.cid = None
        self.failures = {}
        self.repo_file = repo_file
        self.status = 'passed'

    def verify_image(self):
        """Verify this container image by running the provided checks"""
        self.init_container()
        for check in self.enabled_checks:
            # Scan this Image object for a method matching the given
            # check name and then call the check.
            try:
                getattr(self, check)()
            except AttributeError:
                # We attempted to run a check which doesn't
                # exist. This should not be possible. Who updated the
                # @click.option's and didn't add the required check?
                self.logger.error("Attempted to run an unknown check: {bad_check} during image verification".format(bad_check=check))

        # All checks ran, shut it down, clean up after it, analyze results
        self.container.stop()
        self.container.rm()
        # Image().verify_image() => {
        #     'image': 'brewblablabla/openshift3/ose:v3.y.z-nnnnn',
        #     'status': 'failed', # or maybe 'passed'
        #     'distgit': 'ose', # or whatever the Dockerfile distgit
        #                       # source is. Empty string if ran
        #                       # from --images
        #     'failures': {
        #         'check_foo': {
        #             'description': 'words about a specific check',
        #             'items': ['a list of', 'items which failed', 'or the nature', 'of a general failure']
        #         }
        #     }
        # }
        return {'image': self.pull_url, 'failures': self.failures, 'status': self.status, 'distgit': self.distgit}

    def init_container(self):
        """Run basic initializion tasks"""
        self.container.start()
        self.cid = self.container.cid
        # Install that repo file
        self.container.copy_into(self.repo_file, '/etc/yum.repos.d/')

    def check_sigs(self):
        """Ensure installed packages are signed using a valid key"""
        self.logger.debug("[Verify: {name}] Grabbing package signature list".format(name=self.name_tag))
        # If anything is broke here it will be specific to the RPM database.
        rc, rpm_sigs, stderr = self.container.execute("rpm -qa --qf '%{name}-%{VERSION}-%{RELEASE} %{SIGPGP:pgpsig}\n'")
        res = {
            'description': 'Installed packages without valid signatures',
            'items': [],
        }

        if rc != 0:
            res['items'].append('Error querying the RPM database for package signatures')
            res['items'].append(str(rpm_sigs) + str(stderr))

        for line in rpm_sigs.split('\n'):
            l = line.strip()

            # Don't worry about it, these aren't always signed
            if l == 'gpg-pubkey' or l.startswith('gpg-pubkey-'):
                continue

            if l.endswith('(none)'):
                # These results are coming back with two leading
                # single-quotes and the trailing string ' (none)'.
                # Let's normalize that.
                clean_pkg_name = l[:-7]
                res['items'].append(clean_pkg_name)
                self.logger.info("[Verify: {name}] Unsigned package: {pkg}".format(pkg=clean_pkg_name, name=self.name_tag))

        if len(res['items']) > 0:
            self.status = 'failed'
            self.failures['check_sigs'] = res

    def check_versions(self):
        """Ensure the correct package versions are installed for this image"""
        res = {
            'description': 'Installed package target version validation',
            'items': [],
        }
        self.logger.info("[Verify: {name}] Checking atomic openshift version".format(name=self.name_tag))
        # rc check not required as atomic-openshift may not always be
        # installed (rc=1 for non-installed packages)
        _, ver, _ = self.container.execute('rpm -q --qf %{VERSION} atomic-openshift')
        ver = ver.rstrip()

        if not ver.endswith('not installed'):
            if ver != self.image_version:
                res['items'].append("Installed AOS version: '{ver}' does not expected version '{expected}'".format(ver=ver, expected=self.image_version))
                self.failures['check_versions'] = res
                self.status = 'failed'

    def check_orphans(self):
        res = {
            'description': 'Installed packages without valid source repositories',
            'items': [],
        }

        # It is not very useful to check the RC here. Orphans will
        # return rc=0, no orphans return the same rc=0.
        #
        # Any errors with the package-cleanup command will return
        # non-0. We identify bad repo configs (rc=1) and we note them
        # in the results. A bad repo config counts as an error so it
        # is not overlooked.
        _, orphaned_packages, _ = self.container.execute('package-cleanup --orphans')

        for line in orphaned_packages.split('\n'):
            l = line.strip()
            # Line with space separated words, empty length strip()d
            # line, or a line with just a help article in it
            if l.endswith('HTTP Error 404 - Not Found'):
                res['items'].append("Could not check orphan package status due to invalid repository configuration")
                res['items'].append(l)
            elif ' ' in l or '' == l or 'https://access.redhat.com' in l:
                # This line is an informational sentence or a blank
                # line, not a package name. Skip it.
                continue
            else:
                res['items'].append(l)
                self.logger.info("[Verify: {name}] Orphaned Package: {pkg}".format(name=self.name_tag, pkg=l))

        if len(res['items']) > 0:
            self.status = 'failed'
            self.failures['check_orphans'] = res
