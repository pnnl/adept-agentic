"""
Keycloak authentication client for Agentic Framework SDK.

Handles OAuth2 flows with Keycloak for both external and internal access.
"""

import asyncio
import httpx
import time
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urljoin

from .exceptions import AuthenticationError, KeycloakConnectionError, TokenExpiredError
from .token_storage import TokenStorage


class KeycloakAuth:
    """Authentication client for Keycloak integration."""
    
    def __init__(
        self,
        keycloak_url: str = "http://keycloak:8180",
        realm: str = "agentic-framework", 
        client_id: str = "agentic-cli",
        external_proxy_url: Optional[str] = None
    ):
        """
        Initialize Keycloak authentication client.
        
        Args:
            keycloak_url: Internal Keycloak server URL
            realm: Keycloak realm name
            client_id: OAuth2 client ID for CLI
            external_proxy_url: External proxy URL (e.g., https://api.agentic.local/auth)
        """
        self.keycloak_url = keycloak_url.rstrip('/')
        self.external_proxy_url = external_proxy_url.rstrip('/') if external_proxy_url else None
        self.realm = realm
        self.client_id = client_id
        
        # Build endpoint URLs for internal access
        self.token_endpoint = f"{self.keycloak_url}/realms/{realm}/protocol/openid-connect/token"
        self.userinfo_endpoint = f"{self.keycloak_url}/realms/{realm}/protocol/openid-connect/userinfo"
        
        # Build endpoint URLs for external access (through NGINX proxy)
        if self.external_proxy_url:
            self.external_token_endpoint = f"{self.external_proxy_url}/protocol/openid-connect/token"
            self.external_userinfo_endpoint = f"{self.external_proxy_url}/protocol/openid-connect/userinfo"
        
        self.token_storage = TokenStorage()
    
    async def authenticate_password(
        self, 
        username: str, 
        password: str, 
        use_external_proxy: bool = False
    ) -> Dict[str, Any]:
        """
        Authenticate using username/password (Resource Owner Password Credentials flow).
        
        Args:
            username: User's username
            password: User's password
            use_external_proxy: Whether to use external NGINX proxy endpoint
            
        Returns:
            Token information dictionary
            
        Raises:
            AuthenticationError: If authentication fails
        """
        endpoint = self.external_token_endpoint if use_external_proxy else self.token_endpoint
        
        data = {
            "grant_type": "password",
            "client_id": self.client_id,
            "username": username,
            "password": password
        }
        
        return await self._request_token(endpoint, data, use_external_proxy)
    
    async def refresh_token(
        self, 
        refresh_token: str, 
        use_external_proxy: bool = False
    ) -> Dict[str, Any]:
        """
        Refresh an existing access token.
        
        Args:
            refresh_token: The refresh token
            use_external_proxy: Whether to use external NGINX proxy endpoint
            
        Returns:
            New token information dictionary
        """
        endpoint = self.external_token_endpoint if use_external_proxy else self.token_endpoint
        
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token
        }
        
        return await self._request_token(endpoint, data, use_external_proxy)
    
    async def get_valid_token(
        self, 
        username: str = "default", 
        use_external_proxy: bool = False
    ) -> str:
        """
        Get a valid access token, refreshing if necessary.
        
        Args:
            username: Username identifier for token storage
            use_external_proxy: Whether to use external NGINX proxy endpoint
            
        Returns:
            Valid access token string
            
        Raises:
            AuthenticationError: If no token available and can't refresh
        """
        try:
            # Try to get stored token
            token_info = self.token_storage.get_token(username)
            
            # Check if token is still valid
            if self._is_token_expired(token_info):
                # Try to refresh token
                if "refresh_token" in token_info:
                    try:
                        new_token_info = await self.refresh_token(
                            token_info["refresh_token"],
                            use_external_proxy=use_external_proxy
                        )
                        # Store the refreshed token
                        self.token_storage.store_token(new_token_info, username)
                        return new_token_info["access_token"]
                    except Exception:
                        # Refresh failed, token is invalid
                        self.token_storage.delete_token(username)
                        raise AuthenticationError("Token expired and refresh failed")
                else:
                    # No refresh token available
                    self.token_storage.delete_token(username)
                    raise AuthenticationError("Token expired and no refresh token available")
            
            return token_info["access_token"]
            
        except Exception:
            raise AuthenticationError("No valid token available. Please authenticate first.")
    
    def has_valid_token(self, username: str = "default") -> bool:
        """
        Check if a valid token is stored for the user.
        
        Args:
            username: Username identifier for token storage
            
        Returns:
            True if valid token is available
        """
        return self.token_storage.is_token_valid(username)
    
    def clear_tokens(self, username: str = "default") -> None:
        """
        Clear stored tokens for the user.
        
        Args:
            username: Username identifier for token storage
        """
        self.token_storage.delete_token(username)
    
    async def test_connection(self, use_external_proxy: bool = False) -> bool:
        """
        Test connection to Keycloak server.
        
        Args:
            use_external_proxy: Whether to test external NGINX proxy endpoint
            
        Returns:
            True if connection successful
        """
        try:
            endpoint = self.external_token_endpoint if use_external_proxy else self.token_endpoint
            
            # Try to access the token endpoint (should return method not allowed or similar)
            # Use same SSL verification as token requests
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                response = await client.get(endpoint)
                # Any response (even error) means we can connect
                return response.status_code in [200, 400, 404, 405, 500]
                
        except Exception:
            return False
    
    def _is_token_expired(self, token_info: Dict[str, Any]) -> bool:
        """Check if a token is expired."""
        if "expires_in" not in token_info or "stored_at" not in token_info:
            return False  # Can't determine, assume valid
        
        stored_at = token_info["stored_at"]
        expires_in = token_info["expires_in"]
        current_time = int(time.time())
        
        # Add 60 second buffer
        return current_time >= (stored_at + expires_in - 60)
    
    async def _request_token(
        self, 
        endpoint: str, 
        data: Dict[str, str], 
        use_external_proxy: bool
    ) -> Dict[str, Any]:
        """
        Make a token request to Keycloak.
        
        Args:
            endpoint: Token endpoint URL
            data: Form data for token request
            use_external_proxy: Whether using external proxy (affects error handling)
            
        Returns:
            Token response dictionary
            
        Raises:
            AuthenticationError: If authentication fails
        """
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        try:
            # Use different verification settings based on endpoint type
            # For development with self-signed certs, disable SSL verification
            verify_ssl = False
            
            async with httpx.AsyncClient(verify=verify_ssl, timeout=30.0) as client:
                response = await client.post(endpoint, data=data, headers=headers)
                
                if response.status_code == 200:
                    token_info = response.json()
                    token_info["stored_at"] = int(time.time())
                    return token_info
                else:
                    error_info = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                    error_msg = error_info.get("error_description", error_info.get("error", f"HTTP {response.status_code}"))
                    raise AuthenticationError(f"Authentication failed: {error_msg}")
                    
        except httpx.ConnectError:
            endpoint_type = "external proxy" if use_external_proxy else "internal Keycloak"
            raise KeycloakConnectionError(f"Cannot connect to {endpoint_type} at {endpoint}")
        except httpx.TimeoutException:
            raise KeycloakConnectionError(f"Timeout connecting to {endpoint}")
        except AuthenticationError:
            raise
        except Exception as e:
            raise AuthenticationError(f"Unexpected error during authentication: {str(e)}")