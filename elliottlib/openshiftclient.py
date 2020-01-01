"""
Utility functions and object abstractions for general interactions
with oc cli
"""
from __future__ import absolute_import, print_function, unicode_literals

# stdlib
from subprocess import check_output, CalledProcessError
import json

# ours
from elliottlib.exceptions import ElliottFatalError


def get_bug_list(working_dir, old, new):
    """
    Get fixed bugzilla IDs between two payloads. Needs to clone
    the entire okd repo, so it can be quite slow.

    :param str working_dir: file location to clone okd repo
    :param str old: URL to the previous payload
    :param str new: URL to the current payload

    :return: A list of BZ IDs
    :raises exceptions.CalledProcessError: When oc returns a non-zero exit

    """
    bug_list = []
    try:
        bug_list = check_output([
            'oc', 'adm', 'release', 'info',
            '-o', 'name',  # only output BZ IDs
            '--bugs={}/origin'.format(working_dir),  # clone origin to working dir
            '--changes-from={}'.format(old),
            new  # payloads to compare
        ]).splitlines()
    except CalledProcessError as e:
        raise ElliottFatalError("command '{}' return with error (code {}): {}".format(e.cmd, e.returncode, e.output))

    return bug_list


def get_build_list(old, new):
    """
    Get changed container builds between two payloads.

    :param str old: URL to the previous payload
    :param str new: URL to the current payload

    :return: A list of brew NVRs
    :raises exceptions.CalledProcessError: When oc returns a non-zero exit

    """
    build_list = []
    oc_output = ""
    try:
        oc_output = check_output([
            'oc', 'adm', 'release', 'info',
            '--output=json',
            '--changes-from={}'.format(old),
            new  # payloads to compare
        ])
    except CalledProcessError as e:
        raise ElliottFatalError("command '{}' return with error (code {}): {}".format(e.cmd, e.returncode, e.output))

    payload_json = json.loads(oc_output)
    changed_images = []

    for k, v in payload_json["changedImages"].items():
        if k == "machine-os-content":
            continue  # no use in comparing this as it doesn't go in the advisory
        if v["to"]:
            changed_images.append(v["to"]["from"]["name"])

    for i in changed_images:
        build_list.append(get_image_nvr(i))

    return build_list


def get_image_nvr(image):
    """
    Get brew NVR from a oc output.

    :param str image: reference to an image in the payload

    :return: A brew NVR
    :raises exceptions.CalledProcessError: When oc returns a non-zero exit

    """
    try:
        oc_output = check_output(['oc', 'image', 'info', '--output=json', image])
    except CalledProcessError as e:
        raise ElliottFatalError("command '{}' return with error (code {}): {}".format(e.cmd, e.returncode, e.output))

    try:
        image_json = json.loads(oc_output)
        image_name = image_json['config']['config']['Labels']['com.redhat.component']
        image_version = image_json['config']['config']['Labels']['version']
        image_release = image_json['config']['config']['Labels']['release']
    except Exception:
        print("This image json does not have the expected fields:\n" + oc_output)
        raise

    return "{}-{}-{}".format(image_name, image_version, image_release)
