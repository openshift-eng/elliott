"""
This module contains a set of functions for managing shell commands
consistently. It adds some logging and some additional capabilties to the
ordinary subprocess behaviors.
"""

from __future__ import print_function

import subprocess
import time
import shlex

import logging
import pushd
import assertion

SUCCESS = 0


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
    :param func()bool check_f: a function to check if task_f is complete
    :param func()bool wait_f: a function to run between checks
    """
    for attempt in range(retries):
        ret = task_f()
        if check_f(ret):
            return ret
        if attempt < retries - 1 and wait_f is not None:
            wait_f(attempt)
    raise RetryException("Giving up after {} failed attempt(s)".format(retries))


#
# TODO: Formerly common.exec_cmd()
# TODO: move to distgit - Used directly only there. markllama 20180306
#
def cmd_log(cmd, logger=None):
    """
    Executes a command, redirecting its output to the log file.

    If called while the `Dir` context manager is in effect, guarantees that the
    process is executed in that directory, even if it is no longer the current
    directory of the process (i.e. it is thread-safe).

    :param cmd: The command and arguments to execute
    :return: exit code of cmd
    """

    logger = logger or logging.getLogger()

    # The first argument can be string or list. Convert to list for subprocess
    if not isinstance(cmd, list):
        cmd_list = shlex.split(cmd)
    else:
        cmd_list = cmd

    logger.info("Executing:cmd_log: {}".format(cmd_list))
    log_stream = logger.handlers[0].stream
    
    cwd = pushd.Dir.getcwd()
    process = subprocess.Popen(
        cmd_list, cwd=cwd,
        stdout=log_stream, stderr=log_stream)
    result = process.wait()

    cmd_info = '[cwd={}]: {}'.format(cwd, cmd_list)
    if result != 0:
        logger.info("Process exited with error {}: {}\n".format(cmd_info, result))
    else:
        logger.info("Process exited without error {}\n".format(cmd_info))

    return result


#
# TODO: was common.assert_exec()
# TODO: Used directly in distgit, rpm and runtime (once, for a git clone)
# TODO: refactor and remove.  markllama 20180306
#
def cmd_assert(cmd, retries=1, pollrate=60, logger=None):
    """
    Run a command, logging (using exec_cmd) and raise an exception if the
    return code of the command indicates failure.
    Try the command multiple times if requested.

    :param cmd <string|list>: A shell command
    :param retries int: The number of times to try before declaring failure
    :param pollrate int: how long to sleep between tries
    """

    # get a copy of the logger to write
    logger = logger or logging.getLogger()

    for try_num in range(0, retries):
        if try_num > 0:
            logger.info(
                "cmd_assert: Failed {} times. Retrying in {} seconds: {}".
                format(try_num, pollrate, cmd))
            time.sleep(pollrate)

        result = cmd_log(cmd)
        if result == SUCCESS:
            break

    logger.info("cmd_assert: Final result = {} in {} tries.".
                format(result, try_num))

    assertion.success(
        result,
        "Error running [{}] {}. See debug log: {}.".
        format(pushd.Dir.getcwd(), cmd, logger.handlers[0].baseFilename))



#
# TODO: Formerly common.gather_exec.
# TODO: Used directly in distgit, image, rpm, runtime
# TODO: refactor in those places then remove this comment - markllama 20180306
#
def cmd_gather(cmd, logger=None):
    """
    Runs a command and returns rc,stdout,stderr as a tuple.

    If called while the `Dir` context manager is in effect, guarantees that the
    process is executed in that directory, even if it is no longer the current
    directory of the process (i.e. it is thread-safe).

    :param cmd: The command and arguments to execute
    :return: (rc,stdout,stderr)
    """
    logger = logger or logging.getLogger()

    if not isinstance(cmd, list):
        cmd_list = shlex.split(cmd)
    else:
        cmd_list = cmd

    cwd = pushd.Dir.getcwd()
    cmd_info = '[cwd={}]: {}'.format(cwd, cmd_list)

    logger.info("Executing:cmd_gather {}".format(cmd_info))
    proc = subprocess.Popen(
        cmd_list, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    rc = proc.returncode
    logger.info(
        "Process {}: exited with: {}\nstdout>>{}<<\nstderr>>{}<<\n".
        format(cmd_info, rc, out, err))
    return rc, out, err
