"""
This module provides a CLI utility for registering a new tool with the Agent Gateway.

It reads a tool configuration from a JSON file and sends it to the gateway's
`/v1/tools/register` endpoint, handling the necessary authentication.
"""
import argparse
import asyncio
import json
import os
import sys
import httpx
from keycloak import KeycloakOpenID

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

def get_cli_access_token():
    """
    Fetches an access token for the CLI using its own service client credentials.
    """
    # This would fetch credentials from environment variables or a config file
    client_id = os.getenv("CLI_KEYCLOAK_CLIENT_ID", "cli-client")
    client_secret = os.getenv("CLI_KEYCLOAK_CLIENT_SECRET")
    keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8180/")
    realm_name = os.getenv("KEYCLOAK_REALM", "master")

    keycloak_openid = KeycloakOpenID(server_url=keycloak_url,
                                     client_id=client_id,
                                     realm_name=realm_name,
                                     client_secret_key=client_secret)
    token = keycloak_openid.token(grant_type='client_credentials')
    return token['access_token']

async def main():
    """Registers a new tool with the Agent Gateway."""
    parser = argparse.ArgumentParser(description="Register a new tool with the Agent Gateway.")
    parser.add_argument("--tool-config", required=True, help="Path to the JSON file containing the tool configuration.")
    args = parser.parse_args()

    with open(args.tool_config, 'r') as f:
        tool_config = json.load(f)

    try:
        access_token = get_cli_access_token()
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{os.getenv('AGENT_GATEWAY_API_URL')}/v1/tools/register",
                json=tool_config,
                headers=headers
            )
            response.raise_for_status()
            print(f"Tool '{tool_config['name']}' registered successfully.")

    except Exception as e:
        print(f"Error registering tool: {e}")

if __name__ == "__main__":
    asyncio.run(main())