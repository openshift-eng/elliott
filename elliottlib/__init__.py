from __future__ import absolute_import, print_function, unicode_literals
from .runtime import Runtime


def version():
    from os.path import abspath, dirname, join
    filename = join(dirname(abspath(__file__)), 'VERSION')
    return open(filename).read().strip()
