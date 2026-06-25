"""
Configuration Service - Dynamic API Key Management

Provides a central configuration endpoint that OpenWebUI can query
for current service API keys without requiring container restarts.
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any
import json
import os

router = APIRouter()

def get_current_service_keys() -> Dict[str, Any]:
    """Get current service API keys from environment or secrets."""
    service_keys_config = os.getenv("SERVICE_API_KEYS_CONFIG")
    
    if service_keys_config:
        try:
            return json.loads(service_keys_config)
        except json.JSONDecodeError:
            pass
    
    # Fallback to individual environment variables
    openwebui_key = os.getenv("OPENWEBUI_SERVICE_API_KEY")
    n8n_key = os.getenv("N8N_SERVICE_API_KEY")
    
    if openwebui_key:
        return {
            openwebui_key: {
                "client_id": "openwebui-client",
                "groups": ["gateway-agents"],
                "user_id": "service-openwebui", 
                "username": "openwebui-service"
            }
        }
    
    raise HTTPException(status_code=500, detail="No service API keys configured")

@router.get("/config/service-keys")
async def get_service_keys_config():
    """Get current service API keys configuration."""
    try:
        keys_config = get_current_service_keys()
        
        # Return only the keys (not the full config) for security
        return {
            "openwebui_api_key": next(
                (key for key, config in keys_config.items() 
                 if config.get("client_id") == "openwebui-client"), 
                None
            ),
            "available_services": list(config.get("client_id") for config in keys_config.values())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Configuration error: {str(e)}")

@router.get("/config/gateway-endpoint") 
async def get_gateway_endpoint():
    """Get current agent gateway endpoint."""
    gateway_url = os.getenv("AGENT_GATEWAY_URL", "http://agent_gateway:8081/v1")
    return {"agent_gateway_url": gateway_url}