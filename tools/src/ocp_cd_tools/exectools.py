"""
This module contains a set of functions for managing shell commands consistently
It adds some logging and some additional capabilties to the ordinary subprocess
behaviors.
"""

from __future__ import print_function

import subprocess
import time
import shlex

import logs
import pushd
import assertion

SUCCESS = 0


#
# TODO: Formerly common.exec_cmd()
# TODO: move to distgit - Used directly only there. markllama 20180306
#
def cmd_log(cmd):
    """
    Executes a command, redirecting its output to the log file.

    If called while the `Dir` context manager is in effect, guarantees that the
    process is executed in that directory, even if it is no longer the current
    directory of the process (i.e. it is thread-safe).

    :param cmd: The command and arguments to execute
    :return: exit code of cmd
    """

    logger = logs.Log()

    # The first argument can be a string or list. Convert to list for subprocess
    if not isinstance(cmd, list):
        cmd_list = shlex.split(cmd)
    else:
        cmd_list = cmd

    cwd = pushd.Dir.getcwd()
    cmd_info = '[cwd={}]: {}'.format(cwd, cmd_list)

    logger.info("Executing:cmd_log {}".format(cmd_info))
    process = subprocess.Popen(
        cmd_list, cwd=cwd,
        stdout=logger._log_file, stderr=logger._log_file)
    result = process.wait()

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
def cmd_assert(cmd, retries=1, pollrate=60):
    """
    Run a command, logging (using exec_cmd) and raise an exception if the
    return code of the command indicates failure.
    Try the command multiple times if requested.

    :param cmd <string|list>: A shell command
    :param retries int: The number of times to try before declaring failure
    :param pollrate int: how long to sleep between tries
    """

    # get a copy of the logger to write
    logger = logs.Log()

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
        "Error running [{}] {}. See debug log: {}.".format(pushd.Dir.getcwd(), cmd, logger.log_path))


#
# TODO: Formerly common.gather_exec.
# TODO: Used directly in distgit, image, rpm, runtime
# TODO: refactor in those places then remove this comment - markllama 20180306
#
def cmd_gather(cmd):
    """
    Runs a command and returns rc,stdout,stderr as a tuple.

    If called while the `Dir` context manager is in effect, guarantees that the
    process is executed in that directory, even if it is no longer the current
    directory of the process (i.e. it is thread-safe).

    :param cmd: The command and arguments to execute
    :return: (rc,stdout,stderr)
    """
    logger = logs.Log()

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
