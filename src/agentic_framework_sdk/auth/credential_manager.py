"""
Credential management for agentic CLI.

Follows AWS CLI patterns for credential discovery and storage.
"""

from pathlib import Path
from typing import Optional, Dict
import configparser
import os
import stat
import logging

logger = logging.getLogger(__name__)


class CredentialManager:
    """
    Manage CLI credentials with profile support.

    Provides secure credential storage and multi-environment profile support
    following industry standards (AWS CLI, kubectl, docker).
    """

    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize credential manager.

        Args:
            config_dir: Config directory (defaults to ~/.adept-agentic/)
        """
        self.config_dir = config_dir or Path.home() / ".adept-agentic"
        self.credentials_file = self.config_dir / "credentials"
        self.config_file = self.config_dir / "config.json"

    def ensure_config_dir(self) -> None:
        """
        Create config directory if it doesn't exist.

        Sets directory permissions to 700 (owner only).
        """
        self.config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        logger.debug(f"Config directory ensured: {self.config_dir}")

    def load_credentials(self, profile: str = "default") -> Dict[str, str]:
        """
        Load credentials for specified profile.

        Discovery order:
        1. ~/.adept-agentic/credentials (highest priority)
        2. ./deployment/local/docker-compose/.env-keycloak-credentials-dir/
        3. Environment variables (lowest priority)

        Args:
            profile: Profile name (default: "default")

        Returns:
            Dictionary of credentials with keys:
                - validation_runner_client_id
                - validation_runner_client_secret
                - keycloak_url
                - keycloak_realm
                - gateway_registry_url (optional)

        Raises:
            FileNotFoundError: If credentials not found in any location
            PermissionError: If credentials file has insecure permissions
            ValueError: If specified profile not found
        """
        # Try ~/.adept-agentic/credentials first
        if self.credentials_file.exists():
            logger.debug(f"Loading credentials from {self.credentials_file}")
            return self._load_from_file(profile)

        # Try ADEPT installation directory
        logger.debug("Attempting auto-discovery from ADEPT installation")
        adept_creds = self._discover_adept_credentials()
        if adept_creds:
            logger.debug("Credentials auto-discovered from ADEPT installation")
            return adept_creds

        # Fallback to environment variables
        logger.debug("Attempting to load from environment variables")
        env_creds = self._load_from_environment()
        if env_creds:
            logger.debug("Credentials loaded from environment variables")
            return env_creds

        raise FileNotFoundError(
            "No credentials found. Run 'agentic auth setup' to configure credentials."
        )

    def save_credentials(
        self,
        profile: str,
        client_id: str,
        client_secret: str,
        keycloak_url: str,
        keycloak_realm: str = "master",
        gateway_registry_url: Optional[str] = None,
    ) -> None:
        """
        Save credentials to ~/.adept-agentic/credentials.

        Creates or updates the specified profile with provided credentials.
        Sets file permissions to 600 (owner read/write only).

        Args:
            profile: Profile name
            client_id: Keycloak client ID (validation-runner-client)
            client_secret: Keycloak client secret
            keycloak_url: Keycloak server URL
            keycloak_realm: Keycloak realm (default: master)
            gateway_registry_url: Gateway registry URL (optional)
        """
        self.ensure_config_dir()

        # Load existing config or create new
        config = configparser.ConfigParser()
        if self.credentials_file.exists():
            config.read(self.credentials_file)

        # Add/update profile
        if profile not in config:
            config.add_section(profile)

        config[profile]["validation_runner_client_id"] = client_id
        config[profile]["validation_runner_client_secret"] = client_secret
        config[profile]["keycloak_url"] = keycloak_url
        config[profile]["keycloak_realm"] = keycloak_realm
        if gateway_registry_url:
            config[profile]["gateway_registry_url"] = gateway_registry_url

        # Write with secure permissions
        with open(self.credentials_file, 'w') as f:
            config.write(f)

        # Set file permissions to 600 (owner read/write only)
        os.chmod(self.credentials_file, stat.S_IRUSR | stat.S_IWUSR)
        logger.info(f"Credentials saved to {self.credentials_file} (profile: {profile})")

    def list_profiles(self) -> list:
        """
        List all configured profiles.

        Returns:
            List of profile names (empty list if no credentials file exists)
        """
        if not self.credentials_file.exists():
            return []

        config = configparser.ConfigParser()
        config.read(self.credentials_file)
        return list(config.sections())

    def delete_profile(self, profile: str) -> bool:
        """
        Delete a profile from credentials.

        Args:
            profile: Profile name to delete

        Returns:
            True if profile was deleted, False if profile didn't exist
        """
        if not self.credentials_file.exists():
            return False

        config = configparser.ConfigParser()
        config.read(self.credentials_file)

        if profile not in config:
            return False

        config.remove_section(profile)
        with open(self.credentials_file, 'w') as f:
            config.write(f)

        logger.info(f"Profile '{profile}' removed from {self.credentials_file}")
        return True

    def profile_exists(self, profile: str) -> bool:
        """
        Check if a profile exists.

        Args:
            profile: Profile name to check

        Returns:
            True if profile exists, False otherwise
        """
        return profile in self.list_profiles()

    def _load_from_file(self, profile: str) -> Dict[str, str]:
        """
        Load credentials from ~/.adept-agentic/credentials.

        Args:
            profile: Profile name to load

        Returns:
            Dictionary of credentials

        Raises:
            PermissionError: If file has insecure permissions
            ValueError: If profile not found
        """
        # Check file permissions (must be 600)
        file_stat = os.stat(self.credentials_file)
        if file_stat.st_mode & 0o077:
            raise PermissionError(
                f"Credentials file {self.credentials_file} has insecure permissions. "
                f"Run: chmod 600 {self.credentials_file}"
            )

        config = configparser.ConfigParser()
        config.read(self.credentials_file)

        if profile not in config:
            raise ValueError(
                f"Profile '{profile}' not found in credentials file. "
                f"Available profiles: {', '.join(config.sections())}"
            )

        return dict(config[profile])

    def _discover_adept_credentials(self) -> Optional[Dict[str, str]]:
        """
        Auto-discover credentials from ADEPT installation.

        Looks for credentials in these locations (in order):
        1. ./deployment/local/docker-compose/.env-keycloak-credentials-dir/.env-keycloak-credentials
        2. ../deployment/local/docker-compose/.env-keycloak-credentials-dir/.env-keycloak-credentials
        3. ../../deployment/local/docker-compose/.env-keycloak-credentials-dir/.env-keycloak-credentials

        Returns:
            Dictionary of credentials if found, None otherwise
        """
        # Search paths relative to current working directory
        search_paths = [
            Path.cwd() / "deployment/local/docker-compose/.env-keycloak-credentials-dir/.env-keycloak-credentials",
            Path.cwd().parent / "deployment/local/docker-compose/.env-keycloak-credentials-dir/.env-keycloak-credentials",
            Path.cwd().parent.parent / "deployment/local/docker-compose/.env-keycloak-credentials-dir/.env-keycloak-credentials",
        ]

        for path in search_paths:
            if path.exists():
                logger.debug(f"Found ADEPT credentials at: {path}")
                creds = self._parse_env_file(path)
                if creds:
                    return creds

        logger.debug("No ADEPT installation credentials found")
        return None

    def _parse_env_file(self, path: Path) -> Optional[Dict[str, str]]:
        """
        Parse .env file and extract A2A credentials.

        Handles the special case of SERVICE_API_KEYS_CONFIG which contains JSON
        that would break normal .env parsing.

        Args:
            path: Path to .env file

        Returns:
            Dictionary of credentials if found, None if required fields missing
        """
        credentials = {}

        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()

                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue

                    # Skip JSON lines (SERVICE_API_KEYS_CONFIG)
                    if line.startswith('SERVICE_API_KEYS_CONFIG='):
                        continue

                    # Parse key=value
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()

                        if key == "VALIDATION_RUNNER_CLIENT_ID":
                            credentials["validation_runner_client_id"] = value
                        elif key == "VALIDATION_RUNNER_CLIENT_SECRET":
                            credentials["validation_runner_client_secret"] = value

            # Add defaults if we found the required credentials
            # Use Docker service names (keycloak, gateway_registry) instead of localhost
            # to prevent JWT issuer mismatch errors. Requires /etc/hosts entries:
            #   127.0.0.1 keycloak gateway_registry agent_gateway
            if "validation_runner_client_id" in credentials and "validation_runner_client_secret" in credentials:
                credentials.setdefault("keycloak_url", "http://keycloak:8180")
                credentials.setdefault("keycloak_realm", "master")
                credentials.setdefault("gateway_registry_url", "http://gateway_registry:8086")
                return credentials

        except Exception as e:
            logger.warning(f"Failed to parse ADEPT credentials from {path}: {e}")

        return None

    def _load_from_environment(self) -> Optional[Dict[str, str]]:
        """
        Load credentials from environment variables.

        Looks for:
        - VALIDATION_RUNNER_CLIENT_ID
        - VALIDATION_RUNNER_CLIENT_SECRET
        - KEYCLOAK_URL (optional, defaults to http://localhost:8180)
        - KEYCLOAK_REALM (optional, defaults to master)
        - GATEWAY_REGISTRY_URL (optional, defaults to http://localhost:8086)

        Returns:
            Dictionary of credentials if found, None if required fields missing
        """
        client_id = os.getenv("VALIDATION_RUNNER_CLIENT_ID")
        client_secret = os.getenv("VALIDATION_RUNNER_CLIENT_SECRET")

        if not client_id or not client_secret:
            return None

        return {
            "validation_runner_client_id": client_id,
            "validation_runner_client_secret": client_secret,
            "keycloak_url": os.getenv("KEYCLOAK_URL", "http://localhost:8180"),
            "keycloak_realm": os.getenv("KEYCLOAK_REALM", "master"),
            "gateway_registry_url": os.getenv("GATEWAY_REGISTRY_URL", "http://localhost:8086"),
        }
