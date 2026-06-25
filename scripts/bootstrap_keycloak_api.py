# scripts/bootstrap_keycloak_api.py
import os
import time
import logging
from datetime import datetime
from keycloak import KeycloakAdmin, KeycloakOpenIDConnection

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def get_keycloak_admin_client():
    """Establishes a connection with the Keycloak server and returns an admin client."""
    keycloak_connection = KeycloakOpenIDConnection(
        server_url="http://keycloak:8180/",
        username=os.getenv("KC_BOOTSTRAP_ADMIN_USERNAME"),
        password=os.getenv("KC_BOOTSTRAP_ADMIN_PASSWORD"),
        realm_name="master",
        user_realm_name="master",
        verify=True
    )
    
    for i in range(10):
        try:
            admin_client = KeycloakAdmin(connection=keycloak_connection)
            admin_client.get_realms() # Test connection
            logger.info("Successfully connected to Keycloak.")
            return admin_client
        except Exception as e:
            logger.warning(f"Could not connect to Keycloak, retrying in 5 seconds... ({e})")
            time.sleep(5)
    
    logger.error("Failed to connect to Keycloak after multiple retries.")
    return None

def bootstrap_keycloak(admin_client: KeycloakAdmin):
    """
    Bootstraps the Keycloak realm with all necessary clients, groups (roles),
    and users required for the Agentic Framework to function.
    """
    def client_exists(client_id):
        all_clients = admin_client.get_clients()
        return any(c['clientId'] == client_id for c in all_clients)

    clients = [
        {"clientId": "gateway-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
        {"clientId": "mgmt-ui-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
        {"clientId": "n8n-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
        {"clientId": "openwebui-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
        {"clientId": "gateway-registry-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
        {"clientId": "agent-gateway-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
    ]

    for client in clients:
        if not client_exists(client["clientId"]):
            logger.info(f"Creating client: {client['clientId']}")
            admin_client.create_client(payload=client)
        else:
            logger.info(f"Client {client['clientId']} already exists.")

    # Add Group Membership protocol mappers to all service clients
    for client_config in clients:
        client_id_str = client_config["clientId"]
        internal_client_id = admin_client.get_client_id(client_id_str)
        
        if not internal_client_id:
            logger.warning(f"Could not find internal ID for client '{client_id_str}' while trying to add mappers.")
            continue

        mappers = admin_client.get_mappers_from_client(internal_client_id)
        if not any(m['name'] == 'group membership' for m in mappers):
            logger.info(f"Adding 'group membership' protocol mapper to client '{client_id_str}'")
            mapper_payload = {
                'name': 'group membership',
                'protocol': 'openid-connect',
                'protocolMapper': 'oidc-group-membership-mapper',
                'config': {
                    'claim.name': 'groups',
                    'full.path': 'false',
                    'access.token.claim': 'true',
                    'id.token.claim': 'true',
                    'userinfo.token.claim': 'true',
                    'multivalued': 'true'
                }
            }
            admin_client.add_mapper_to_client(internal_client_id, mapper_payload)
        else:
            logger.info(f"Client '{client_id_str}' already has a 'group membership' protocol mapper.")

    def group_exists(group_name):
        all_groups = admin_client.get_groups()
        return any(g['name'] == group_name for g in all_groups)

    groups_to_create = ["notebook-users", "gateway-service", "admin", "gateway-agents"]
    for group_name in groups_to_create:
        if not group_exists(group_name):
            logger.info(f"Creating group: {group_name}")
            admin_client.create_group({"name": group_name})
        else:
            logger.info(f"Group {group_name} already exists.")

    def user_exists(username):
        all_users = admin_client.get_users()
        return any(u['username'] == username for u in all_users)

    user_name = "notebook-user"
    if not user_exists(user_name):
        logger.info(f"Creating user: {user_name}")
        user_id = admin_client.create_user({"username": user_name, "enabled": True})
        admin_client.set_user_password(user_id, os.getenv("NOTEBOOK_USER_PASSWORD", "notebook-password"), temporary=False)
        
        all_groups = admin_client.get_groups()
        group_id = next((g['id'] for g in all_groups if g['name'] == "notebook-users"), None)
        if group_id:
            admin_client.group_user_add(user_id, group_id)
    else:
        logger.info(f"User {user_name} already exists.")

    client_to_group_mapping = {
        "agent-gateway-client": ["gateway-service", "gateway-agents"],
        "gateway-client": ["gateway-service", "gateway-agents"],
        "n8n-client": ["gateway-agents"],
        "openwebui-client": ["gateway-agents"],
        "mgmt-ui-client": ["admin"],
        "gateway-registry-client": ["gateway-service"],
    }
    
    all_groups = admin_client.get_groups()
    group_name_to_id = {g['name']: g['id'] for g in all_groups}

    for client_name, group_names in client_to_group_mapping.items():
        for group_name in group_names:
            group_id = group_name_to_id.get(group_name)
            if not group_id:
                logger.error(f"CRITICAL: Group '{group_name}' not found. Cannot assign client '{client_name}'.")
                continue
            
            try:
                client_internal_id = admin_client.get_client_id(client_name)
                if client_internal_id:
                    service_account = admin_client.get_client_service_account_user(client_internal_id)
                    if service_account:
                        user_groups = admin_client.get_user_groups(user_id=service_account['id'])
                        if not any(g['id'] == group_id for g in user_groups):
                            admin_client.group_user_add(service_account['id'], group_id)
                            logger.info(f"Successfully assigned '{client_name}' to the '{group_name}' group.")
            except Exception as e:
                logger.error(f"Failed to assign '{client_name}' to '{group_name}' group: {e}")

def generate_and_save_secrets(admin_client: KeycloakAdmin):
    env_file_path = "/app/credentials/.env-keycloak-credentials"
    clients_with_secrets = [
        "gateway-client", 
        "mgmt-ui-client", 
        "n8n-client", 
        "openwebui-client",
        "gateway-registry-client",
        "agent-gateway-client",
    ]
    secrets_to_write = {}

    logger.info(f"Generating secrets for clients and preparing to write to {env_file_path}")
    os.makedirs(os.path.dirname(env_file_path), exist_ok=True)

    for client_id_str in clients_with_secrets:
        try:
            internal_client_id = admin_client.get_client_id(client_id_str)
            if not internal_client_id:
                logger.error(f"Could not find internal ID for client '{client_id_str}'.")
                continue
            
            new_secret = admin_client.generate_client_secrets(internal_client_id)
            secret_value = new_secret['value']
            
            if client_id_str == "gateway-client":
                secrets_to_write["GATEWAY_CLIENT_SECRET"] = secret_value
            elif client_id_str == "mgmt-ui-client":
                secrets_to_write["KEYCLOAK_CLIENT_SECRET"] = secret_value
            elif client_id_str == "n8n-client":
                secrets_to_write["N8N_CLIENT_SECRET"] = secret_value
            elif client_id_str == "openwebui-client":
                secrets_to_write["OPENWEBUI_CLIENT_SECRET"] = secret_value
            elif client_id_str == "gateway-registry-client":
                secrets_to_write["REGISTRY_CLIENT_SECRET"] = secret_value
            elif client_id_str == "agent-gateway-client":
                secrets_to_write["AGENT_GATEWAY_CLIENT_SECRET"] = secret_value
        except Exception as e:
            logger.error(f"Failed to generate secret for client '{client_id_str}': {e}")

    with open(env_file_path, "w") as f:
        f.write(f"# Generated at {datetime.now().isoformat()}\n")
        for key, value in secrets_to_write.items():
            f.write(f"{key}={value}\n")
            
    time.sleep(1) # Note: Added to give some delay to file flushing before keycloak-setup exists 
    logger.info(f"Successfully wrote secrets to {env_file_path}")

if __name__ == "__main__":
    admin_client = get_keycloak_admin_client()
    if admin_client:
        bootstrap_keycloak(admin_client)
        generate_and_save_secrets(admin_client)
        logger.info("Keycloak bootstrapping and secret generation finished successfully.")
    else:
        logger.error("Keycloak bootstrapping failed.")
        exit(1)