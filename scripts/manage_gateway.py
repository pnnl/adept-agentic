# scripts/manage_gateway.py
import argparse
import asyncio
import os
import sys
import httpx
from keycloak import KeycloakOpenID

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agentic_framework_pkg.logger_config import get_logger

logger = get_logger(__name__)

def get_admin_access_token():
    """Authenticates with Keycloak to get a JWT for the admin user."""
    try:
        keycloak_openid = KeycloakOpenID(
            server_url=os.getenv("KEYCLOAK_URL", "http://localhost:8180"),
            client_id="admin-cli",
            realm_name=os.getenv("KEYCLOAK_REALM", "master")
        )
        token = keycloak_openid.token(
            username=os.getenv("KEYCLOAK_ADMIN"),
            password=os.getenv("KEYCLOAK_ADMIN_PASSWORD")
        )
        return token['access_token']
    except Exception as e:
        logger.error(f"Failed to get admin access token from Keycloak: {e}")
        return None

async def reregister_gateway(gateway_api_url: str):
    """Calls the management endpoint to re-register the gateway."""
    token = get_admin_access_token()
    if not token:
        print("Could not authenticate with Keycloak. Please check admin credentials.", file=sys.stderr)
        return

    headers = {"Authorization": f"Bearer {token}"}
    url = f"{gateway_api_url.rstrip('/')}/v1/management/registry/reregister"
    
    print(f"Attempting to trigger re-registration at: {url}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()
            print("Successfully triggered re-registration.")
            print("Response:", response.json())
    except httpx.HTTPStatusError as e:
        print(f"Error: Received status code {e.response.status_code}", file=sys.stderr)
        print(f"Response body: {e.response.text}", file=sys.stderr)
    except httpx.RequestError as e:
        print(f"An error occurred while requesting {e.request.url!r}.", file=sys.stderr)
        print(f"Error details: {e}", file=sys.stderr)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)

async def main():
    parser = argparse.ArgumentParser(description="Agent Gateway Management CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Reregister command
    parser_reregister = subparsers.add_parser("reregister", help="Trigger the gateway to re-register with the registry.")
    parser_reregister.add_argument(
        "--gateway-url",
        default=os.getenv("AGENT_GATEWAY_API_URL", "http://localhost:8083"),
        help="The base URL of the Agent Gateway API."
    )

    args = parser.parse_args()

    if args.command == "reregister":
        await reregister_gateway(args.gateway_url)

if __name__ == "__main__":
    # This allows the script to find other modules in the package when run directly
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(main())
