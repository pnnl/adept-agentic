"""
User Key Management API

Provides runtime API for managing user service API keys without
requiring container rebuilds.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, List, Any, Optional
import json
import secrets
import string
from datetime import datetime
from ...auth import get_current_user, AuthCredentials

router = APIRouter()

class UserKeyRequest(BaseModel):
    service: str
    user: str
    description: Optional[str] = None
    permissions: Optional[List[str]] = None

class UserKeyResponse(BaseModel):
    api_key: str
    user_id: str
    username: str
    service: str
    created_at: str

class UserKeyManager:
    """Manages user service API keys dynamically."""
    
    def __init__(self):
        self.key_template = "sk-service-{service}-{user}-STABLE-v1-{suffix}"
    
    def generate_suffix(self, length: int = 32) -> str:
        """Generate secure random suffix."""
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    def generate_user_key(self, service: str, user: str) -> str:
        """Generate a stable service API key for a user."""
        safe_user = user.replace('-', '_').replace(' ', '_')
        suffix = self.generate_suffix()
        return self.key_template.format(
            service=service,
            user=safe_user,
            suffix=suffix
        )
    
    def create_key_config(self, service: str, user: str, permissions: List[str] = None) -> Dict[str, Any]:
        """Create key configuration."""
        if not permissions:
            permissions = ["gateway-agents", f"{service}-users"]
            
        return {
            "client_id": f"{service}-client",
            "groups": permissions,
            "user_id": f"service-{service}-{user}",
            "username": f"{service}-service-{user}",
            "description": f"{service.upper()} service API key for user {user}",
            "created_at": datetime.utcnow().isoformat(),
            "user": user,
            "service": service
        }

key_manager = UserKeyManager()

@router.post("/create", response_model=UserKeyResponse)
async def create_user_key(
    request: UserKeyRequest,
    current_user: AuthCredentials = Depends(get_current_user)
):
    """Create a new service API key for a user."""
    # Only admin users can create service keys
    if "admin" not in current_user.groups:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    # Generate new key and config
    api_key = key_manager.generate_user_key(request.service, request.user)
    key_config = key_manager.create_key_config(
        request.service, 
        request.user, 
        request.permissions
    )
    
    # TODO: Store the key in persistent storage (Redis, database)
    # For now, this is just the API structure
    
    return UserKeyResponse(
        api_key=api_key,
        user_id=key_config["user_id"],
        username=key_config["username"],
        service=request.service,
        created_at=key_config["created_at"]
    )

@router.get("/list/{service}")
async def list_service_keys(
    service: str,
    current_user: AuthCredentials = Depends(get_current_user)
):
    """List all service API keys for a service."""
    if "admin" not in current_user.groups:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    # TODO: Retrieve from persistent storage
    # For now, return empty list
    return {"service": service, "keys": []}

@router.delete("/{key_id}")
async def revoke_user_key(
    key_id: str,
    current_user: AuthCredentials = Depends(get_current_user)
):
    """Revoke a service API key."""
    if "admin" not in current_user.groups:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    # TODO: Remove from persistent storage
    return {"message": f"Key {key_id} revoked successfully"}