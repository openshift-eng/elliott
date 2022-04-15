import sys
import pkg_resources

if sys.version_info < (3, 6):
    sys.exit('Sorry, Python < 3.6 is not supported.')
from .runtime import Runtime


def version():
    stream = pkg_resources.resource_stream('elliottlib', 'VERSION')
    return stream.read().decode()
