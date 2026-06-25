# scripts/inspect_mappers.py
import os
import sys
from keycloak import KeycloakAdmin, KeycloakOpenIDConnection

# --- Add src to path to import the core utility ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))
from agentic_framework_pkg.logger_config import get_logger

logger = get_logger(__name__)

def get_keycloak_admin_client():
    """Establishes a connection with the Keycloak server and returns an admin client."""
    keycloak_connection = KeycloakOpenIDConnection(
        #server_url="http://keycloak:8180/",
        server_url="http://localhost:8180/",
        username=os.getenv("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        password=os.getenv("KC_BOOTSTRAP_ADMIN_PASSWORD", "admin"),
        realm_name="master",
        user_realm_name="master",
        verify=True
    )
    
    try:
        admin_client = KeycloakAdmin(connection=keycloak_connection)
        admin_client.get_realms() # Test connection
        logger.info("Successfully connected to Keycloak.")
        return admin_client
    except Exception as e:
        logger.error(f"Could not connect to Keycloak: {e}")
        return None

def inspect_mappers():
    """Inspects the mappers for the admin-cli client."""
    admin_client = get_keycloak_admin_client()
    if not admin_client:
        return

    client_id_str = "admin-cli"
    internal_client_id = admin_client.get_client_id(client_id_str)
    
    if not internal_client_id:
        logger.error(f"Could not find internal ID for client '{client_id_str}'.")
        return

    mappers = admin_client.get_mappers_from_client(internal_client_id)
    
    logger.info(f"Mappers for client '{client_id_str}':")
    for mapper in mappers:
        logger.info(f"  - Name: {mapper['name']}")
        logger.info(f"    Config: {mapper['config']}")

if __name__ == "__main__":
    inspect_mappers()
