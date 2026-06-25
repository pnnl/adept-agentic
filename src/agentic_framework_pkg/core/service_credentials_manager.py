"""
Service Credentials Manager

Provides credential validation, refresh, and health monitoring for service clients
(OpenWebUI, n8n, etc.) to prevent credential drift and authentication failures.

This addresses the critical issue where service clients lose authentication after
Keycloak restarts or token expiration, requiring manual intervention.
"""
import os
import time
import json
import asyncio
from typing import Dict, Optional, List
from dataclasses import dataclass
from keycloak import KeycloakOpenID, KeycloakAdmin, KeycloakAuthenticationError
import httpx

from ..logger_config import get_logger
from .secrets_manager import get_secret, save_secrets

logger = get_logger(__name__)

@dataclass
class ServiceCredential:
    """Represents a service client's authentication credentials"""
    client_id: str
    client_secret: str
    service_name: str
    keycloak_url: str = "http://keycloak:8180/"
    realm: str = "master"
    last_validated: Optional[float] = None
    last_token: Optional[str] = None
    token_expires_at: Optional[float] = None

class ServiceCredentialsManager:
    """
    Manages service client credentials with automatic validation and refresh.
    
    Prevents credential drift by:
    1. Validating credentials at service startup
    2. Refreshing expired tokens automatically  
    3. Re-registering clients if they're missing from Keycloak
    4. Providing health checks for monitoring
    """
    
    def __init__(self):
        self.credentials: Dict[str, ServiceCredential] = {}
        self.keycloak_admin: Optional[KeycloakAdmin] = None
        self._validation_interval = 300  # 5 minutes
        self._refresh_threshold = 120   # 2 minutes before expiry
        
    async def initialize(self) -> bool:
        """Initialize the credentials manager and validate existing credentials"""
        try:
            # Load credentials from environment/files
            await self._load_service_credentials()
            
            # Validate all credentials
            validation_results = await self._validate_all_credentials()
            
            # Start background validation task
            asyncio.create_task(self._background_validation_loop())
            
            success_count = sum(1 for result in validation_results.values() if result)
            total_count = len(validation_results)
            
            logger.info(f"ServiceCredentialsManager initialized: {success_count}/{total_count} credentials valid")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"Failed to initialize ServiceCredentialsManager: {e}", exc_info=True)
            return False
    
    async def _load_service_credentials(self):
        """Load service credentials from environment and files"""
        # Standard service clients that need credential management
        service_configs = [
            {
                "service_name": "openwebui",
                "client_id": "openwebui-client", 
                "secret_env": "OPENWEBUI_CLIENT_SECRET"
            },
            {
                "service_name": "n8n",
                "client_id": "n8n-client",
                "secret_env": "N8N_CLIENT_SECRET"  
            },
            {
                "service_name": "gateway-registry",
                "client_id": "gateway-registry-client",
                "secret_env": "REGISTRY_CLIENT_SECRET"
            }
        ]
        
        for config in service_configs:
            try:
                client_secret = get_secret(config["secret_env"])
                if client_secret:
                    credential = ServiceCredential(
                        client_id=config["client_id"],
                        client_secret=client_secret,
                        service_name=config["service_name"]
                    )
                    self.credentials[config["service_name"]] = credential
                    logger.info(f"Loaded credentials for {config['service_name']}")
                else:
                    logger.warning(f"No secret found for {config['service_name']} ({config['secret_env']})")
            except Exception as e:
                logger.warning(f"Failed to load credentials for {config['service_name']}: {e}")
    
    async def _validate_all_credentials(self) -> Dict[str, bool]:
        """Validate all loaded credentials"""
        results = {}
        
        for service_name, credential in self.credentials.items():
            try:
                is_valid = await self._validate_credential(credential)
                results[service_name] = is_valid
                
                if is_valid:
                    credential.last_validated = time.time()
                    logger.info(f"✅ {service_name} credentials validated successfully")
                else:
                    logger.warning(f"⚠️  {service_name} credentials validation failed (service may be unavailable)")
                    
            except Exception as e:
                logger.error(f"Exception validating {service_name} credentials: {e}")
                results[service_name] = False
                
        return results
    
    async def _validate_credential(self, credential: ServiceCredential) -> bool:
        """Validate a single credential by attempting token exchange"""
        try:
            keycloak_openid = KeycloakOpenID(
                server_url=credential.keycloak_url,
                client_id=credential.client_id,
                realm_name=credential.realm,
                client_secret_key=credential.client_secret
            )
            
            # Attempt client credentials flow
            token = keycloak_openid.token(grant_type='client_credentials')
            
            if token and 'access_token' in token:
                # Cache the token with expiration
                credential.last_token = token['access_token'] 
                credential.token_expires_at = time.time() + token.get('expires_in', 300)
                return True
                
        except KeycloakAuthenticationError as e:
            logger.warning(f"Authentication failed for {credential.service_name}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error validating {credential.service_name}: {e}")
            
        return False
    
    async def get_valid_token(self, service_name: str) -> Optional[str]:
        """Get a valid access token for a service, refreshing if necessary"""
        if service_name not in self.credentials:
            logger.error(f"No credentials found for service: {service_name}")
            return None
            
        credential = self.credentials[service_name]
        current_time = time.time()
        
        # Check if token needs refresh
        if (credential.token_expires_at is None or 
            credential.token_expires_at - current_time < self._refresh_threshold):
            logger.info(f"Refreshing token for {service_name}")
            
            if await self._validate_credential(credential):
                logger.info(f"Token refreshed successfully for {service_name}")
            else:
                logger.warning(f"Failed to refresh token for {service_name}")
                return None
                
        return credential.last_token
    
    async def ensure_client_exists(self, service_name: str) -> bool:
        """Ensure the service client exists in Keycloak, creating if necessary"""
        if service_name not in self.credentials:
            return False
            
        credential = self.credentials[service_name]
        
        try:
            if not self.keycloak_admin:
                self.keycloak_admin = await self._get_admin_client()
                
            # Check if client exists
            clients = self.keycloak_admin.get_clients()
            existing_client = next(
                (c for c in clients if c['clientId'] == credential.client_id), 
                None
            )
            
            if not existing_client:
                logger.warning(f"Client {credential.client_id} not found in Keycloak, creating...")
                
                # Create the client
                client_config = {
                    "clientId": credential.client_id,
                    "serviceAccountsEnabled": True,
                    "directAccessGrantsEnabled": False,
                    "publicClient": False,
                    "standardFlowEnabled": False,
                    "secret": credential.client_secret
                }
                
                self.keycloak_admin.create_client(client_config)
                logger.info(f"✅ Created missing client: {credential.client_id}")
                
            return True

        except Exception as e:
            logger.warning(f"Failed to ensure client exists for {service_name}: {e}")
            return False
    
    async def _get_admin_client(self):
        """Get Keycloak admin client for management operations"""
        from ..agent_gateway.identity import get_identity_providers
        _, admin_client = get_identity_providers()
        return admin_client
    
    async def health_check(self) -> Dict[str, Dict]:
        """Perform health check on all service credentials"""
        health_status = {}
        
        for service_name, credential in self.credentials.items():
            current_time = time.time()
            
            # Calculate time since last validation
            last_validated_ago = (
                current_time - credential.last_validated 
                if credential.last_validated else float('inf')
            )
            
            # Calculate token expiry status
            token_expires_in = (
                credential.token_expires_at - current_time
                if credential.token_expires_at else None
            )
            
            status = {
                "service_name": service_name,
                "client_id": credential.client_id,
                "last_validated_ago_seconds": last_validated_ago,
                "token_expires_in_seconds": token_expires_in,
                "has_valid_token": credential.last_token is not None,
                "health_status": "healthy" if last_validated_ago < 600 else "stale"  # 10 minutes
            }
            
            # Override status if token is expired
            if token_expires_in is not None and token_expires_in <= 0:
                status["health_status"] = "expired"
                
            health_status[service_name] = status
            
        return health_status
    
    async def _background_validation_loop(self):
        """Background task to periodically validate credentials"""
        while True:
            try:
                await asyncio.sleep(self._validation_interval)
                logger.debug("Running background credential validation...")
                
                await self._validate_all_credentials()
                
            except asyncio.CancelledError:
                logger.info("Background validation loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in background validation loop: {e}")

# Global instance
credentials_manager = ServiceCredentialsManager()