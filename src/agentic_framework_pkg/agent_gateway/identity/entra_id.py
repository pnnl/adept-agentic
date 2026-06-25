"""
This module contains the concrete implementation for Microsoft Entra ID
(formerly Azure Active Directory) as an identity provider.

It provides concrete implementations of the `IdentityValidator` and `IdentityAdmin`
interfaces defined in `base.py`.

Architectural Note:
-   **Validator:** The `EntraIdValidator` uses the `authlib` library to fetch
    public keys from Entra ID's OIDC discovery endpoint and validate JWTs.
-   **Admin:** The `EntraIdAdmin` uses the `msgraph-sdk` to interact with the
    Microsoft Graph API for managing users and groups. Note that some administrative
    actions, like managing service clients (App Registrations), are not fully
    implemented and are noted as placeholders, as they often require more complex,
    manual setup in the Azure Portal.
"""
import os
import asyncio
from typing import Dict, Any, List
from functools import lru_cache

from authlib.jose import jwt
from authlib.jwk import fetch_jwk_set
from authlib.integrations.httpx_client import AsyncOAuth2Client

from azure.identity.aio import ClientSecretCredential
from msgraph_sdk.graph_service_client import GraphServiceClient
from msgraph_sdk.models import User, PasswordProfile, Group, ReferenceUpdate

from .base import IdentityValidator, IdentityAdmin, JWTValidationError
from ...logger_config import get_logger

logger = get_logger(__name__)

# --- Entra ID Validator ---

@lru_cache(maxsize=1)
def get_jwk_set(jwks_uri):
    """Cached function to fetch JWK set."""
    return fetch_jwk_set(jwks_uri, client=AsyncOAuth2Client())

class EntraIdValidator(IdentityValidator):
    """Validates JWTs using Entra ID's OIDC discovery endpoint."""
    def __init__(self):
        self.issuer_url = os.getenv("OIDC_ISSUER_URL")
        self.audience = os.getenv("OIDC_CLIENT_ID")
        if not self.issuer_url or not self.audience:
            raise ValueError("Entra ID validator is not fully configured. Missing OIDC_ISSUER_URL or OIDC_CLIENT_ID.")
        
        self.metadata_url = f"{self.issuer_url.rstrip('/')}/.well-known/openid-configuration"

    async def validate_token(self, token: str) -> Dict[str, Any]:
        """
        Validates an Entra ID JWT by fetching the JWK set and checking claims.
        """
        if not token:
            raise JWTValidationError("No token provided.")
        
        try:
            async with AsyncOAuth2Client() as client:
                metadata = await client.get(self.metadata_url, timeout=10)
                metadata.raise_for_status()
                jwks_uri = metadata.json().get("jwks_uri")
            
            jwk_set = get_jwk_set(jwks_uri)
            claims = jwt.decode(token, jwk_set)
            
            # Manual validation of standard claims
            claims.validate()

            # Manual audience check
            if 'aud' not in claims or self.audience not in claims['aud']:
                raise JWTValidationError("Invalid audience claim.")

            return claims
        except Exception as e:
            logger.warning(f"Entra ID token validation failed: {e}")
            raise JWTValidationError(f"Token is invalid or expired: {e}") from e

# --- Entra ID Admin Client ---

