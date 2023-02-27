import os
import sys

if sys.version_info < (3, 8):
    sys.exit('Sorry, Python < 3.8 is no longer supported.')

from elliottlib.runtime import Runtime


def version():
    try:
        from ._version import version
    except ImportError:
        from setuptools_scm import get_version
        version = get_version()
    return version
