"""
This module defines a set of functions for running and monitoring
asynchronous tasks and sub processes.
"""

import time
import subprocess


class RetryException(Exception):
    """
    Provide a custom exception for retry failures
    """
    pass


def retry(retries, task_f, check_f=bool, wait_f=None):
    """
    Try a function up to n times.
    Raise an exception if it does not pass in time

    :param retries int: The number of times to retry
    :param task_f func: The function to be run and observed
    :param func()bool check_f: a function to check of task_f is complete
    :param func()bool wait_f: a function to run between checks
    """
    for attempt in range(retries):
        ret = task_f()
        if check_f(ret):
            return ret
        if attempt < retries - 1 and wait_f is not None:
            wait_f(attempt)
    raise RetryException("Giving up after {} failed attempt(s)".format(retries))


def parse_taskinfo(out):
    """
    This function generates a series of text lines from an input stream.
    Each line which begins with "State:" is returned.

    This is specifically for output from the brew task-watch command
    """
    return next(
        (l[7:] for l in out.splitlines() if l.startswith("State: ")),
        "unknown")


def watch_task(log_f, task_id):
    """
    This function opens a brew CLI sub-process and observes the output stream.
    When the task exits, the funtion returns the return state.
    The loop polls every 2 minutes.
    If a timeout is exceeded (4 hours), the watching process is killed.
    """
    start = time.time()
    task = subprocess.Popen(
        ("brew", "watch-task", str(task_id)),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while task.poll() is None:
        info = subprocess.check_output(("brew", "taskinfo", str(task_id)))
        log_f("Task state: {}".format(parse_taskinfo(info)))
        if time.time() - start < 4 * 60 * 60:
            time.sleep(2 * 60)
        else:
            log_f("Timeout building image")
            subprocess.check_call(("brew", "cancel", str(task_id)))
            task.kill()
    return task.returncode, task.stdout.read(), task.stderr.read()
