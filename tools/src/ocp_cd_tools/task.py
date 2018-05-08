"""
This module defines a set of functions for running and monitoring
asynchronous tasks and sub processes.
"""

import time
import koji
import koji_cli
import subprocess
import logging

import constants


def parse_taskinfo(out):
    """
    This function generates a series of text lines from an input stream.
    Each line which begins with "State:" is returned.

    This is specifically for output from the brew task-watch command
    """
    return next(
        (l[7:] for l in out.splitlines() if l.startswith("State: ")),
        "unknown")


def cancel_brew_build(task_id, reason, logger=None):
    """
    """
    logger = logger or logging.getLogger()

    # Task still running, cancel and clean up
    logger.error(reason + ": canceling build")
    subprocess.check_call(("brew", "cancel", str(task_id)))


def watch_task(task_id, terminate_event=None,
               timeout=14400, poll_interval=120, logger=None):
    """
    This function opens a brew CLI sub-process and observes the output stream.
    When the task exits, the funtion returns the return state.
    The loop polls every 2 minutes.
    If a timeout is exceeded (4 hours), the watching process is killed.

    :param task_id: The id number of a brew/koji task in process
    :param terminate_event: A threading.Event() object

    :return: True for success, False for incompleted, otherwise the fail result
    """
    start = time.time()
    end = start + timeout

    if terminate_event is not None:
        interrupted = lambda p: not terminate_event.wait(timeout=p)
    else:
        interrupted = lambda p: time.sleep(p) and False

    watcher = koji_cli.lib.TaskWatcher(
        task_id,
        koji.ClientSession(constants.BREW_HUB),
        quiet=True)

    while not watcher.is_done():

        # wait one poll interval (unless interrupted)
        if interrupted(poll_interval):
            cancel_brew_build(task_id, "Build Interrupted")
            return False

        # Test
        if time.time() > end:
            cancel_brew_build(task_id, "Timeout exceeded")
            return False

    return watcher.is_success() or watcher.get_failure()
