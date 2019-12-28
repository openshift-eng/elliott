"""Common tooling exceptions. Store them in this central place to
avoid circular imports
"""
from __future__ import absolute_import, print_function, unicode_literals


class ElliottFatalError(Exception):
    """A broad exception for errors during Brew CRUD operations"""
    pass


class BrewBuildException(Exception):
    """A broad exception for errors during Brew CRUD operations"""
    pass


class ErrataToolUnauthenticatedException(Exception):
    """You were not authenticated when accessing the Errata Tool API"""
    pass


class ErrataToolUnauthorizedException(Exception):
    """You were not authorized to make a request to the Errata Tool API"""
    pass


class ErrataToolError(Exception):
    """General problem interacting with the Errata Tool"""
    pass


class BugzillaFatalError(Exception):
    """A broad exception for errors during Bugzilla API call"""
    pass
