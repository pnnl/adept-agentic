"""
This module contains the concrete implementation for Keycloak as an identity provider.

It provides concrete implementations of the `IdentityValidator` and `IdentityAdmin`
interfaces defined in `base.py`, using the `python-keycloak` library to interact
with a Keycloak instance.
"""
import os
import time
from typing import Dict, Any, List
from keycloak import KeycloakAdmin as KeycloakAdminClient, KeycloakOpenID, KeycloakOpenIDConnection
from keycloak.exceptions import KeycloakError, KeycloakGetError
from jose.exceptions import JOSEError

from ...logger_config import get_logger
from ...core.secrets_manager import get_secret
from .base import IdentityValidator, IdentityAdmin, JWTValidationError

logger = get_logger(__name__)

class KeycloakValidator(IdentityValidator):
    """Validates JWTs using Keycloak's OIDC endpoint."""
    def __init__(self):
        """Initializes the Keycloak OpenID Connect client."""
        self.keycloak_openid = KeycloakOpenID(
            server_url=os.getenv("KEYCLOAK_URL", "http://localhost:8180"),
            realm_name=os.getenv("KEYCLOAK_REALM", "master"),
            client_id=os.getenv("KEYCLOAK_CLIENT_ID"),
        )

    async def validate_token(self, token: str) -> Dict[str, Any]:
        """
        Validates a JWT by decoding it using the realm's public key.
        """
        if not token:
            raise JWTValidationError("No token provided.")
        try:
            return self.keycloak_openid.decode_token(
                token,
                key=self.keycloak_openid.public_key(),
                options={"verify_signature": True, "verify_aud": True, "exp": True}
            )
        except JOSEError as e:
            logger.warning(f"JWT validation failed: {e}")
            raise JWTValidationError(f"Token validation error: {e}") from e
        except Exception as e:
            logger.error(f"An unexpected error occurred during JWT validation: {e}", exc_info=True)
            raise JWTValidationError("An unexpected error occurred during token validation.") from e

