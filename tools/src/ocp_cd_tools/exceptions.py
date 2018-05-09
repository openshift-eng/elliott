"""Common tooling exceptions. Store them in this central place to
avoid circular imports
"""


class BrewBuildException(Exception):
    """A broad exception for errors during Brew CRUD operations"""
    pass


class ErrataToolUnauthorizedException(Exception):
    """You were not authorized to hit the Errata Tool API"""
    pass


class ErrataToolError(Exception):
    """General problem interacting with the Errata Tool"""
    pass
