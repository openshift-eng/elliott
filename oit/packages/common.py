import os
import errno
import subprocess


class Dir(object):

    def __init__(self, dir):
        self.dir = dir

    def __enter__(self):
        self.previousDir = os.getcwd()
        os.chdir(self.dir)
        return self.dir

    def __exit__(self, *args):
        os.chdir(self.previousDir)


# Create FileNotFound for Python2
try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError


def assert_dir(path, msg):
    if not os.path.isdir(path):
        raise FileNotFoundError(errno.ENOENT, "%s: %s" % (msg, os.strerror(errno.ENOENT)), path)


def assert_file(path, msg):
    if not os.path.isfile(path):
        raise FileNotFoundError(errno.ENOENT, "%s: %s" % (msg, os.strerror(errno.ENOENT)), path)


def assert_rc0(rc, msg):
    if rc is not 0:
        raise IOError("Command returned non-zero exit status: %s" % msg)


def assert_exec(runtime, cmd_list):
    runtime.verbose("Executing: %s" % cmd_list)
    # process = subprocess.Popen(cmd_list, stdout=runtime.debug_log, stderr=runtime.debug_log)
    process = subprocess.Popen(cmd_list)
    assert_rc0(process.wait(), "Error running %s. See debug log." % cmd_list)
