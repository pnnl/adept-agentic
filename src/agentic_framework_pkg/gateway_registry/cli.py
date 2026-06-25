"""
This module provides a command-line interface for administering the Gateway Registry.

It allows administrators to manually register, unregister, and list gateways,
which is useful for debugging and manual configuration.
"""
import argparse
import asyncio
import httpx
import json

def get_admin_token():
    """
    Placeholder function to retrieve an admin token.
    In a real scenario, this would involve a proper OAuth flow.
    """
    # In a real scenario, this would involve a proper OAuth flow.
    # For this example, we'll assume an admin token is available as an env var.
    return "admin-token-placeholder"

async def register(args):
    """Handles the 'register' command."""
    url = f"{args.registry_url}/v1/gateways"
    headers = {"Authorization": f"Bearer {get_admin_token()}"}
    data = {
        "alias": args.alias,
        "public_url": args.public_url,
        "internal_url": args.internal_url,
        "capabilities": args.capabilities.split(',') if args.capabilities else []
    }
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.post(url, json=data, headers=headers)
        response.raise_for_status()
        print(json.dumps(response.json(), indent=2))

async def unregister(args):
    """Handles the 'unregister' command."""
    url = f"{args.registry_url}/v1/gateways/{args.alias}"
    headers = {"Authorization": f"Bearer {get_admin_token()}"}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.delete(url, headers=headers)
        response.raise_for_status()
        print(f"Gateway '{args.alias}' unregistered successfully.")

async def list_gateways(args):
    """Handles the 'list' command."""
    url = f"{args.registry_url}/v1/gateways"
    headers = {"Authorization": f"Bearer {get_admin_token()}"}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        print(json.dumps(response.json(), indent=2))

def main():
    """Parses command-line arguments and executes the corresponding function."""
    parser = argparse.ArgumentParser(description="Admin CLI for the Gateway Registry Service.")
    parser.add_argument("--registry-url", default="http://localhost:8086", help="URL of the registry service.")
    
    subparsers = parser.add_subparsers(required=True)

    # Register command
    parser_register = subparsers.add_parser("register", help="Register a new gateway.")
    parser_register.add_argument("--alias", required=True)
    parser_register.add_argument("--public-url", required=True)
    parser_register.add_argument("--internal-url")
    parser_register.add_argument("--capabilities")
    parser_register.set_defaults(func=register)

    # Unregister command
    parser_unregister = subparsers.add_parser("unregister", help="Unregister a gateway.")
    parser_unregister.add_argument("--alias", required=True)
    parser_unregister.set_defaults(func=unregister)

    # List command
    parser_list = subparsers.add_parser("list", help="List all gateways.")
    parser_list.set_defaults(func=list_gateways)

    args = parser.parse_args()
    asyncio.run(args.func(args))

if __name__ == "__main__":
    main()