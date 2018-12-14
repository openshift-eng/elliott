from .runtime import Runtime
from .pushd import Dir
from .errata import Erratum


def version():
    from os.path import abspath, dirname, join
    filename = join(dirname(abspath(__file__)), 'VERSION')
    return open(filename).read().strip()
