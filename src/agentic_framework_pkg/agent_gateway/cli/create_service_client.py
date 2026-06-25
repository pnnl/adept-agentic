"""
This module provides a CLI utility for creating service clients in Keycloak.

It is used during the local development startup process (`start-chapter-resources.sh`)
to programmatically provision the necessary OAuth 2.0 clients that services
like the Management UI and other gateways need to authenticate themselves.
"""
import argparse
import asyncio
import os
import sys
import time

from keycloak.exceptions import KeycloakGetError, KeycloakPostError
from agentic_framework_pkg.agent_gateway.identity.keycloak import KeycloakAdmin

async def main():
    """
    Creates a new service client in Keycloak if it doesn't exist,
    and prints its client_id and client_secret.

    This script includes a retry mechanism to handle cases where Keycloak is
    still starting up when the script is first run.
    """
    parser = argparse.ArgumentParser(description="Create or retrieve a service client in Keycloak.")
    parser.add_argument("--client-name", required=True, help="The name for the new service client.")
    args = parser.parse_args()

    max_retries = 5
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        try:
            keycloak_admin = KeycloakAdmin()
            client_info = keycloak_admin.create_or_get_service_client(args.client_name)
            # On success, print the secret to stdout and exit
            print(client_info['client_secret'])
            return
        except KeycloakPostError:
            # This specific error indicates Keycloak is up but may not be fully ready.
            print(f"Attempt {attempt + 1}/{max_retries}: Keycloak seems to be starting up. Retrying in {retry_delay}s...", file=sys.stderr)
            await asyncio.sleep(retry_delay)
        except Exception as e:
            # For any other exception, fail immediately.
            print(f"An unexpected error occurred in create_service_client: {repr(e)}", file=sys.stderr)
            sys.exit(1)

    print(f"Failed to connect to Keycloak and create client '{args.client_name}' after {max_retries} attempts.", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ImportError as e:
        print(f"FATAL IMPORT ERROR: {e}. Check PYTHONPATH.", file=sys.stderr)
        sys.exit(1)