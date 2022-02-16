import json
from tenacity import retry, stop_after_attempt, wait_fixed
from urllib import request
from elliottlib import util, exectools, constants


def release_url(version, arch="x86_64", private=False):
    """
    base url for a release stream in the release browser (AWS bucket).

    @param version  The 4.y ocp version as a string (e.g. "4.6")
    @param arch  architecture we are interested in (e.g. "s390x")
    @param private  boolean, true for private stream, false for public (currently, no effect)
    @return e.g. "https://releases-rhcos-art...com/storage/releases/rhcos-4.6-s390x"
    """
    # TODO: create private rhcos builds and do something with "private" here
    return f"{constants.RHCOS_RELEASES_BASE_URL}/rhcos-{version}{util.brew_suffix_for_arch(arch)}"


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
def get_build_meta(build_id, version, arch="x86_64", private=False, meta_type="meta"):
    return _build_meta(build_id, version, arch, private, meta_type)


def _build_meta(build_id, version, arch="x86_64", private=False, meta_type="meta"):
    """
    rhcos metadata for an id in the given stream from the release browser.
    meta_type is "meta" for the build record or "commitmeta" for its ostree content.

    @return  a "meta" build record e.g.:
     https://releases-rhcos-art.cloud.privileged.psi.redhat.com/storage/releases/rhcos-4.1/410.81.20200520.0/meta.json
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
    url = f"{release_url(version, arch, private)}/{build_id}/"
    # before 4.3 the arch was not included in the path
    vtuple = tuple(int(f) for f in version.split("."))
    url += f"{meta_type}.json" if vtuple < (4, 3) else f"{arch}/{meta_type}.json"
    with request.urlopen(url) as req:
        return json.loads(req.read().decode())


def get_build_from_payload(payload_pullspec):
    rhcos_tag = 'machine-os-content'
    out, err = exectools.cmd_assert(["oc", "adm", "release", "info", "--image-for", rhcos_tag, "--", payload_pullspec])
    if err:
        raise Exception(f"Error running oc adm: {err}")
    rhcos_pullspec = out.split('\n')[0]
    out, err = exectools.cmd_assert(["oc", "image", "info", "-o", "json", rhcos_pullspec])
    if err:
        raise Exception(f"Error running oc adm: {err}")
    image_info = json.loads(out)
    build_id = image_info["config"]["config"]["Labels"]["version"]
    arch = image_info["config"]["config"]["Labels"]["architecture"]
    return build_id, arch


def get_rpm_nvrs(build_id, version, arch, private=''):
    stream_name = f"{arch}{'-priv' if private else ''}"
    try:
        commitmeta = get_build_meta(build_id, version, arch, private, meta_type="commitmeta")
        rpm_list = commitmeta.get("rpmostree.rpmdb.pkglist")
        if not rpm_list:
            raise Exception(f"no pkglist in {commitmeta}")

    except Exception as ex:
        problem = f"{stream_name}: {ex}"
        util.red_print(f"error finding RHCOS {problem}")
        return None

    rpms = [(r[0], r[2], r[3]) for r in rpm_list]
    return rpms
