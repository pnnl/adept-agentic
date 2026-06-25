"""
This module provides a CLI utility for creating a new user in Keycloak.

It is used by the local development startup script (`start-chapter-resources.sh`)
to provision the default `notebook-user` for the Jupyter tutorials.
"""
import argparse
import asyncio
import os
import sys

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from agentic_framework_pkg.agent_gateway.identity.keycloak import KeycloakAdmin

async def main():
    """Creates a new user in Keycloak with a specified username and password."""
    parser = argparse.ArgumentParser(description="Create a new user in Keycloak.")
    parser.add_argument("--username", required=True, help="The username for the new user.")
    parser.add_argument("--password", required=True, help="The password for the new user.")
    args = parser.parse_args()

    keycloak_admin = KeycloakAdmin()
    try:
        user_id = keycloak_admin.create_user(args.username, args.password)
        print(f"User '{args.username}' created successfully with ID: {user_id}")
    except Exception as e:
        print(f"Error creating user: {e}")

if __name__ == "__main__":
    asyncio.run(main())