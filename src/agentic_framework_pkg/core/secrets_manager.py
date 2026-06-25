# src/agentic_framework_pkg/core/secrets_manager.py
import os
import json
import base64
from typing import Optional, Dict
from ..logger_config import get_logger

logger = get_logger(__name__)

SECRET_RETRIEVAL_METHOD = os.getenv("SECRET_RETRIEVAL_METHOD", "file").lower()
SECRET_FILE_PATH = os.getenv("SECRET_FILE_PATH", "/run/secrets")

def get_secret(secret_name: str) -> Optional[str]:
    """
    Retrieves a secret, adapting to the configured retrieval method.

    This function is the central point for accessing secrets. It checks the
    SECRET_RETRIEVAL_METHOD environment variable to determine whether to read
    the secret from a file (e.g., a Docker or Kubernetes secret) or from
    environment variables.

    Args:
        secret_name: The name of the secret to retrieve (e.g., "AGENT_GATEWAY_CLIENT_SECRET").

    Returns:
        The secret value as a string, or None if not found.
    """
    if SECRET_RETRIEVAL_METHOD == "file":
        # Docker/K8s secrets can have varied casing, but we standardize on UPPERCASE for our file names.
        path = os.path.join(SECRET_FILE_PATH, secret_name.upper())
        logger.debug(f"Attempting to read secret '{secret_name}' from file: {path}")
        try:
            with open(path, 'r') as f:
                secret_value = f.read().strip()
                if secret_value:
                    logger.debug(f"Secret '{secret_name}' read successfully from file.")
                else:
                    logger.warning(f"Secret file for '{secret_name}' was empty.")
                return secret_value
        except FileNotFoundError:
            # Fallback for Docker secrets which are always lowercase
            path_lower = os.path.join(SECRET_FILE_PATH, secret_name.lower())
            logger.debug(f"Uppercase secret not found, trying lowercase: {path_lower}")
            try:
                with open(path_lower, 'r') as f:
                    secret_value = f.read().strip()
                    if secret_value:
                        logger.debug(f"Secret '{secret_name}' read successfully from lowercase file.")
                    else:
                        logger.warning(f"Lowercase secret file for '{secret_name}' was empty.")
                    return secret_value
            except FileNotFoundError:
                logger.warning(f"Secret file not found for '{secret_name}' at either uppercase or lowercase paths.")
                # Fallback: Try /app/credentials directory
                creds_path = f"/app/credentials/{secret_name}"
                logger.debug(f"Attempting fallback to credentials directory: {creds_path}")
                try:
                    with open(creds_path, 'r') as f:
                        secret_value = f.read().strip()
                        if secret_value:
                            logger.debug(f"Secret '{secret_name}' read successfully from credentials directory.")
                        else:
                            logger.warning(f"Credentials directory file for '{secret_name}' was empty.")
                        return secret_value
                except FileNotFoundError:
                    logger.warning(f"Secret file not found in credentials directory: {creds_path}")
                    # Final fallback: Check environment variable even when using file method
                    env_value = os.getenv(secret_name)
                    if env_value:
                        logger.debug(f"Secret '{secret_name}' retrieved from environment variable as final fallback.")
                        return env_value
                    return None
        except Exception as e:
            logger.error(f"Error reading secret file at {path}: {e}", exc_info=True)
            # Fallback: Try /app/credentials directory
            creds_path = f"/app/credentials/{secret_name}"
            logger.debug(f"Attempting fallback to credentials directory after error: {creds_path}")
            try:
                with open(creds_path, 'r') as f:
                    secret_value = f.read().strip()
                    if secret_value:
                        logger.debug(f"Secret '{secret_name}' read successfully from credentials directory.")
                    else:
                        logger.warning(f"Credentials directory file for '{secret_name}' was empty.")
                    return secret_value
            except FileNotFoundError:
                logger.warning(f"Secret file not found in credentials directory: {creds_path}")
                # Final fallback: Check environment variable even when using file method
                env_value = os.getenv(secret_name)
                if env_value:
                    logger.debug(f"Secret '{secret_name}' retrieved from environment variable as final fallback.")
                    return env_value
                return None
    else: # Default to environment variables
        logger.debug(f"Attempting to read secret '{secret_name}' from environment variable.")
        return os.getenv(secret_name)

