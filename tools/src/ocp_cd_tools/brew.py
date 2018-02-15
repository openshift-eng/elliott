"""
Utility functions for general interactions with Red Hat Bugzilla
"""

# stdlib
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing import cpu_count
import shlex

# ours
import ocp_cd_tools.common
import ocp_cd_tools.constants

# 3rd party
import click
import requests
from requests_kerberos import HTTPKerberosAuth


def get_brew_build(nvr, product_version='', session=None):
    """5.2.2.1. GET /api/v1/build/{id_or_nvr}

    Get Brew build details.

    https://errata.devel.redhat.com/developer-guide/api-http-api.html#api-get-apiv1buildid_or_nvr

    :param str nvr: A name-version-release string of a brew rpm/image build
    :param str product_version: The product version tag as given to ET
    when attaching a build
    :param requests.Session session: A python-requests Session object,
    used for for connection pooling. Providing `session` object can
    yield a significant reduction in total query time when looking up
    many builds.

    http://docs.python-requests.org/en/master/user/advanced/#session-objects

    :return: If the build is discovered, a Build object with the build
    details is returned. False if no build is discovered for the given
    nvr.

    """
    if session is not None:
        res = session.get(ocp_cd_tools.constants.errata_get_build_url.format(id=nvr),
                          auth=HTTPKerberosAuth())
    else:
        res = requests.get(ocp_cd_tools.constants.errata_get_build_url.format(id=nvr),
                           auth=HTTPKerberosAuth())
    if res.status_code == 200:
        return Build(nvr=nvr, body=res.json(), product_version=product_version)
    else:
        raise BrewBuildException("Invalid brew build given: {build}".format(build=nvr))


def find_unshipped_builds(runtime, base_tag, product_version, kind='rpm'):
    """Find builds for a product and return a list of the builds only
    labeled with the -candidate tag.

    :param Runtime runtime: The runtime context object
    :param str base_tag: The tag to search for shipped/candidate
    builds. This is combined with '-candidate' to return the build
    difference.
    :param str product_version: The product version tag as given to ET
    when attaching a build
    :param str kind: Search for RPM builds by default. 'image' is also
    acceptable

    For example, if `base_tag` is 'rhaos-3.7-rhel7' then this will
    look for two sets of tagged builds:

    (1) 'rhaos-3.7-rhel7'
    (2) 'rhaos-3.7-rhel7-candidate'

    The items returned are those ONLY present in #2. The results are
    a tuple splitting the results into two lists:

    :return: A list of Build objects of builds that are not attached
    to any past or current advisory
    """
    if kind == 'rpm':
        candidate_builds = BrewTaggedRPMBuilds(base_tag + "-candidate")
        shipped_builds = BrewTaggedRPMBuilds(base_tag)
    elif kind == 'image':
        candidate_builds = BrewTaggedImageBuilds(base_tag + "-candidate")
        shipped_builds = BrewTaggedImageBuilds(base_tag)

    # Multiprocessing may seem overkill, but these queries can take
    # longer than you'd like
    pool = ThreadPool(cpu_count())
    results = pool.map(
        lambda builds: builds.refresh(runtime),
        [candidate_builds, shipped_builds])
    # Wait for results
    pool.close()
    pool.join()

    # Builds only tagged with -candidate (not shipped yet)
    unshipped_builds = candidate_builds.builds.difference(shipped_builds.builds)

    # Re-use TCP connection to speed things up
    session = requests.Session()

    # We could easily be making scores of requests, one for each build
    # we need information about. May as well do it in parallel.
    pool = ThreadPool(cpu_count())
    results = pool.map(
        lambda nvr: get_brew_build(nvr, product_version, session=session),
        list(unshipped_builds))
    # Wait for results
    pool.close()
    pool.join()

    # We only want builds not attached to an existing advisory
    return [b for b in results if not b.attached]


def get_tagged_image_builds(runtime, tag):
    """Wrapper around shelling out to run 'brew list-tagged' for a given tag.

    :param Runtime runtime: A runtime context object
    :param str tag: The tag to list builds from
    """
    query_string = "brew list-tagged {tag} --latest --type=image --quiet".format(tag=tag)
    # --latest - Only the last build for that package
    # --type=image - Only show container images builds
    # --quiet - Omit field headers in output

    return ocp_cd_tools.common.gather_exec(runtime, shlex.split(query_string))


def get_tagged_rpm_builds(runtime, tag, arch='src'):
    """Wrapper around shelling out to run 'brew list-tagged' for a given tag.

    :param Runtime runtime: A runtime context object
    :param str tag: The tag to list builds from
    :param str arch: Filter results to only this architecture
    """
    query_string = "brew list-tagged {tag} --latest --rpm --quiet --arch {arch}".format(
        tag=tag, arch=arch)
    # --latest - Only the last build for that package
    # --rpm - Only show RPM builds
    # --quiet - Omit field headers in output
    # --arch {arch} - Only show builds of this architecture

    return ocp_cd_tools.common.gather_exec(runtime, shlex.split(query_string))


