import urllib
import json
import functools
import semver
from elliottlib import exectools, util, constants


def sort_semver(versions):
    return sorted(versions, key=functools.cmp_to_key(semver.compare), reverse=True)


def get_latest_fast_ocp(version, arch):
    """
    Queries Cincinnati and returns latest release version for the given X.Y version
    from the fast channel
    """

    arch = 'amd64' if arch == 'x86_64' else arch
    channel = f'fast-{version}'
    url = f'{constants.CINCINNATI_BASE_URL}?arch={arch}&channel={channel}'

    req = urllib.request.Request(url)
    req.add_header('Accept', 'application/json')
    content = exectools.urlopen_assert(req).read()
    graph = json.loads(content)
    versions = [node['version'] for node in graph['nodes']]
    if not versions:
        util.red_print(f"No releases found in {channel}")
        return
    descending_versions = sort_semver(versions)
    return descending_versions[0]