class EntraIdAdmin(IdentityAdmin):
    """
    A client for managing users and groups via the Microsoft Graph API.
    """
    def __init__(self):
        self.tenant_id = os.getenv("GRAPH_API_TENANT_ID")
        self.client_id = os.getenv("GRAPH_API_CLIENT_ID")
        self.client_secret = os.getenv("GRAPH_API_CLIENT_SECRET")

        if not all([self.tenant_id, self.client_id, self.client_secret]):
            raise ValueError("Entra ID Admin client is not fully configured. Missing GRAPH_API variables.")

        creds = ClientSecretCredential(self.tenant_id, self.client_id, self.client_secret)
        self.graph_client = GraphServiceClient(credentials=creds)

    async def create_user(self, username: str, password: str) -> str:
        """Creates a new user in Entra ID."""
        request_body = User(
            account_enabled=True,
            display_name=username,
            mail_nickname=username.split('@')[0],
            user_principal_name=username,
            password_profile=PasswordProfile(
                force_change_password_next_sign_in=False,
                password=password,
            )
        )
        new_user = await self.graph_client.users.post(request_body)
        return new_user.id

    async def get_users(self) -> List[Dict[str, Any]]:
        """Retrieves a list of all users from Entra ID."""
        users_response = await self.graph_client.users.get()
        return [
            {"id": user.id, "username": user.user_principal_name, "enabled": user.account_enabled}
            for user in users_response.value
        ]

    async def delete_user(self, user_id: str):
        """Deletes a user from Entra ID."""
        await self.graph_client.users.by_user_id(user_id).delete()

    async def create_group(self, group_name: str) -> str:
        """Creates a new security group in Entra ID."""
        request_body = Group(
            display_name=group_name,
            mail_enabled=False,
            mail_nickname=group_name.replace(" ", "").lower(),
            security_enabled=True,
        )
        new_group = await self.graph_client.groups.post(request_body)
        return new_group.id

    async def get_groups(self) -> List[Dict[str, Any]]:
        """Retrieves a list of all groups from Entra ID."""
        groups_response = await self.graph_client.groups.get()
        return [
            {"id": group.id, "name": group.display_name}
            for group in groups_response.value
        ]

    async def delete_group(self, group_id: str):
        """Deletes a group from Entra ID."""
        await self.graph_client.groups.by_group_id(group_id).delete()

    async def add_user_to_group(self, user_id: str, group_id: str):
        """Adds a user to a group in Entra ID."""
        request_body = ReferenceUpdate(
            odata_id=f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"
        )
        await self.graph_client.groups.by_group_id(group_id).members.ref.post(request_body)

    async def remove_user_from_group(self, user_id: str, group_id: str):
        """Removes a user from a group in Entra ID."""
        await self.graph_client.groups.by_group_id(group_id).members.by_directory_object_id(user_id).ref.delete()

    # --- Methods below are not a 1:1 mapping and are placeholders ---
    
    def get_user_groups(self, user_id: str) -> List[Dict[str, Any]]:
        """Placeholder: Retrieves the groups a user is a member of."""
        logger.warning("EntraIdAdmin.get_user_groups is a placeholder and not fully implemented.")
        return []

    def create_or_get_service_client(self, client_name: str) -> Dict[str, Any]:
        """Placeholder: Manages service clients (App Registrations)."""
        logger.warning("EntraIdAdmin.create_or_get_service_client is a placeholder.")
        logger.warning("Service Clients (App Registrations) in Entra ID must be created manually in the Azure Portal.")
        return {"client_id": client_name, "client_secret": "MANUALLY_CONFIGURED_IN_AZURE_PORTAL"}

    def get_clients(self) -> List[Dict[str, Any]]:
        """Placeholder: Retrieves a list of all clients."""
        logger.warning("EntraIdAdmin.get_clients is not fully implemented.")
        return []

    def delete_client(self, client_id: str):
        """Placeholder: Deletes a client."""
        raise NotImplementedError("Deleting App Registrations programmatically is not supported in this implementation.")

    def get_client_groups(self, client_id: str) -> List[Dict[str, Any]]:
        """Placeholder: Retrieves the groups a service client is a member of."""
        raise NotImplementedError("EntraIdAdmin.get_client_groups is not implemented.")

    def add_client_to_group(self, client_id: str, group_id: str):
        """Placeholder: Adds a service client to a group."""
        raise NotImplementedError("Adding App Registrations to groups programmatically is not supported in this implementation.")

    def remove_client_from_group(self, client_id: str, group_id: str):
        """Placeholder: Removes a service client from a group."""
        raise NotImplementedError("Removing App Registrations from groups programmatically is not supported in this implementation.")
