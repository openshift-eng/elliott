#!/usr/bin/env python3

import os
import sys

import bugzilla
from packaging import version


api_key = None
try:
    api_key = open(os.path.expanduser('~/.bugzilla_apikey')).read().strip()
except FileNotFoundError:
    #  api key in ~/.config/python-bugzilla/bugzillarc will be used
    pass

bz = bugzilla.RHBugzilla(url=None, api_key=api_key)
bz.connect('https://bugzilla.redhat.com')

PRODUCT_NAME = "OpenShift Container Platform"
try:
    TARGET_RELEASE = sys.argv[1]  # e.g. "4.5.0"
except IndexError:
    sys.exit("Target Release required, e.g. '4.5.0'")

query = bz.build_query(
    product=PRODUCT_NAME,
    status=["MODIFIED", "ON_QA", "VERIFIED"],
    target_release=TARGET_RELEASE,
    keywords=["Security", "SecurityTracking"],
)


def _get_flaw_cve(flaw):
    # python has no .get() for lists
    try:
        return flaw.alias[0]
    except IndexError:
        return None


def parse_version(v):
    try:
        return version.parse(v)
    except:
        return v


BZ_PAGE_SIZE = 1000
query["limit"] = BZ_PAGE_SIZE
y_stream_trackers = []
partial = bz.query(query)
while len(partial) == BZ_PAGE_SIZE:
    print(len(partial))
    y_stream_trackers += partial
    query["offset"] += BZ_PAGE_SIZE
    partial = bz.query(query)
y_stream_trackers += partial

for y_stream_tracker in y_stream_trackers:
    component = y_stream_tracker.summary.split(":")[0].split(" ")[-1]
    blocking_bugs = bz.getbugs(y_stream_tracker.blocks)
    flaw_bugs = list(filter(lambda x: x.product == "Security Response", blocking_bugs))

    tracker_cves = list(filter(lambda x: x is not None, (_get_flaw_cve(flaw) for flaw in flaw_bugs)))
    if len(tracker_cves) == 0:
        continue
    tracker_flaws = list(filter(lambda x: _get_flaw_cve(x) in tracker_cves, flaw_bugs))
    flaw_tracker_ids = set([t for f in tracker_flaws for t in f.depends_on])
    trackers = bz.getbugs(flaw_tracker_ids)

    def filter_tracker(tracker):
        tracker_tr = tracker.target_release[0].replace(".z", ".0")
        if all([
            tracker.product == PRODUCT_NAME,
            component + ":" in tracker.summary,
            version.parse(tracker_tr) <= version.parse(TARGET_RELEASE),
            version.parse(tracker_tr) > version.parse("4.0.0"),
        ]):
            return True
        return False

    sorted_trackers = sorted(trackers, key=lambda x: version.parse(x.target_release[0]), reverse=True)
    filtered_trackers = filter(filter_tracker, sorted_trackers)

    print("{} {}".format(" ".join(tracker_cves), component))
    for tracker in filtered_trackers:
        print("\t{} {} {} {}".format(tracker.id, tracker.target_release[0], tracker.status, tracker.resolution))
