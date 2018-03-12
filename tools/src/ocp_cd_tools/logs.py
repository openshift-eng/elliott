"""
This module provides a singleton logging facility for CLI and file logging
It also provides an "event recording" output stream for later machine
parsing
"""
import os
import shutil
import atexit
import multiprocessing
import datetime
import click


#
# These two private functions are registered with atexit to safely close out
# debug/record logs and to remove temporary files if needed.
#
def _close_logs(log):
    log.close()


def _cleanup_log_dir(log_dir):
    shutil.rmtree(log_dir)


#
# Define a set of log levels allowing the user to control the level of output
#
_LOG_LEVELS = ['FATAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']

FATAL = _LOG_LEVELS.index("FATAL")
ERROR = _LOG_LEVELS.index("ERROR")
WARNING = _LOG_LEVELS.index("WARNING")
INFO = _LOG_LEVELS.index("INFO")
DEBUG = _LOG_LEVELS.index("DEBUG")


#
# Define the internal "borg" object.
# See "Python Cookbook", Martelli& Ascher, O'Reilly c. 2002, page 208
#
class _Log(object):
    """
    The initializer object for the internal shared state of the Log objects
    """
    # Define the clean initial state of the log object.  This is not overwritten
    # so that the state can be reset.  This is primarily useful for testing.
    _initial_state = {
        "log_dir": None,
        "verbose": False,
        "cleanup": None,
        "_log_level": INFO,
        "_record_file": None,
        "_log_file": None
    }

    # These locks are used to synchronize writes when multiple threads may be
    # writing to the same files.
    _log_lock = multiprocessing.Lock()
    _record_lock = multiprocessing.Lock()

    _state = _initial_state.copy()

    def __init__(self):
        """
        Set the initial state of the "singleton" object.
        The state is shared by all instances of the class
        """
        try:
            self.__dict__ = self._state
        except Exception:
            _Log._reset()

    @classmethod
    def _reset(cls):
        """
        Reset the logger internal state to the initial state.
        Close open files and copy the initial state over the top
        """
        try:
            log_file = cls._state['_log_file']
            if log_file is not None and not log_file.closed:
                log_file.close()

            record_file = cls._state['_record_file']
            if record_file is not None and not record_file.closed:
                record_file.close()

            for k in cls._initial_state:
                cls._state[k] = cls._initial_state[k]
        except Exception:
            cls._state = cls._initial_state.copy()