class KeycloakAdmin(IdentityAdmin):
    """
    A client for managing users, groups, and clients via the Keycloak Admin API.
    """

    def __init__(self):
        """Initializes the Keycloak Admin client.

        Note: admin-cli is a confidential client, so client_secret_key is required.
        Reads from credentials directory via get_secret() helper.
        """
        connection = KeycloakOpenIDConnection(
            server_url=os.getenv("KEYCLOAK_URL", "http://localhost:8180/"),
            username=os.getenv("KEYCLOAK_ADMIN", "admin"),
            password=os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin"),
            realm_name=os.getenv("KEYCLOAK_REALM", "master"),
            client_id="admin-cli",
            client_secret_key=get_secret("KC_ADMIN_CLI_SECRET"),
            verify=True,
        )
        self.keycloak_admin = KeycloakAdminClient(connection=connection)

    def create_user(self, username: str, password: str) -> str:
        """Creates a new user in Keycloak."""
        try:
            user_id = self.keycloak_admin.create_user(
                {"email": f"{username}@example.com", "username": username, "enabled": True}
            )
            self.keycloak_admin.set_user_password(user_id, password, temporary=False)
            logger.info(f"Successfully created user '{username}' with ID: {user_id}")
            return user_id
        except KeycloakError as e:
            logger.error(f"Failed to create user '{username}': {e}")
            raise

    def get_users(self) -> List[Dict[str, Any]]:
        """Retrieves a list of all users."""
        return self.keycloak_admin.get_users()

    def delete_user(self, user_id: str):
        """Deletes a user by their ID."""
        self.keycloak_admin.delete_user(user_id)

    def create_group(self, group_name: str) -> str:
        """Creates a new group."""
        try:
            group_id = self.keycloak_admin.create_group({"name": group_name})
            logger.info(f"Successfully created group '{group_name}' with ID: {group_id}")
            return group_id
        except KeycloakError as e:
            logger.error(f"Failed to create group '{group_name}': {e}")
            raise

    def get_groups(self) -> List[Dict[str, Any]]:
        """Retrieves a list of all groups."""
        return self.keycloak_admin.get_groups()

    def delete_group(self, group_id: str):
        """Deletes a group by its ID."""
        self.keycloak_admin.delete_group(group_id)

    def add_user_to_group(self, user_id: str, group_id: str):
        """Adds a user to a group."""
        try:
            self.keycloak_admin.group_user_add(user_id, group_id)
            logger.info(f"Successfully added user '{user_id}' to group '{group_id}'")
        except KeycloakError as e:
            logger.error(f"Failed to add user '{user_id}' to group '{group_id}': {e}")
            raise

    def remove_user_from_group(self, user_id: str, group_id: str):
        """Removes a user from a group."""
        try:
            self.keycloak_admin.group_user_remove(user_id, group_id)
            logger.info(f"Successfully removed user '{user_id}' from group '{group_id}'")
        except KeycloakError as e:
            logger.error(f"Failed to remove user '{user_id}' from group '{group_id}': {e}")
            raise
            
    def get_user_groups(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieves the groups a user is a member of."""
        return self.keycloak_admin.get_user_groups(user_id)

    def get_client_groups(self, client_id: str) -> List[Dict[str, Any]]:
        """Retrieves the groups a service client is a member of."""
        try:
            service_account_user = self.keycloak_admin.get_client_service_account_user(client_id)
            if not service_account_user:
                return []
            return self.keycloak_admin.get_user_groups(service_account_user['id'])
        except KeycloakError as e:
            logger.error(f"Failed to get groups for client '{client_id}': {e}")
            return []

    def add_client_to_group(self, client_id: str, group_id: str):
        """Adds a service client to a group."""
        try:
            service_account_user = self.keycloak_admin.get_client_service_account_user(client_id)
            if not service_account_user:
                raise ValueError(f"Service account user not found for client ID {client_id}")
            self.keycloak_admin.group_user_add(service_account_user['id'], group_id)
            logger.info(f"Successfully added client '{client_id}' to group '{group_id}'")
        except KeycloakError as e:
            logger.error(f"Failed to add client '{client_id}' to group '{group_id}': {e}")
            raise

    def remove_client_from_group(self, client_id: str, group_id: str):
        """Removes a service client from a group."""
        try:
            service_account_user = self.keycloak_admin.get_client_service_account_user(client_id)
            if not service_account_user:
                raise ValueError(f"Service account user not found for client ID {client_id}")
            self.keycloak_admin.group_user_remove(service_account_user['id'], group_id)
            logger.info(f"Successfully removed client '{client_id}' from group '{group_id}'")
        except KeycloakError as e:
            logger.error(f"Failed to remove client '{client_id}' from group '{group_id}': {e}")
            raise

    def create_service_client(self, client_name: str) -> Dict[str, Any]:
        """Creates a new service account client in Keycloak."""
        try:
            payload = {
                "clientId": client_name, "enabled": True, "serviceAccountsEnabled": True,
                "publicClient": False, "standardFlowEnabled": False, "directAccessGrantsEnabled": False,
                "implicitFlowEnabled": False, "protocol": "openid-connect", "clientAuthenticatorType": "client-secret"
            }
            self.keycloak_admin.create_client(payload)
            internal_client_id = self.keycloak_admin.get_client_id(client_name)
            # Regenerate the secret to ensure it's available immediately
            new_secret = self.keycloak_admin.generate_client_secrets(internal_client_id)
            logger.info(f"Successfully created and set secret for service client '{client_name}' with internal ID: {internal_client_id}")
            return {"client_id": client_name, "client_secret": new_secret['value']}
        except KeycloakError as e:
            logger.error(f"Failed to create service client '{client_name}': {e.response_body}")
            raise

    import time

    def create_or_get_service_client(self, client_name: str) -> Dict[str, Any]:
        """
        Robustly gets or creates a service client and its secret.

        This function is idempotent and handles race conditions where a client
        may exist but its secret is not immediately available.
        """
        try:
            # Attempt to get the client's internal UUID.
            internal_client_id = self.keycloak_admin.get_client_id(client_name)
            
            # Check if client was actually found
            if internal_client_id is None:
                logger.info(f"Service client '{client_name}' not found (get_client_id returned None). Creating it now.")
                
                # Create the client
                self.create_service_client(client_name)
                
                # IMPORTANT: Wait briefly for Keycloak to process the creation before fetching the secret.
                time.sleep(1) 
                
                # Now, fetch the newly created client's secret
                internal_client_id = self.keycloak_admin.get_client_id(client_name)
                new_secret = self.keycloak_admin.generate_client_secrets(internal_client_id)
                logger.info(f"Successfully created and retrieved secret for new client '{client_name}'.")
                return {"client_id": client_name, "client_secret": new_secret['value']}
            
            logger.info(f"Service client '{client_name}' already exists with internal ID: {internal_client_id}.")
            
            # If client exists, get its secret, regenerating if necessary.
            try:
                client_secret_data = self.keycloak_admin.get_client_secrets(internal_client_id)
                if not client_secret_data:
                    raise KeycloakError("Client secret data is empty.")
                client_secret = client_secret_data[0]["value"]
                logger.info(f"Successfully fetched existing secret for client '{client_name}'.")
                return {"client_id": client_name, "client_secret": client_secret}
            except (KeycloakError, KeyError, IndexError) as e:
                logger.warning(f"Could not retrieve existing secret for '{client_name}' (Reason: {e}). Regenerating secret.")
                new_secret = self.keycloak_admin.generate_client_secrets(internal_client_id)
                return {"client_id": client_name, "client_secret": new_secret['value']}

        except KeycloakGetError as e:
            if e.response_code == 404:
                # Client does not exist, create it.
                logger.info(f"Service client '{client_name}' not found. Creating it now.")
                
                # Create the client
                self.create_service_client(client_name)
                
                # IMPORTANT: Wait briefly for Keycloak to process the creation before fetching the secret.
                time.sleep(1) 
                
                # Now, fetch the newly created client's secret
                internal_client_id = self.keycloak_admin.get_client_id(client_name)
                new_secret = self.keycloak_admin.generate_client_secrets(internal_client_id)
                logger.info(f"Successfully created and retrieved secret for new client '{client_name}'.")
                return {"client_id": client_name, "client_secret": new_secret['value']}
            else:
                logger.error(f"An unexpected Keycloak error occurred while checking for client '{client_name}': {e.response_body}")
                raise
        except Exception as e:
            logger.error(f"A broad exception occurred in create_or_get_service_client for '{client_name}': {e}")
            raise


    def get_clients(self) -> List[Dict[str, Any]]:
        """Retrieves a list of all clients."""
        return self.keycloak_admin.get_clients()

    def delete_client(self, client_id: str):
        """Deletes a client by its internal ID."""
        self.keycloak_admin.delete_client(client_id)