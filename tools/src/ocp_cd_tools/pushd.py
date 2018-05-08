"""
This file contains the definition of a class that can be used like shell
pushd and popd.

The Dir object is a context_manager that can be used with the Python 'with'
clause.  The context manager idiom allows the user to execute some commands
in a working directory other than the CWD and return without needing to
explicitly handle it.

Example:

  # os.getcwd() returns /tmp/somewhere
  with Dir("/tmp/somewhere/else"):
      # os.getcwd() returns /tmp/somewhere/else
      ....

  # os.getcwd() returns /tmp/somewhere
"""

import os
import threading


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

    def __init__(self, newdir):
        self.dir = newdir
        self.previous_dir = None

    def __enter__(self):
        self.previous_dir = self.getcwd()
        os.chdir(self.dir)
        self._tl.cwd = self.dir
        return self.dir

    def __exit__(self, *args):
        os.chdir(self.previous_dir)
        self._tl.cwd = self.previous_dir

    @classmethod
    def getcwd(cls):
        """
        Provide a context dependent current working directory. This method
        will return the directory currently holding the lock.
        """
        if not hasattr(cls._tl, "cwd"):
            cls._tl.cwd = os.getcwd()
        return cls._tl.cwd