class Log(_Log):
    """
    This is the public log object.
    It is not a singleton in the strict sense.
    Two instances are not the same object, but they share internal state.

    The first time a Log is created, the shared state is initialized. Each
    instance after that is created using that same shared state and changes
    to that state are reflected in all instances.

    The instance must be given a destination directory
    """

    def __init__(self, log_dir=None, log_level=None, verbose=None):
        """
        Create a Log object.  The first call populates the internal state.
        Subsequent calls return a new object with the shared state.

        :param log_dir string: The name of a directory to create logs in.
          If none is provided, a random directory is created in /tmp.
          Only used on the the first Log object created.  Attempts to
          set the log_dir after initialization will raise OSError.

        :param log_level int: An integer log level. See DATA
          default: log.INFO

        :param verbose boolean: write to stdout as well as the log file
          default: False

        :param cleanup boolean: delete the logs and directory after close.
          default: False

        :raises OSError: On attempt to initialize twice without reset.
        """

        _Log.__init__(self)

        # Make sure SOME value exists
        if not hasattr(self, 'log_dir'):
            self.log_dir = None

        if self.log_dir is None:
            if log_dir is None:
                raise ValueError("log_dir is required for initialization")
            else:
                self.log_dir = log_dir

        else:
            if log_dir is not None:
                raise OSError(
                    "re-initializing a singleton: current log_dir = {}, new log_dir = {}".
                    format(self.log_dir, log_dir))

        # The user may change the verbose and log level
        if verbose is not None:
            self.verbose = verbose

        if log_level is not None:
            if not isinstance(log_level, int) or log_level not in range(0, 5):
                raise ValueError(
                    "invalid log level {}: Must be int 0-4".format(log_level))
            self._log_level = log_level

        # Check that the destination exists
        if not os.path.exists(self.log_dir):
            raise OSError("directory not found: {}".format(self.log_dir))

        # and is a directory
        if not os.path.isdir(self.log_dir):
            raise OSError(
                "log destination is not a directory: {}".format(self.log_dir))

        if "_log_file" not in self.__dict__:
            self._log_file = None

        if "_record_file" not in self.__dict__:
            self._record_file = None

    @property
    def initialized(self):
        """
        Return true if the first borg has been created
        """

    @property
    def record_path(self):
        """
        Report the location of the record log file.
        """
        return os.path.join(self.log_dir, "record.log")

    @property
    def log_path(self):
        """
        Report the location of the log file.
        """
        return os.path.join(self.log_dir, "debug.log")

    def open(self):
        """
        Open the log file and record file.
        The files are opened for append, so that existing data is not
        overwritten.

        The files are registered for auto-close on program exit.
        """

        if self._record_file is None:
            self._record_file = open(self.record_path, 'a')
            atexit.register(_close_logs, self._record_file)

        if self._log_file is None:
            self._log_file = open(self.log_path, 'a')
            atexit.register(_close_logs, self._log_file)

    def close(self):
        """
        Close the log and record file.
        """

        if self._record_file is not None:
            self._record_file.close()
        if self._log_file is not None:
            self._log_file.close()

    def record(self, record_type, **kwargs):
        """
        Records an action taken by oit that needs to be communicated to
        outside systems. For example, the update a Dockerfile which needs to be
        reviewed by an owner. Each record is encoded on a single line in the
        record.log.

        Records cannot contain line feeds -- if you need to communicate
        multi-line data, create a record with a path to a file in the working
        directory.

        :param record_type: The type of record to create.
        :param kwargs: key/value pairs

        A record line is designed to be easily parsed and formatted as:
        record_type|key1=value1|key2=value2|...|
        """

        # Multiple image build processes could be calling us with action
        # simultaneously, so synchronize output to the file.
        with self._record_lock:
            record = "%s|" % record_type
            for k, value in kwargs.iteritems():
                assert "\n" not in str(k)
                # Make sure the values have no linefeeds as this would
                # interfere with simple parsing.
                r_string = str(value).replace("\n", " ;;; ").replace("\r", "")
                record += "%s=%s|" % (k, r_string)

            # Add the record to the file
            self._record_file.write("%s\n" % record)
            self._record_file.flush()

    #
    # These methods write at the appropriate log levels to the log file
    # and to stdout if the verbose flag is set.
    #

    def _write(self, message):
        """
        Format and write a log message to the open log file.
        Writes with the shared file object are syncronized.
        """

        timestamp = datetime.datetime.utcnow().isoformat()
        log_line = timestamp + " " + message

        if self.verbose is True:
            click.echo(log_line)

        if self._log_file is None or self._log_file.closed:
            raise IOError("error writing log: file not open: {}".format(self.log_path))

        with self._log_lock:
            self._log_file.write(log_line + "\n")
            self._log_file.flush()

    def debug(self, message):
        """
        Write debug messages to the log if the log level is log.DEBUG.
        Write to stdout as well if verbose flag is set.

        :param message string: A debugging message to print
        """
        if self._log_level >= DEBUG:
            self._write("DEBUG: " + message)

    def info(self, message):
        """
        Write informational messages to the log if the log level
        is log.INFO or lower.
        Write to stdout as well if verbose flag is set.

        :param message string: An informational message to print
        """
        if self._log_level >= INFO:
            self._write("INFO: " + message)

    def warning(self, message):
        """
        Write warning messages to the log if the log level
        is log.WARN or lower.
        Write to stdout as well if verbose flag is set.

        :param message string: A warning message to print
        """
        if self._log_level >= WARNING:
            self._write("WARNING: " + message)

    def error(self, message):
        """
        Write error messages to the log if the log level
        is log.ERROR or lower.
        Write to stdout as well if verbose flag is set.

        :param message string: An error message to print
        """
        if self._log_level >= ERROR:
            self._write("ERROR: " + message)

    def fatal(self, message):
        """
        Write a fatal message to the log and abort execution.
        Write to stdout as well if verbose flag is set.

        :param message string: A status message before exiting the program.
        :raises RuntimeError:
        """
        if self._log_level >= FATAL:
            self._write("ERROR: " + message)

        raise RuntimeError(message)
