import os
import sys
from setuptools_scm import get_version

if sys.version_info < (3, 8):
    sys.exit('Sorry, Python < 3.8 is no longer supported.')
from .runtime import Runtime


def version():
    return get_version(
        root=os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..')
        )
    )
