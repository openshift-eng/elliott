from model import Model, ModelException, Missing
import yaml

DEFAULT_REPOTYPE = 'signed'


class Repo(object):
    """Represents a single yum repository and provides sane ways to
    access each property based on the arch or repo type."""

    def __init__(self, name, data, valid_arches):
        self.name = name
        self._valid_arches = valid_arches
        self._data = Model(data)
        for req in ['conf', 'content_set']:
            if req not in self._data:
                raise ValueError('Repo definitions must contain "{}" key!'.format(req))
        if self._data.conf.baseurl is Missing:
            raise ValueError('Repo definitions must include conf.baseurl!')

        # fill out default conf values
        conf = self._data.conf
        conf.name = conf.get('name', name)
        conf.enabled = conf.get('enabled', 0)
        self.enabled = conf.enabled == 1
        conf.gpgcheck = conf.get('gpgcheck', 0)

        self.repotypes = [DEFAULT_REPOTYPE]
        self.baseurl(DEFAULT_REPOTYPE)  # run once just to populate self.repotypes

    @property
    def enabled(self):
        """Allows access via repo.enabled"""
        return self._data.conf.enabled == 1

    @enabled.setter
    def enabled(self, val):
        """Set enabled option without digging direct into the underlying data"""
        self._data.conf.enabled = 1 if val else 0

    def __repr__(self):
        """For debugging mainly, to display contents as a dict"""
        return str(self._data)

    def baseurl(self, repotype):
        """Get baseurl based on repo type, if one was specified for this repo."""
        bu = self._data.conf.baseurl
        if isinstance(bu, str):
            return bu
        elif isinstance(bu, dict):
            if repotype not in bu:
                raise ValueError('{} is not a valid repotype option in {}'.format(repotype, bu.keys()))
            self.repotypes = list(bu.keys())
            return bu[repotype]
        else:
            raise ValueError('baseurl must be str or dict!')

    def content_set(self, arch):
        """Return content set name for given arch with sane fallbacks and error handling."""

        if arch not in self._valid_arches:
            raise ValueError('{} is not a valid arch!')
        if self._data.content_set[arch] is Missing:
            if self._data.content_set['default'] is Missing:
                raise ValueError('{} does not contain a content_set for {} and no default was provided.'.format(self.name, arch))
            return self._data.content_set['default']
        else:
            return self._data.content_set[arch]

    def conf_section(self, repotype, enabled=None):
        """Generates and returns the yum .repo section for this repo,
        based on given type and enabled state"""

        result = '[{}]\n'.format(self.name)
        for k, v in self._data.conf.iteritems():
            line = '{} = {}\n'
            if k == 'baseurl':
                line = line.format('baseurl', self.baseurl(repotype))
            else:
                if k is 'enabled' and enabled is not None:
                    v = 1 if enabled else 0
                line = line.format(k, v)
            result += line
        result += '\n'
        return result


# base empty repo section for disabling repos in Dockerfiles
EMPTY_REPO = """
[{0}]
baseurl = http://download.lab.bos.redhat.com/rcm-guest/puddles/RHAOS/AtomicOpenShift_Empty/
enabled = 1
gpgcheck = 0
name = {0}
"""

# Base header for all content_sets.yml output
CONTENT_SETS = """
# This file is managed by the OpenShift Image Tool: https://github.com/openshift/enterprise-images,
# by the OpenShift Continuous Delivery team (#aos-cd-team on IRC).
# Any manual changes will be overwritten by OIT on the next build.
#
# This is a file defining which content sets (yum repositories) are needed to
# update content in this image. Data provided here helps determine which images
# are vulnerable to specific CVEs. Generally you should only need to update this
# file when:
#    1. You start depending on a new product
#    2. You are preparing new product release and your content sets will change
#
# See https://mojo.redhat.com/docs/DOC-1023066 for more information on
# maintaining this file and the format and examples
#
# You should have one top level item for each architecture being built. Most
# likely this will be x86_64 and ppc64le initially.
---
"""


class Repos(object):
    """
    Represents the entire collection of repos and provides
    automatic content_set and repo conf file generation.
    """
    def __init__(self, repos, arches):
        self._arches = arches
        self._repos = {}
        repotypes = []
        names = []
        for name, repo in repos.iteritems():
            names.append(name)
            self._repos[name] = Repo(name, repo, self._arches)
            repotypes.extend(self._repos[name].repotypes)
        self.names = tuple(names)
        self.repotypes = list(set(repotypes))  # leave only unique values

    def __getitem__(self, item):
        """Allows getting a Repo() object simply by name via repos[repo_name]"""
        if item not in self._repos:
            raise ValueError('{} is not a valid repo name!'.format(item))
        return self._repos[item]

    def __repr__(self):
        """Mainly for debugging to dump a dict representation of the collection"""
        return str(self._repos)

    def repo_file(self, repo_type, enabled_repos=[], empty_repos=[]):
        """Returns the string contents of a yum .repo file for the given
        type, enabled repos, and dummy 'emtpy' repos. Contents written to file
        by external accessor.
        """

        result = ''
        for r in self._repos.itervalues():
            result += r.conf_section(repo_type, enabled=(r.name in enabled_repos))
        for er in empty_repos:
            result += EMPTY_REPO.format(er)
        return result

    def content_sets(self, enabled_repos=[]):
        """Generates a valid content_sets.yml file based on the currently
        configured and enabled repos in the collection. Using the correct
        name for each arch."""

        result = {}
        for a in self._arches:
            result[a] = []
            for r in self._repos.itervalues():
                if r.enabled or r.name in enabled_repos:
                    cs = r.content_set(a)
                    if cs:  # possible to be forced off by setting to null
                        result[a].append(cs)

        return CONTENT_SETS + yaml.dump(result, default_flow_style=False)
