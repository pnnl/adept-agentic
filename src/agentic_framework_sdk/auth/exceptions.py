"""
Authentication-specific exceptions.
"""


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass


class TokenExpiredError(AuthenticationError):
    """Raised when a token has expired."""
    pass


class TokenNotFoundError(AuthenticationError):
    """Raised when no stored token is found."""
    pass


class KeycloakConnectionError(AuthenticationError):
    """Raised when cannot connect to Keycloak server."""
    pass