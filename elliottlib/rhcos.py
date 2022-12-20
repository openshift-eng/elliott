import json
from tenacity import retry, stop_after_attempt, wait_fixed
from urllib import request
from elliottlib.model import ListModel
from elliottlib import util, exectools, constants

# Historically the only RHCOS container was 'machine-os-content'; see
# https://github.com/openshift/machine-config-operator/blob/master/docs/OSUpgrades.md
# But in the future this will change, see
# https://github.com/coreos/enhancements/blob/main/os/coreos-layering.md
default_primary_container = dict(
    name="machine-os-content",
    build_metadata_key="oscontainer",
    primary=True)


def get_container_configs(runtime):
    """
    look up the group.yml configuration for RHCOS container(s) for this group, or create if missing.
    @return ListModel with Model entries like ^^ default_primary_container
    """
    return runtime.group_config.rhcos.payload_tags or ListModel([default_primary_container])


def release_url(runtime, version, arch="x86_64", private=False):
    """
    base url for a release stream in the release browser (AWS bucket).

    @param version  The 4.y ocp version as a string (e.g. "4.6")
    @param arch  architecture we are interested in (e.g. "s390x")
    @param private  boolean, true for private stream, false for public (currently, no effect)
    @return e.g. "https://releases-rhcos-art...com/storage/releases/rhcos-4.6-s390x"
    """
    # TODO: create private rhcos builds and do something with "private" here
    bucket = arch
    if runtime.group_config.urls.rhcos_release_base[bucket]:
        return runtime.group_config.urls.rhcos_release_base[bucket]
    multi_url = runtime.group_config.urls.rhcos_release_base["multi"]
    bucket_url = runtime.group_config.urls.rhcos_release_base[bucket]
    if multi_url:
        if bucket_url:
            raise ValueError(f"Multiple rhcos_release_base urls found in group config: `multi` and `{bucket}`")
        return multi_url
    if bucket_url:
        return bucket_url

    bucket_suffix = util.brew_suffix_for_arch(arch)
    return f"{constants.RHCOS_RELEASES_BASE_URL}/rhcos-{version}{bucket_suffix}"


# this is hard to test with retries, so wrap testable method
@retry(reraise=True, stop=stop_after_attempt(10), wait=wait_fixed(3))
def latest_build_id(version, arch="x86_64", private=False):
    return _latest_build_id(version, arch, private)


def _latest_build_id(version, arch="x86_64", private=False):
    # returns the build id string or None (or raise exception)
    # (may want to return "schema-version" also if this ever gets more complex)
    with request.urlopen(f"{release_url(version, arch, private)}/builds.json") as req:
        data = json.loads(req.read().decode())
    if not data["builds"]:
        return None
    build = data["builds"][0]
    # old schema just had the id as a string; newer has it in a dict
    return build if isinstance(build, str) else build["id"]


# this is hard to test with retries, so wrap testable method
@retry(reraise=True, stop=stop_after_attempt(10), wait=wait_fixed(3))
def get_build_meta(runtime, build_id, version, arch="x86_64", private=False, meta_type="meta"):
    return _build_meta(runtime, build_id, version, arch, private, meta_type)


def _build_meta(runtime, build_id, version, arch="x86_64", private=False, meta_type="meta"):
    """
    rhcos metadata for an id in the given stream from the release browser.
    meta_type is "meta" for the build record or "commitmeta" for its ostree content.

    @return  a "meta" build record e.g.:
     https://releases-rhcos-art.apps.ocp-virt.prod.psi.redhat.com/storage/releases/rhcos-4.1/410.81.20200520.0/meta.json
     {
         "buildid": "410.81.20200520.0",
         ...
         "oscontainer": {
             "digest": "sha256:b0997c9fe4363c8a0ed3b52882b509ade711f7cdb620cc7a71767a859172f423"
             "image": "quay.io/openshift-release-dev/ocp-v4.0-art-dev"
         },
         ...
     }
    """
    url = f"{release_url(runtime, version, arch, private)}/{build_id}/"
    # before 4.3 the arch was not included in the path
    vtuple = tuple(int(f) for f in version.split("."))
    url += f"{meta_type}.json" if vtuple < (4, 3) else f"{arch}/{meta_type}.json"
    with request.urlopen(url) as req:
        return json.loads(req.read().decode())


def get_build_from_payload(payload_pullspec):
    rhcos_tag = 'machine-os-content'
    out, _ = exectools.cmd_assert(["oc", "adm", "release", "info", "--image-for", rhcos_tag, "--", payload_pullspec])
    rhcos_pullspec = out.split('\n')[0]
    out, _ = exectools.cmd_assert(["oc", "image", "info", "-o", "json", rhcos_pullspec])
    image_info = json.loads(out)
    build_id = image_info["config"]["config"]["Labels"]["version"]
    arch = image_info["config"]["config"]["Labels"]["architecture"]
    return build_id, arch


def get_rpm_nvrs(runtime, build_id, version, arch, private=''):
    stream_name = f"{arch}{'-priv' if private else ''}"
    try:
        commitmeta = get_build_meta(runtime, build_id, version, arch, private, meta_type="commitmeta")
        rpm_list = commitmeta.get("rpmostree.rpmdb.pkglist")
        if not rpm_list:
            raise Exception(f"no pkglist in {commitmeta}")

    except Exception as ex:
        problem = f"{stream_name}: {ex}"
        util.red_print(f"error finding RHCOS {problem}")
        return None

    rpms = [(r[0], r[2], r[3]) for r in rpm_list]
    return rpms
