import os
import errno
import subprocess
import time

BREW_IMAGE_HOST = "brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888"
CGIT_URL = "http://pkgs.devel.redhat.com/cgit"


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


def assert_exec(runtime, cmd, retries=1):
    rc = 0

    for t in range(1, retries):
        if t > 1:
            runtime.log_verbose("Retrying previous invocation in 60 seconds: %s" % cmd)
            time.sleep(60)

        rc = exec_cmd(runtime, cmd), "Error running %s. See debug log: %s." % (cmd, runtime.debug_log_path)
        if rc == 0:
            break

    assert_rc0(rc)


def exec_cmd(runtime, cmd):
    """
    Executes a command, redirecting its output to the log file.
    :return: exit code
    """
    if not isinstance(cmd, list):
        cmd_list = cmd.split(' ')
    else:
        cmd_list = cmd

    runtime.log_verbose("\nExecuting: %s" % cmd_list)
    # https://stackoverflow.com/a/7389473
    runtime.debug_log.flush()
    process = subprocess.Popen(cmd_list, stdout=runtime.debug_log, stderr=runtime.debug_log)
    runtime.log_verbose("Process exited with: %d\n" % process.wait())
    return process.wait()


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


def recursive_overwrite(runtime, src, dest, ignore=set()):
    exclude = ''
    for i in ignore:
        exclude += ' --exclude="{}" '.format(i)
    cmd = 'rsync -av {} {}/ {}/'.format(exclude, src, dest)
    assert_exec(runtime, cmd.split(' '))


class RetryException(Exception):
    pass


def retry(n, f, check_f=bool, wait_f=None):
    for c in xrange(n):
        ret = f()
        if check_f(ret):
            return ret
        if c < n - 1 and wait_f is not None:
            wait_f(c)
    raise RetryException("Giving up after {} failed attempt(s)".format(n))
