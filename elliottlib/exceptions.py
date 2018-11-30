"""Common tooling exceptions. Store them in this central place to
avoid circular imports
"""

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