class BrewTaggedImageBuilds(object):
    """
    Abstraction around working with lists of brew tagged image
    builds. Ensures the result set is formatted correctly for this
    build type.
    """
    def __init__(self, tag):
        self.tag = tag
        self.builds = set([])

    def refresh(self, runtime):
        """Refresh or build initial list of brew builds

        :return: True if builds could be found for the given tag

        :raises: Exception if there is an error looking up builds
        """
        rc, stdout, stderr = get_tagged_image_builds(runtime, self.tag)

        if rc != 0:
            raise Exception("Failed to get brew builds for tag: {tag} - {err}".format(tag=self.tag, err=stderr))
        else:
            builds = set(stdout.splitlines())
            for b in builds:
                self.builds.add(b.split()[0])

        return True


class BrewTaggedRPMBuilds(object):
    """
    Abstraction around working with lists of brew tagged rpm
    builds. Ensures the result set is formatted correctly for this
    build type.
    """
    def __init__(self, tag):
        self.tag = tag
        self.builds = set([])

    def refresh(self, runtime):
        """Refresh or build initial list of brew builds

        :return: True if builds could be found for the given tag

        :raises: Exception if there is an error looking up builds
        """
        rc, stdout, stderr = get_tagged_rpm_builds(runtime, self.tag)

        print("Refreshing for tag: {tag}".format(tag=self.tag))

        if rc != 0:
            raise Exception("Failed to get brew builds for tag: {tag} - {err}".format(tag=self.tag, err=stderr))
        else:
            builds = set(stdout.splitlines())
            for b in builds:
                # The results come back with the build arch (.src)
                # appended. Remove that if it is in the string.
                try:
                    self.builds.add(b[:b.index('.src')])
                except ValueError:
                    # Raised if the given substring is not found
                    self.builds.add(b)

        return True


class Build(object):
    """An existing brew build

How might you use this object? Great question. I'd start by fetching
the details of a known build from the Errata Tool using the
/api/v1/build/{id_or_nvr} API endpoint. Then take that build NVR or ID
and the build object from the API and initialize a new Build object
from those.

Save yourself some time and use the ocp_cd_tools.brew.get_brew_build()
function. Give it an NVR or a build ID and it will give you an
initialized Build object (provided the build exists).

    """
    def __init__(self, nvr=None, body={}, product_version=''):
        """Model for a brew build.

        :param str nvr: Name-Version-Release (or build ID) of a brew build

        :param dict body: An object as one gets from the errata tool
        /api/v1/build/{id_or_nvr} REST endpoint. See also:
        get_brew_build() (above)

        :param str product_version: The tag (from Errata Tool) of the
        product this build will be attached to, for example:
        "RHEL-7-OSE-3.9". This is only useful when representing this
        object as an item that would be given to the Errata Tool API
        add_builds endpoint (see: Build.to_json()).
        """
        self.nvr = nvr
        self.body = body
        self.all_errata = []
        self.attached = False
        self.kind = ''
        self.path = ''
        self.product_version = product_version
        self.process()

    def __str__(self):
        return self.nvr

    def __repr__(self):
        return "Build({nvr})".format(nvr=self.nvr)

    # Set addition
    def __eq__(self, other):
        return self.nvr == other.nvr

    # Set addition
    def __ne__(self, other):
        return self.nvr != other.nvr

    # List sorting
    def __gt__(self, other):
        return self.nvr > other.nvr

    # List sorting
    def __lt__(self, other):
        return self.nvr < other.nvr

    def process(self):
        """Generate some easy to access attributes about this build so we
don't have to do extra manipulation later back in the view"""
        # Has this build been attached to any erratum?
        if 'all_errata' in self.body:
            for erratum in self.body['all_errata']:
                self.all_errata.append(erratum['name'])
            self.attached = len(self.all_errata) > 0

        # What kind of build is this?
        if 'files' in self.body:
            # All of the files are provided. What we're trying to do
            # is figure out if this build classifies as one of the
            # kind of builds we work with: RPM builds and Container
            # Image builds.
            #
            # We decide opportunistically, hence the abrupt
            # breaks. This decision process may require tweaking in
            # the future.
            #
            # I've only ever seen OSE image builds having 1 item (a
            # tar file) in the 'files' list. On the other hand, I have
            # seen some other general product builds that have both
            # tars and rpms (and assorted other file types), and I've
            # seen pure RPM builds with srpms and rpms...
            for f in self.body['files']:
                if f['type'] == 'rpm':
                    self.kind = 'rpm'
                    self.file_type = 'rpm'
                    break
                elif f['type'] == 'tar':
                    self.kind = 'image'
                    self.file_type = 'tar'
                    break

    def to_json(self):
        """Method for adding this build to advisory via the Errata Tool
API. This is the body content of the erratum add_builds endpoint."""
        return {
            'product_version': self.product_version,
            'build': self.nvr,
            'file_types': [self.file_type],
        }


class BrewBuildException(Exception):
    pass
