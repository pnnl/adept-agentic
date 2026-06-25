"""
This module defines the abstract base classes for identity management.

It establishes a provider-agnostic interface for:
1.  **IdentityValidator:** Validating security tokens (e.g., JWTs).
2.  **IdentityAdmin:** Managing identity resources (users, groups, clients).

This abstraction allows the application to be decoupled from a specific
identity provider like Keycloak. To support a different provider (e.g.,
Microsoft Entra ID), one would simply need to create new concrete classes
that implement these interfaces.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List

# Re-export canonical AuthCredentials and JWTValidationError from core.auth (Phase 0c consolidation)
from ...core.auth import AuthCredentials, JWTValidationError

class IdentityValidator(ABC):
    """
    Abstract interface for validating identity tokens.
    """
    @abstractmethod
    async def validate_token(self, token: str) -> Dict[str, Any]:
        """Validates a token and returns its claims."""
        pass

class IdentityAdmin(ABC):
    """
    Abstract interface for managing users, groups, and clients
    in an identity provider.
    """
    @abstractmethod
    def create_user(self, username: str, password: str) -> str:
        """Creates a new user."""
        pass

    @abstractmethod
    def get_users(self) -> List[Dict[str, Any]]:
        """Retrieves a list of all users."""
        pass

    @abstractmethod
    def delete_user(self, user_id: str):
        """Deletes a user."""
        pass

    @abstractmethod
    def create_group(self, group_name: str) -> str:
        """Creates a new group."""
        pass

    @abstractmethod
    def get_groups(self) -> List[Dict[str, Any]]:
        """Retrieves a list of all groups."""
        pass
    
    @abstractmethod
    def delete_group(self, group_id: str):
        """Deletes a group."""
        pass

    @abstractmethod
    def add_user_to_group(self, user_id: str, group_id: str):
        """Adds a user to a group."""
        pass

    @abstractmethod
    def remove_user_from_group(self, user_id: str, group_id: str):
        """Removes a user from a group."""
        pass

    @abstractmethod
    def get_user_groups(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieves the groups a user is a member of."""
        pass

    @abstractmethod
    def create_or_get_service_client(self, client_name: str) -> Dict[str, Any]:
        """Creates or retrieves a service client and its secret."""
        pass
    
    @abstractmethod
    def get_clients(self) -> List[Dict[str, Any]]:
        """Retrieves a list of all clients."""
        pass

    @abstractmethod
    def delete_client(self, client_id: str):
        """Deletes a client."""
        pass

    @abstractmethod
    def get_client_groups(self, client_id: str) -> List[Dict[str, Any]]:
        """Retrieves the groups a service client is a member of."""
        pass

    @abstractmethod
    def add_client_to_group(self, client_id: str, group_id: str):
        """Adds a service client to a group."""
        pass

    @abstractmethod
    def remove_client_from_group(self, client_id: str, group_id: str):
        """Removes a service client from a group."""
        pass