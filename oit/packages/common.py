import os
import errno
import subprocess
import shutil

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
    runtime.verbose("\nExecuting: %s" % cmd_list)
    # https://stackoverflow.com/a/7389473
    runtime.debug_log.flush()
    process = subprocess.Popen(cmd_list, stdout=runtime.debug_log, stderr=runtime.debug_log)
    runtime.verbose("Process exited with: %d\n" % process.wait())
    assert_rc0(process.wait(), "Error running %s. See debug log: %s." % (cmd_list, runtime.debug_log_path))


def gather_exec(runtime, cmd_list):
    """
    Runs a command and returns rc,stdout,stderr as a tuple
    :param runtime: The runtime object
    :param cmd_list: The command and arguments to execute
    :return: (rc,stdout,stderr)
    """
    p = subprocess.Popen(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    return p.returncode, out, err

def recursive_overwrite(src, dest, ignore=None):
    if os.path.isdir(src):
        if not os.path.isdir(dest):
            os.makedirs(dest)
        files = os.listdir(src)
        if ignore is not None:
            ignored = ignore(src, files)
        else:
            ignored = set()
        for f in files:
            if f not in ignored:
                recursive_overwrite(os.path.join(src, f),
                                    os.path.join(dest, f),
                                    ignore)
    else:
        shutil.copyfile(src, dest)