def _save_secrets_to_file(secrets_to_write: Dict[str, str], output_dir: str, consolidated_file_name: str):
    """
    Saves secrets to individual files for Docker/K8s and to a consolidated
    .env file for legacy services.
    """
    os.makedirs(output_dir, exist_ok=True)
    consolidated_path = os.path.join(output_dir, consolidated_file_name)
    
    logger.info(f"Saving secrets to individual files in directory: {output_dir}")
    logger.info(f"Saving secrets to consolidated env file: {consolidated_path}")

    with open(consolidated_path, "w") as env_file:
        for key, value in secrets_to_write.items():
            env_file.write(f"{key.upper()}={value}\n")
            # We consistently use the uppercase secret name as the filename.
            individual_file_path = os.path.join(output_dir, key.upper())
            with open(individual_file_path, "w") as secret_file:
                secret_file.write(value)
                logger.debug(f"Wrote secret for {key} to {individual_file_path} (length: {len(value)})")
    
    logger.info(f"Successfully wrote {len(secrets_to_write)} secrets.")

def _save_secrets_to_k8s(secrets_to_write: Dict[str, str], secret_name: str, namespace: str):
    """Creates or updates a Kubernetes Secret with the given data."""
    try:
        from kubernetes import client, config
        from kubernetes.client.rest import ApiException
    except ImportError:
        logger.error("Kubernetes client library not found. Please install 'kubernetes' to use K8s secret management.")
        raise

    config.load_incluster_config()
    k8s_client = client.CoreV1Api()

    encoded_secrets = {key: base64.b64encode(value.encode()).decode() for key, value in secrets_to_write.items()}
    
    metadata = {"name": secret_name, "namespace": namespace}
    secret_body = {"apiVersion": "v1", "kind": "Secret", "metadata": metadata, "data": encoded_secrets}

    try:
        k8s_client.read_namespaced_secret(name=secret_name, namespace=namespace)
        logger.info(f"Secret '{secret_name}' already exists. Patching with new data.")
        k8s_client.patch_namespaced_secret(name=secret_name, namespace=namespace, body=secret_body)
        logger.info(f"Successfully patched Secret '{secret_name}'.")
    except ApiException as e:
        if e.status == 404:
            logger.info(f"Secret '{secret_name}' not found. Creating it now.")
            k8s_client.create_namespaced_secret(namespace=namespace, body=secret_body)
            logger.info(f"Successfully created Secret '{secret_name}'.")
        else:
            logger.error(f"An unexpected Kubernetes API error occurred: {e}", exc_info=True)
            raise

def save_secrets(secrets_to_write: Dict[str, str], **kwargs):
    """
    Saves secrets, adapting to the execution environment.
    - In Kubernetes, it creates/updates a Kubernetes Secret.
    - In Docker Compose, it writes to files.
    """
    if "KUBERNETES_SERVICE_HOST" in os.environ:
        logger.info("Kubernetes environment detected. Saving secrets to K8s Secret.")
        secret_name = kwargs.get("secret_name", "keycloak-client-secrets")
        namespace = kwargs.get("namespace", "agentic-framework")
        _save_secrets_to_k8s(secrets_to_write, secret_name, namespace)
    else:
        logger.info("File-based environment (Docker Compose) detected. Saving secrets to files.")
        output_dir = kwargs.get("output_dir", "/app/credentials")
        consolidated_file = kwargs.get("consolidated_file_name", ".env-keycloak-credentials")
        _save_secrets_to_file(secrets_to_write, output_dir, consolidated_file)
