"""
Setup command module - Environment configuration
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
from fabric import Connection
from rich.console import Console

console = Console()


def setup_environment(conn: Connection, workspace_path: str, config: Dict[str, Any]) -> bool:
    """
    Set up ADEPT environment configuration

    Args:
        conn: Fabric SSH connection
        workspace_path: Path to workspace directory
        config: Configuration dictionary

    Returns:
        bool: True if successful
    """
    try:
        # Copy .env.example to .env if it exists
        env_example = f"{workspace_path}/.env.example"
        env_file = f"{workspace_path}/.env"

        result = conn.run(f"test -f {env_example}", warn=True)
        if result.ok:
            conn.run(f"cp {env_example} {env_file}")
            console.print(f"  ✓ Created .env from template")

            # Update specific environment variables if provided in config
            if 'environment' in config:
                for key, value in config['environment'].items():
                    # Use sed to update or add environment variable
                    conn.run(
                        f"grep -q '^{key}=' {env_file} && "
                        f"sed -i 's/^{key}=.*/{key}={value}/' {env_file} || "
                        f"echo '{key}={value}' >> {env_file}",
                        hide=True
                    )
                console.print(f"  ✓ Updated environment variables")

        # Create Keycloak credentials directory if needed
        keycloak_dir = f"{workspace_path}/.env-keycloak-credentials-dir"
        conn.run(f"mkdir -p {keycloak_dir}")

        return True

    except Exception as e:
        console.print(f"  ✗ Environment setup failed: {e}")
        return False


def setup_docker_credentials(conn: Connection, config: Dict[str, Any]) -> bool:
    """
    Set up Docker registry credentials if needed

    Args:
        conn: Fabric SSH connection
        config: Configuration dictionary

    Returns:
        bool: True if successful
    """
    try:
        if 'docker' in config and 'registry' in config['docker']:
            registry = config['docker']['registry']
            username = config['docker'].get('username')
            password = config['docker'].get('password')

            if username and password:
                result = conn.run(
                    f"echo '{password}' | docker login {registry} -u {username} --password-stdin",
                    hide=True,
                    warn=True
                )

                if result.ok:
                    console.print(f"  ✓ Docker registry login successful")
                    return True
                else:
                    console.print(f"  ⚠ Docker registry login failed")
                    return False

        return True

    except Exception as e:
        console.print(f"  ✗ Docker credential setup failed: {e}")
        return False