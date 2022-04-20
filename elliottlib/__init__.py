import sys
import pkg_resources
import subprocess

if sys.version_info < (3, 6):
    sys.exit('Sorry, Python < 3.6 is not supported.')
from .runtime import Runtime


def version():
    try:
        stream = pkg_resources.resource_stream('elliottlib', 'VERSION')
        return stream.read().decode()
    except FileNotFoundError:
        proc = subprocess.run(['git', 'describe', '--tags'], stdout=subprocess.PIPE)
        return proc.stdout.decode().strip()
