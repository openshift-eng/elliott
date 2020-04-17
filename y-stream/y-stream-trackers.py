#!/usr/bin/env python

from __future__ import print_function
import bugzilla
import os


api_key = open(os.path.expanduser('~/.bugzilla_apikey')).read().strip()

bz = bugzilla.RHBugzilla(url=None, api_key=api_key)
bz.connect('https://bugzilla.redhat.com')

PRODUCT_NAME = "OpenShift Container Platform"
TARGET_RELEASE = "4.4.0"

query = bz.build_query(
    product=PRODUCT_NAME,
    status=["MODIFIED", "ON_QA", "VERIFIED"],
    target_release=TARGET_RELEASE,
    keywords=["Security", "SecurityTracking"],
)


def _get_flaw_cve(flaw):
    # python2 has no .get() for lists
    try:
        return flaw.alias[0]
    except IndexError:
        return None


y_stream_trackers = bz.query(query)
for y_stream_tracker in y_stream_trackers:
    component = y_stream_tracker.summary.split(":")[0].split(" ")[-1]
    blocking_bugs = bz.getbugs(y_stream_tracker.blocks)
    flaw_bugs = filter(lambda x: x.product == "Security Response", blocking_bugs)

    tracker_cves = filter(lambda x: x is not None, (_get_flaw_cve(flaw) for flaw in flaw_bugs))
    if len(tracker_cves) == 0:
        continue
    tracker_flaws = filter(lambda x: _get_flaw_cve(x) in tracker_cves, flaw_bugs)
    flaw_tracker_ids = set([t for f in tracker_flaws for t in f.depends_on])
    trackers = bz.getbugs(flaw_tracker_ids)

    def filter_tracker(tracker):
        if all([
            tracker.product == PRODUCT_NAME,
            component + ":" in tracker.summary,
            tracker.target_release[0] <= TARGET_RELEASE,
            tracker.target_release[0] > "4.0.0",
        ]):
            return True
        return False

    sorted_trackers = sorted(trackers, key=lambda x: x.target_release, reverse=True)
    filtered_trackers = filter(filter_tracker, sorted_trackers)

    print("{} {}".format(" ".join(tracker_cves), component))
    for tracker in filtered_trackers:
        print("\t{} {} {} {}".format(tracker.id, tracker.target_release[0], tracker.status, tracker.resolution))
