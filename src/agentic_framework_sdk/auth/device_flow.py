"""
OAuth2 Device Flow implementation for Agentic Framework.

Implements the device authorization grant flow (RFC 8628) for CLI authentication
without requiring users to enter passwords or credentials directly.
"""

import asyncio
import time
import secrets
import httpx
from typing import Dict, Any, Optional, Callable
from urllib.parse import urljoin

from .exceptions import AuthenticationError, KeycloakConnectionError
from .token_storage import TokenStorage


class DeviceFlowAuth:
    """
    OAuth2 Device Flow authentication client.
    
    Implements RFC 8628 device authorization grant for CLI authentication.
    Users visit a URL and enter a user code instead of providing credentials directly.
    """
    
    def __init__(
        self,
        keycloak_url: str = "http://keycloak:8180",
        realm: str = "master",
        client_id: str = "agentic-cli",
        external_proxy_url: Optional[str] = None,
        poll_interval: int = 5,
        timeout: int = 300
    ):
        """
        Initialize device flow authentication client.
        
        Args:
            keycloak_url: Internal Keycloak server URL
            realm: Keycloak realm name
            client_id: OAuth2 client ID for CLI
            external_proxy_url: External proxy URL (e.g., https://api.agentic.local/auth)
            poll_interval: Seconds between token polling requests
            timeout: Total timeout for device flow in seconds
        """
        self.keycloak_url = keycloak_url.rstrip('/')
        self.external_proxy_url = external_proxy_url.rstrip('/') if external_proxy_url else None
        self.realm = realm
        self.client_id = client_id
        self.poll_interval = poll_interval
        self.timeout = timeout
        
        # Build endpoint URLs for internal access
        self.device_auth_endpoint = f"{self.keycloak_url}/realms/{realm}/protocol/openid-connect/auth/device"
        self.token_endpoint = f"{self.keycloak_url}/realms/{realm}/protocol/openid-connect/token"
        
        # Build endpoint URLs for external access (through NGINX proxy)
        if self.external_proxy_url:
            self.external_device_auth_endpoint = f"{self.external_proxy_url}/protocol/openid-connect/auth/device"
            self.external_token_endpoint = f"{self.external_proxy_url}/protocol/openid-connect/token"
        
        self.token_storage = TokenStorage()
    
    async def start_device_flow(
        self,
        use_external_proxy: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Start the device authorization flow.
        
        Args:
            use_external_proxy: Whether to use external NGINX proxy endpoint
            progress_callback: Optional callback for progress updates
            
        Returns:
            Device authorization response containing user_code, device_code, etc.
            
        Raises:
            AuthenticationError: If device flow initiation fails
        """
        device_auth_url = (
            self.external_device_auth_endpoint if use_external_proxy 
            else self.device_auth_endpoint
        )
        
        data = {
            "client_id": self.client_id
        }
        
        if progress_callback:
            progress_callback("Initiating device authorization flow...")
        
        try:
            verify_ssl = True if use_external_proxy else False
            
            async with httpx.AsyncClient(verify=verify_ssl, timeout=30.0) as client:
                response = await client.post(device_auth_url, data=data)
                
                if response.status_code == 200:
                    device_auth_response = response.json()
                    
                    # Validate required fields from device authorization response
                    required_fields = ["device_code", "user_code", "verification_uri", "expires_in"]
                    for field in required_fields:
                        if field not in device_auth_response:
                            raise AuthenticationError(f"Device authorization response missing required field: {field}")
                    
                    return device_auth_response
                else:
                    error_info = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                    error_msg = error_info.get("error_description", error_info.get("error", f"HTTP {response.status_code}"))
                    raise AuthenticationError(f"Device authorization failed: {error_msg}")
                    
        except httpx.ConnectError:
            endpoint_type = "external proxy" if use_external_proxy else "internal Keycloak"
            raise KeycloakConnectionError(f"Cannot connect to {endpoint_type} at {device_auth_url}")
        except httpx.TimeoutException:
            raise KeycloakConnectionError(f"Timeout connecting to {device_auth_url}")
        except AuthenticationError:
            raise
        except Exception as e:
            raise AuthenticationError(f"Unexpected error during device authorization: {str(e)}")
    
    async def poll_for_token(
        self,
        device_code: str,
        use_external_proxy: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Poll the token endpoint until user completes authorization.
        
        Args:
            device_code: Device code from device authorization response
            use_external_proxy: Whether to use external NGINX proxy endpoint
            progress_callback: Optional callback for progress updates
            
        Returns:
            Token response containing access_token, refresh_token, etc.
            
        Raises:
            AuthenticationError: If polling fails or times out
        """
        token_url = (
            self.external_token_endpoint if use_external_proxy 
            else self.token_endpoint
        )
        
        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": self.client_id,
            "device_code": device_code
        }
        
        start_time = time.time()
        verify_ssl = True if use_external_proxy else False
        
        while True:
            if time.time() - start_time > self.timeout:
                raise AuthenticationError(f"Device flow timed out after {self.timeout} seconds")
            
            try:
                async with httpx.AsyncClient(verify=verify_ssl, timeout=30.0) as client:
                    response = await client.post(token_url, data=data)
                    
                    if response.status_code == 200:
                        # Success! User has authorized the device
                        token_info = response.json()
                        token_info["stored_at"] = int(time.time())
                        
                        if progress_callback:
                            progress_callback("✅ Authorization successful!")
                        
                        return token_info
                    
                    elif response.status_code == 400:
                        error_response = response.json()
                        error_code = error_response.get("error", "")
                        
                        if error_code == "authorization_pending":
                            # User hasn't authorized yet, continue polling
                            if progress_callback:
                                progress_callback("⏳ Waiting for user authorization...")
                            await asyncio.sleep(self.poll_interval)
                            continue
                        
                        elif error_code == "slow_down":
                            # Slow down polling as requested by server
                            self.poll_interval += 5
                            if progress_callback:
                                progress_callback("🐌 Slowing down polling rate...")
                            await asyncio.sleep(self.poll_interval)
                            continue
                        
                        elif error_code == "expired_token":
                            raise AuthenticationError("Device code has expired. Please start a new device flow.")
                        
                        elif error_code == "access_denied":
                            raise AuthenticationError("User denied the authorization request.")
                        
                        else:
                            error_msg = error_response.get("error_description", error_code)
                            raise AuthenticationError(f"Authorization failed: {error_msg}")
                    
                    else:
                        # Unexpected error
                        error_info = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                        error_msg = error_info.get("error_description", error_info.get("error", f"HTTP {response.status_code}"))
                        raise AuthenticationError(f"Token polling failed: {error_msg}")
                        
            except httpx.ConnectError:
                endpoint_type = "external proxy" if use_external_proxy else "internal Keycloak"
                raise KeycloakConnectionError(f"Cannot connect to {endpoint_type} at {token_url}")
            except httpx.TimeoutException:
                raise KeycloakConnectionError(f"Timeout connecting to {token_url}")
            except AuthenticationError:
                raise
            except Exception as e:
                raise AuthenticationError(f"Unexpected error during token polling: {str(e)}")
    
    async def authenticate_device_flow(
        self,
        use_external_proxy: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
        username: str = "default"
    ) -> Dict[str, Any]:
        """
        Complete device flow authentication.
        
        This is the main method that orchestrates the entire device flow:
        1. Start device authorization
        2. Display user code and verification URL
        3. Poll for token until user completes authorization
        4. Store token and return token info
        
        Args:
            use_external_proxy: Whether to use external NGINX proxy endpoint
            progress_callback: Optional callback for progress updates
            username: Username identifier for token storage
            
        Returns:
            Token information dictionary
            
        Raises:
            AuthenticationError: If device flow fails
        """
        # Step 1: Start device authorization
        device_auth = await self.start_device_flow(use_external_proxy, progress_callback)
        
        # Step 2: Display user instructions
        user_code = device_auth["user_code"]
        verification_uri = device_auth["verification_uri"]
        expires_in = device_auth["expires_in"]
        
        instructions = f"""
🔐 Device Authorization Required

Please visit: {verification_uri}
Enter code: {user_code}

This code expires in {expires_in // 60} minutes.
"""
        
        if progress_callback:
            progress_callback(instructions.strip())
        
        # Step 3: Poll for token
        device_code = device_auth["device_code"]
        token_info = await self.poll_for_token(device_code, use_external_proxy, progress_callback)
        
        # Step 4: Store token
        self.token_storage.store_token(token_info, username)
        
        return token_info
    
    async def test_device_flow_support(self, use_external_proxy: bool = False) -> bool:
        """
        Test if the Keycloak server supports device flow.
        
        Args:
            use_external_proxy: Whether to test external NGINX proxy endpoint
            
        Returns:
            True if device flow is supported
        """
        device_auth_url = (
            self.external_device_auth_endpoint if use_external_proxy 
            else self.device_auth_endpoint
        )
        
        try:
            verify_ssl = True if use_external_proxy else False
            
            async with httpx.AsyncClient(verify=verify_ssl, timeout=10.0) as client:
                # Try a device authorization request with invalid client to test endpoint
                response = await client.post(device_auth_url, data={"client_id": "test"})
                
                # If endpoint exists, we should get a 400 (bad client) or 200 (success)
                # If endpoint doesn't exist, we'll get 404
                return response.status_code in [200, 400, 401]
                
        except Exception:
            return False
    
    def get_stored_token(self, username: str = "default") -> Optional[str]:
        """
        Get stored access token for user.
        
        Args:
            username: Username identifier for token storage
            
        Returns:
            Access token if available, None otherwise
        """
        try:
            if self.token_storage.is_token_valid(username):
                token_info = self.token_storage.get_token(username)
                return token_info.get("access_token")
        except Exception:
            pass
        return None