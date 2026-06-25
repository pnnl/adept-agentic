"""
This module provides a factory function to get the configured identity provider.

It reads the `IDENTITY_PROVIDER` environment variable and returns the corresponding
`IdentityValidator` and `IdentityAdmin` implementations. This allows the rest of
the application to be agnostic to the specific identity provider being used.
"""
import os
from .base import IdentityValidator, IdentityAdmin

def get_identity_providers() -> (IdentityValidator, IdentityAdmin):
    """
    Factory function that returns the configured identity provider
    validator and admin client.

    Returns:
        A tuple containing an instance of an IdentityValidator and an IdentityAdmin.

    Raises:
        ValueError: If the configured IDENTITY_PROVIDER is unknown.
    """
    provider = os.getenv("IDENTITY_PROVIDER", "keycloak").lower()

    if provider == "keycloak":
        from .keycloak import KeycloakValidator, KeycloakAdmin
        return KeycloakValidator(), KeycloakAdmin()
    elif provider == "entra_id":
        from .entra_id import EntraIdValidator, EntraIdAdmin
        return EntraIdValidator(), EntraIdAdmin()
    else:
        raise ValueError(f"Unknown identity provider: {provider}")