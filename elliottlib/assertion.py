"""
The assertion module provides functions that will raise an exception if
the asserted condition is not met.

The use of the FileNotFound exception makes this Python3 ready.
Making them functions keeps the exception definition localized.
"""
from __future__ import absolute_import, print_function, unicode_literals
import os
import errno

# Create FileNotFound for Python2
try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError

# Create ChildProcessError for Python2
try:
    ChildProcessError
except NameError:
    ChildProcessError = IOError


def isdir(path, message):
    """
    Raise an exception if the given directory does not exist.

    :param path: The path to a directory to be tested
    :param message: A custom message to report in the exception

    :raises: FileNotFoundError
    """
    if not os.path.isdir(path):
        raise FileNotFoundError(
            errno.ENOENT,
            "{}: {}".format(message, os.strerror(errno.ENOENT)), path)


def isfile(path, message):
    """
    Raise an exception if the given file does not exist.

    :param path: The path to a file to be tested
    :param message: A custom message to report in the exception

    :raises: FileNotFoundError
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(
            errno.ENOENT,
            "{}: {}".format(message, os.strerror(errno.ENOENT)), path)


def success(exitcode, message):
    """
    Raise an IO Error if the return code from a subprocess is non-zero

    :param exitcode: The return code from a subprocess run
    :param message: A custom message if the process failed
    :raises: ChildProcessError
    """
    if exitcode != 0:
        raise ChildProcessError("Command returned non-zero exit status: %s" % message)
