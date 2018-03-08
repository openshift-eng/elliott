import os
from dockerfile_parse import DockerfileParser
from distgit import pull_image
from metadata import Metadata

from common import BREW_IMAGE_HOST, assert_rc0, gather_exec
import container


class ImageMetadata(Metadata):
    def __init__(self, runtime, dir, name):
        super(ImageMetadata, self).__init__('image', runtime, dir, name)

    def get_latest_build_info(self):

        """
        Queries brew to determine the most recently built release of the component
        associated with this image. This method does not rely on the "release"
        label needing to be present in the Dockerfile.

        :return: A tuple: (component name, version, release); e.g. ("registry-console-docker", "v3.6.173.0.75", "1")
        """

        component_name = self.get_component_name()

        tag = "{}-candidate".format(self.branch())

        rc, stdout, stderr = gather_exec(self.runtime,
                                         ["brew", "latest-build", tag, component_name])

        assert_rc0(rc, "Unable to search brew builds: %s" % stderr)

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
        dfp = DockerfileParser()
        dfp.content = self.fetch_cgit_file("Dockerfile")
        # Don't trust what is the Dockerfile for version & release. This field may not even be present.
        # Query brew to find the most recently built release for this component version.
        _, version, release = self.get_latest_build_info()
        return "{host}/{l[name]}:{version}-{release}".format(
            host=BREW_IMAGE_HOST, l=dfp.labels, version=version, release=release)

    def pull_image(self):
        pull_image(self.runtime, self.pull_url())


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
        'rhel-server-rpms': runtime.group_config.repos.common['rhel-server-rpms'],
        'rhel-server-extras-rpms': runtime.group_config.repos.common['rhel-server-extras-rpms'],
        'rhel-server-rhscl-rpms': runtime.group_config.repos.common['rhel-server-rhscl-rpms'],
        'rhel-server-optional-rpms': runtime.group_config.repos.common['rhel-server-optional-rpms'],
        'rhel-fast-datapath-rpms': runtime.group_config.repos.common['rhel-fast-datapath-rpms'],
        'rhel-server-ose-rpms': runtime.group_config.repos[repo_type]['rhel-server-ose-rpms'],
    }

    repo_string = """[{repo}]
name={repo}
baseurl={baseurl}
enabled=1
gpgcheck=0
"""

    with open(repo_file, 'w') as fp:
        for repo in repos.keys():
            fp.write(repo_string.format(
                repo=repo,
                baseurl=repos[repo]['baseurl']))

    return repo_file


class Image(object):
    """This is an image. We're going to launch a container from it and
verify the contents.
    """

    def __init__(self, runtime, pull_url, repo_file, enabled_checks):
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
        # I must apologize for this...... Trim the version. Remove any
        # possible leaving 'v' characters, split on hyphen to isolate
        # the image release (-NN), take first item
        self.image_version = self.name_tag.split(':')[-1].lstrip('v').split('-')[0]
        self.container = container.DockerContainer(pull_url, runtime)
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
                self.runtime.log_verbose("Attempted to run an unknown check: {bad_check} during image verification".format(bad_check=check))

        # All checks ran, shut it down, clean up after it, analyze results
        self.container.stop()
        self.container.rm()
        # Image().verify_image() => {
        #     'image': 'brewblablabla/openshift3/ose:v3.y.z-nnnnn',
        #     'status': 'failed', # or maybe 'passed'
        #     'failures': {
        #         'check_foo': {
        #             'description': 'words about a specific check',
        #             'items': ['a list of', 'items which failed', 'or the nature', 'of a general failure']
        #         }
        #     }
        # }
        return {'image': self.pull_url, 'failures': self.failures, 'status': self.status}

    def init_container(self):
        """Run basic initializion tasks"""
        self.container.start()
        self.cid = self.container.cid
        # Install that repo file
        self.container.copy_into(self.repo_file, '/etc/yum.repos.d/')

    def check_sigs(self):
        """Ensure installed packages are signed using a valid key"""
        self.runtime.log_verbose("[Verify: {name}] Grabbing package signature list".format(name=self.name_tag))
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
            if l == 'gpg-pubkey':
                continue

            if l.endswith('(none)'):
                # These results are coming back with two leading
                # single-quotes and the trailing string ' (none)'.
                # Let's normalize that.
                clean_pkg_name = l[:-7]
                res['items'].append(clean_pkg_name)
                self.runtime.log_verbose("[Verify: {name}] Unsigned package: {pkg}".format(pkg=clean_pkg_name, name=self.name_tag))

        if len(res['items']) > 0:
            self.status = 'failed'
            self.failures['check_sigs'] = res

    def check_versions(self):
        """Ensure the correct package versions are installed for this image"""
        res = {
            'description': 'Installed package target version validation',
            'items': [],
        }
        self.runtime.log_verbose("[Verify: {name}] Checking atomic openshift version".format(name=self.name_tag))
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
                self.runtime.log_verbose("[Verify: {name}] Orphaned Package: {pkg}".format(name=self.name_tag, pkg=l))

        if len(res['items']) > 0:
            self.status = 'failed'
            self.failures['check_orphans'] = res
