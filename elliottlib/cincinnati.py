import urllib
import json
import functools
import semver
from elliottlib import exectools, util

CINCINNATI_BASE_URL = "https://api.openshift.com/api/upgrades_info/v1/graph"


def sort_semver(versions):
    return sorted(versions, key=functools.cmp_to_key(semver.compare), reverse=True)


def get_latest_candidate_ocp(version, arch):
    """
    Queries Cincinnati and returns latest release version for the given X.Y version
    Code referenced from Doozer #release_calc_previous
    """

    arch = 'amd64' if arch == 'x86_64' else arch
    channel = f'candidate-{version}'
    url = f'{CINCINNATI_BASE_URL}?arch={arch}&channel={channel}'

    req = urllib.request.Request(url)
    req.add_header('Accept', 'application/json')
    content = exectools.urlopen_assert(req).read()
    graph = json.loads(content)
    versions = [node['version'] for node in graph['nodes']]
    if not versions:
        util.red_print("No stable release versions found")
        return
    descending_versions = sort_semver(versions)
    return descending_versions[0]
