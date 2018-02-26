import os
import errno
import functools
import subprocess
import threading
import time
import traceback
import sys
import koji
import koji_cli.lib

BREW_HUB = "https://brewhub.engineering.redhat.com/brewhub"
BREW_IMAGE_HOST = "brew-pulp-docker01.web.prod.ext.phx2.redhat.com:8888"
CGIT_URL = "http://pkgs.devel.redhat.com/cgit"


class Dir(object):
    """
    Context manager to handle directory changes safely.

    On `__enter__`, `chdir`s to the given directory and on `__exit__`, `chdir`s
    back to restore the previous `cwd`.

    The current directory is also kept on thread-local storage and can be
    accessed (e.g. by multi-threaded programs that cannot rely on `chdir`) via
    the `getcwd` static method.

    The `assert_exec` and `gather_exec` member functions use the directory in
    effect automatically.
    """
    _tl = threading.local()

    def __init__(self, dir):
        self.dir = dir
        self.previousDir = None

    def __enter__(self):
        self.previousDir = self.getcwd()
        os.chdir(self.dir)
        self._tl.cwd = self.dir
        return self.dir

    def __exit__(self, *args):
        os.chdir(self.previousDir)
        self._tl.cwd = self.previousDir

    @classmethod
    def getcwd(cls):
        if not hasattr(cls._tl, "cwd"):
            cls._tl.cwd = os.getcwd()
        return cls._tl.cwd


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

    for t in range(0, retries):
        if t > 0:
            runtime.log_verbose("Retrying previous invocation in 60 seconds: %s" % cmd)
            time.sleep(60)

        rc = exec_cmd(runtime, cmd)
        if rc == 0:
            break

    assert_rc0(rc, "Error running %s. See debug log: %s." % (cmd, runtime.debug_log_path))


def exec_cmd(runtime, cmd):
    """
    Executes a command, redirecting its output to the log file.

    If called while the `Dir` context manager is in effect, guarantees that the
    process is executed in that directory, even if it is no longer the current
    directory of the process (i.e. it is thread-safe).

    :param runtime: The runtime object
    :param cmd_list: The command and arguments to execute
    :return: exit code
    """
    if not isinstance(cmd, list):
        cmd_list = cmd.split(' ')
    else:
        cmd_list = cmd

    runtime.log_verbose("Executing:exec_cmd: %s" % cmd_list)
    # https://stackoverflow.com/a/7389473
    runtime.debug_log.flush()
    process = subprocess.Popen(
        cmd_list, cwd=Dir.getcwd(),
        stdout=runtime.debug_log, stderr=runtime.debug_log)
    runtime.log_verbose("Process exited with: %d\n" % process.wait())
    return process.wait()


def gather_exec(runtime, cmd):
    """
    Runs a command and returns rc,stdout,stderr as a tuple.

    If called while the `Dir` context manager is in effect, guarantees that the
    process is executed in that directory, even if it is no longer the current
    directory of the process (i.e. it is thread-safe).

    :param runtime: The runtime object
    :param cmd_list: The command and arguments to execute
    :return: (rc,stdout,stderr)
    """

    if not isinstance(cmd, list):
        cmd_list = cmd.split(' ')
    else:
        cmd_list = cmd

    runtime.log_verbose("Executing:gather_exec: %s" % str(cmd_list))
    p = subprocess.Popen(
        cmd_list, cwd=Dir.getcwd(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    runtime.log_verbose("Process exited with: %d\nstdout>>>%s<<<\nstderr>>>%s<<<\n" % (p.returncode, out, err))
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


def watch_task(log_f, task_id, terminate_event):
    end = time.time() + 4 * 60 * 60
    watcher = koji_cli.lib.TaskWatcher(
        task_id, koji.ClientSession(BREW_HUB), quiet=True)
    error = None
    while error is None:
        watcher.update()
        if watcher.is_done():
            return None if watcher.is_success() else watcher.get_failure()
        log_f("Task state: " + koji.TASK_STATES[watcher.info['state']])
        if terminate_event.wait(timeout=2 * 60):
            error = 'Interrupted'
        elif time.time() > end:
            error = 'Timeout building image'
    log_f(error + ", canceling build")
    subprocess.check_call(("brew", "cancel", str(task_id)))
    return error


class WrapException(Exception):
    """ https://bugs.python.org/issue13831 """
    def __init__(self):
        super(WrapException, self).__init__()
        exc_type, exc_value, exc_tb = sys.exc_info()
        self.exception = exc_value
        self.formatted = "".join(
            traceback.format_exception(exc_type, exc_value, exc_tb))

    def __str__(self):
        return "{}\nOriginal traceback:\n{}".format(
            Exception.__str__(self), self.formatted)


def wrap_exception(func):
    """ Decorate a function, wrap exception if it occurs. """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception:
            raise WrapException()
    return wrapper
