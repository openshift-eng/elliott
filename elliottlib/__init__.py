import sys
from setuptools_scm import get_version

if sys.version_info < (3, 6):
    sys.exit('Sorry, Python < 3.6 is not supported.')
from .runtime import Runtime


def version():
    return get_version()
