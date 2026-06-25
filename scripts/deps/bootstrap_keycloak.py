# scripts/deps/bootstrap_keycloak.py
"""
Keycloak Bootstrap Script - OAuth Client Configuration with Port Forwarding Support

OVERVIEW:
This script bootstraps Keycloak with OAuth2 client configurations for all services
in the ADEPT framework, including support for SSH port forwarding access patterns.

KEY FEATURES:
1. Admin-CLI Secret Auto-Discovery - No hardcoded credentials
2. Service Account Management - Automated client registration
3. SSH Port Forwarding Support - Explicit redirect URIs for common tunnel ports
4. Dynamic Port Configuration - CUSTOM_OAUTH_PORTS environment variable support

CRITICAL IMPLEMENTATION DETAIL (Session 36):
Keycloak 26.3.2 does NOT support port wildcards (:*) in redirect URIs.
Invalid patterns like "https://localhost:*/oauth2/callback" are silently ignored
during client creation but fail at runtime with "invalid_redirect_uri" errors.

SOLUTION:
This script uses EXPLICIT PORT LISTS instead of wildcards to support multiple
SSH port forwarding scenarios (8443, 8080, 8000, 443, 80) plus dynamic configuration.

RELATED DOCUMENTATION:
- docs/implementation-plans/SESSION_36_OAUTH2_REDIRECT_URI_FIX.md
  - OAuth2 redirect URI validation fix (port wildcard investigation)
  - Official Keycloak source code analysis (RedirectUtils.java)
  - OAuth2-Proxy dynamic redirect_uri behavior

- docs/implementation-reports/SESSION_36_BOOTSTRAP_KEYCLOAK_ADMIN_CLI_SECRET_FIX.md
  - Bootstrap authentication fix (admin-cli secret auto-discovery)

- docs/implementation-reports/SESSION_36_SECURITY_IMPROVEMENTS.md
  - Security improvements (no hardcoded credentials in docker-compose)

- docs/implementation-reports/SESSION_36_BOOTSTRAP_FIX_SUMMARY.md
  - Bootstrap fix summary (complete Session 36 bootstrap work)

- docs/implementation-plans/SESSION_36_FINAL_STATUS.md
  - Session 36 final status (presigned URL feature context)

- docs/implementation-reports/JUPYTERLAB_AUTHENTICATION_FLOW_WITH_PORT_FORWARDING.md
  - Complete authentication flow for port-forwarded access
  - NGINX, OAuth2-Proxy, Keycloak integration details

ENVIRONMENT VARIABLES:
- KC_ADMIN_CLI_SECRET: Admin-CLI client secret (auto-discovered if not set)
- CUSTOM_OAUTH_PORTS: Comma-separated list of custom ports (e.g., "9443,9090")
- KC_BOOTSTRAP_ADMIN_USERNAME: Keycloak admin username (default: admin)
- KC_BOOTSTRAP_ADMIN_PASSWORD: Keycloak admin password (default: admin)

USAGE:
    python scripts/deps/bootstrap_keycloak.py

    # With custom ports:
    export CUSTOM_OAUTH_PORTS="9443,9090"
    python scripts/deps/bootstrap_keycloak.py

VALIDATION:
After running this script, verify OAuth2 redirect URIs:
    docker exec keycloak /opt/keycloak/bin/kcadm.sh config credentials \\
        --server http://localhost:8180 --realm master --user admin --password admin
    docker exec keycloak /opt/keycloak/bin/kcadm.sh get clients -r master \\
        --fields clientId,redirectUris | jq '.[] | select(.clientId=="jupyterlab-client")'
"""
import os
import sys
import time
from keycloak import KeycloakAdmin, KeycloakOpenIDConnection
from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional

# --- Add src to path to import the core utility ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))
from agentic_framework_pkg.core.secrets_manager import get_secret, save_secrets
from agentic_framework_pkg.logger_config import get_logger

logger = get_logger(__name__)

# --- Pydantic Models for Configuration Validation ---
class KeycloakClientConfig(BaseModel):
    client_id: str = Field(..., alias='clientId')
    service_accounts_enabled: bool = Field(..., alias='serviceAccountsEnabled')
    direct_access_grants_enabled: bool = Field(..., alias='directAccessGrantsEnabled')
    public_client: bool = Field(..., alias='publicClient')
    standard_flow_enabled: bool = Field(..., alias='standardFlowEnabled')
    redirect_uris: Optional[List[str]] = Field(None, alias='redirectUris')

class BootstrapConfig(BaseModel):
    clients: List[KeycloakClientConfig]

def get_keycloak_admin_client():
    """Establishes a connection with the Keycloak server and returns an admin client.

    Handles both fresh installs (admin-cli is public, no secret needed) and
    existing installs (admin-cli is confidential, secret required).
    """
    admin_cli_secret = get_secret("KC_ADMIN_CLI_SECRET")

    connection_kwargs = dict(
        server_url="http://keycloak:8180/",
        username=os.getenv("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        password=os.getenv("KC_BOOTSTRAP_ADMIN_PASSWORD", "admin"),
        realm_name="master",
        user_realm_name="master",
        verify=True,
    )

    if admin_cli_secret:
        logger.info("Using KC_ADMIN_CLI_SECRET for confidential admin-cli authentication.")
        connection_kwargs["client_secret_key"] = admin_cli_secret
    else:
        logger.info("KC_ADMIN_CLI_SECRET not set — attempting public client authentication (fresh Keycloak install).")

    keycloak_connection = KeycloakOpenIDConnection(**connection_kwargs)

    for i in range(10):
        try:
            admin_client = KeycloakAdmin(connection=keycloak_connection)
            admin_client.get_realms()
            logger.info("Successfully connected to Keycloak.")
            return admin_client
        except Exception as e:
            logger.warning(f"Could not connect to Keycloak, retrying in 5 seconds... ({e})")
            time.sleep(5)

    logger.error("Failed to connect to Keycloak after multiple retries.")
    return None

def configure_realm_token_settings(admin_client: KeycloakAdmin):
    """Configure realm-level token and session settings for longer lifespans."""
    logger.info("Configuring realm token and session settings for 8-hour sessions...")
    
    # Fetch current realm representation
    realm = admin_client.get_realm(realm_name="master")
    
    # Update token lifespans to 8 hours (28800 seconds)
    eight_hours_seconds = 28800
    
    realm_updates = {
        "accessTokenLifespan": eight_hours_seconds,           # Access token lifespan
        "accessTokenLifespanForImplicitFlow": eight_hours_seconds,  # Implicit flow tokens
        "ssoSessionIdleTimeout": eight_hours_seconds,         # SSO session idle timeout
        "ssoSessionMaxLifespan": eight_hours_seconds,         # SSO session max lifespan
        "accessCodeLifespan": 300,                           # Keep auth code short (5 minutes)
        "accessCodeLifespanUserAction": 3600,               # User action codes (1 hour)
        "accessCodeLifespanLogin": 1800,                    # Login codes (30 minutes)
        "offlineSessionIdleTimeout": eight_hours_seconds,    # Offline session idle timeout
        "offlineSessionMaxLifespan": eight_hours_seconds * 30,  # Offline sessions (30 days)
    }
    
    # Update the realm with new token settings
    realm.update(realm_updates)
    admin_client.update_realm(realm_name="master", payload=realm)
    
    logger.info(f"Successfully updated realm token lifespans to {eight_hours_seconds} seconds (8 hours)")

def bootstrap_keycloak(admin_client: KeycloakAdmin):
    """
    Bootstraps the Keycloak realm with all necessary clients, groups (roles),
    and users required for the Agentic Framework to function.
    """
    def client_exists(client_id):
        all_clients = admin_client.get_clients()
        return any(c['clientId'] == client_id for c in all_clients)

    # Get public FQDN from environment (for production flexibility)
    public_fqdn = os.getenv("PUBLIC_BASE_URL", "https://api.agentic.local")
    if public_fqdn.endswith('/'):
        public_fqdn = public_fqdn.rstrip('/')

    logger.info(f"Using public FQDN for OAuth redirects: {public_fqdn}")

    clients_config_raw = {
        "clients": [
            {"clientId": "gateway-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
            {"clientId": "mgmt-ui-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
            {"clientId": "n8n-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
            {"clientId": "openwebui-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
            {"clientId": "gateway-registry-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
            {"clientId": "agent-gateway-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
            {"clientId": "admin-cli", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
            {"clientId": "validation-runner-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
            {"clientId": "langfuse-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
            {"clientId": "ragflow-client", "serviceAccountsEnabled": True, "directAccessGrantsEnabled": True, "publicClient": False, "standardFlowEnabled": False},
            {"clientId": "login-client", "serviceAccountsEnabled": False, "directAccessGrantsEnabled": True, "publicClient": True, "standardFlowEnabled": True, "redirectUris": ["http://localhost:8503/*"]},
            {
                "clientId": "jupyterlab-client",
                "name": "JupyterLab OAuth Client",
                "description": "OAuth2 client for JupyterLab SSO integration via oauth2-proxy",
                "serviceAccountsEnabled": False,
                "directAccessGrantsEnabled": False,
                "publicClient": False,
                "standardFlowEnabled": True,
                "redirectUris": [
                    # Production FQDN redirects
                    f"{public_fqdn}/oauth2/callback",
                    f"{public_fqdn}/jupyter/oauth_callback",

                    # OAuth2-Proxy standalone
                    "http://localhost:4180/oauth2/callback",

                    # Common SSH port forwarding ports (explicit)
                    # NOTE: Keycloak 26.3.2 does NOT support port wildcards (:*)
                    # These explicit ports cover 95% of SSH tunnel use cases
                    #
                    # SERVICES USING THESE PORTS (via NGINX reverse proxy):
                    # - JupyterLab: /jupyter/ → oauth2_proxy:4180 → jupyterlab:8888
                    # - Streamlit: /streamlit/ → streamlit_app:8503
                    # - OpenWebUI: /openwebui/ → openwebui:8902
                    # - Management UI: /mgmt-ui/ → agent_gateway_mgmt_ui:8502
                    # - Agent Gateway: /v1/, /a2a/ → agent_gateway:8081
                    #
                    # IMPORTANT: When adding new services that require OAuth2 authentication,
                    # update the corresponding nginx location blocks in:
                    # - infra/nginx/api.local.conf.template (main reverse proxy config)
                    # Ensure new locations use $http_host for Host header preservation
                    #
                    "https://localhost:8443/oauth2/callback",  # Most common SSH tunnel port (ssh -L 8443:localhost:443)
                    "https://localhost:8080/oauth2/callback",  # Alternative HTTPS port (common for web services)
                    "https://localhost:8000/oauth2/callback",  # Alternative HTTPS port (development servers)
                    "https://localhost:443/oauth2/callback",   # Standard HTTPS port (direct access)
                    "http://localhost:8080/oauth2/callback",   # Alternative HTTP port (non-TLS dev)
                    "http://localhost:8000/oauth2/callback",   # Alternative HTTP port (non-TLS dev)
                    "http://localhost:80/oauth2/callback",     # Standard HTTP port (non-TLS)

                    # Dynamic user-specified custom ports (from CUSTOM_OAUTH_PORTS environment variable)
                    *[f"https://localhost:{port.strip()}/oauth2/callback"
                      for port in os.getenv("CUSTOM_OAUTH_PORTS", "").split(",") if port.strip().isdigit()],
                    *[f"http://localhost:{port.strip()}/oauth2/callback"
                      for port in os.getenv("CUSTOM_OAUTH_PORTS", "").split(",") if port.strip().isdigit()]
                ],
                "webOrigins": [
                    # Production FQDN
                    public_fqdn,

                    # OAuth2-Proxy standalone
                    "http://localhost:4180",

                    # Common port forwarding ports (explicit)
                    "https://localhost:8443",
                    "https://localhost:8080",
                    "https://localhost:8000",
                    "https://localhost:443",
                    "http://localhost:8080",
                    "http://localhost:8000",
                    "http://localhost:80",

                    # Dynamic custom ports
                    *[f"https://localhost:{port.strip()}"
                      for port in os.getenv("CUSTOM_OAUTH_PORTS", "").split(",") if port.strip().isdigit()],
                    *[f"http://localhost:{port.strip()}"
                      for port in os.getenv("CUSTOM_OAUTH_PORTS", "").split(",") if port.strip().isdigit()]
                ]
            },
        ]
    }

    try:
        config = BootstrapConfig(**clients_config_raw)
    except ValidationError as e:
        logger.error(f"Keycloak client configuration is invalid: {e}")
        raise

    for client in config.clients:
        client_payload = client.model_dump(by_alias=True, exclude_none=True)
        if not client_exists(client.client_id):
            logger.info(f"Creating client: {client.client_id}")
            admin_client.create_client(payload=client_payload)
        else:
            logger.info(f"Client {client.client_id} already exists. Updating configuration...")
            # Update existing client to ensure redirect URIs and other settings are current
            internal_client_id = admin_client.get_client_id(client.client_id)
            if internal_client_id:
                try:
                    admin_client.update_client(internal_client_id, payload=client_payload)
                    logger.info(f"✅ Updated client {client.client_id} with latest configuration")
                except Exception as e:
                    logger.warning(f"Failed to update client {client.client_id}: {e}")

    for client in config.clients:
        internal_client_id = admin_client.get_client_id(client.client_id)
        
        if not internal_client_id:
            logger.warning(f"Could not find internal ID for client '{client.client_id}' while trying to add mappers.")
            continue

        mappers = admin_client.get_mappers_from_client(internal_client_id)
        
        # Add group membership mapper to clients that handle user authentication
        # Note: admin-cli is excluded as it's only for service-to-service authentication
        if client.client_id != "admin-cli":
            if not any(m['name'] == 'group membership' for m in mappers):
                logger.info(f"Adding 'group membership' protocol mapper to client '{client.client_id}'")
                mapper_payload = {
                    'name': 'group membership', 'protocol': 'openid-connect',
                    'protocolMapper': 'oidc-group-membership-mapper',
                    'config': {
                        'claim.name': 'groups', 'full.path': 'false',
                        'access.token.claim': 'true', 'id.token.claim': 'true',
                        'userinfo.token.claim': 'true', 'multivalued': 'true'
                    }
                }
                admin_client.add_mapper_to_client(internal_client_id, mapper_payload)
            else:
                logger.info(f"Client '{client.client_id}' already has a 'group membership' protocol mapper.")
        else:
            logger.info(f"Skipping 'group membership' mapper for '{client.client_id}' as it is only used for service-to-service authentication.")

        audience_mapper_name = f"audience-{client.client_id}"
        existing_audience_mapper = next((m for m in mappers if m['name'] == audience_mapper_name), None)

        if not existing_audience_mapper:
            logger.info(f"Adding audience mapper to client '{client.client_id}' to include audience '{client.client_id}'")
            mapper_payload = {
                'name': audience_mapper_name,
                'protocol': 'openid-connect',
                'protocolMapper': 'oidc-audience-mapper',
                'config': {
                    'id.token.claim': 'false',
                    'access.token.claim': 'true',
                    'included.client.audience': client.client_id,  # Use client's own client_id as audience
                }
            }
            admin_client.add_mapper_to_client(internal_client_id, mapper_payload)
        else:
            # Validate and update existing audience mapper if misconfigured
            existing_audience = existing_audience_mapper.get('config', {}).get('included.client.audience')
            if existing_audience != client.client_id:
                logger.info(f"Updating audience mapper for '{client.client_id}': {existing_audience} -> {client.client_id}")
                mapper_id = existing_audience_mapper['id']
                # Update the existing mapper with correct audience
                updated_payload = existing_audience_mapper.copy()
                updated_payload['config']['included.client.audience'] = client.client_id
                admin_client.update_client_mapper(internal_client_id, mapper_id, updated_payload)
                logger.info(f"✅ Updated audience mapper for '{client.client_id}' with correct audience")
            else:
                logger.info(f"Client '{client.client_id}' already has correct audience mapper.")

        if client.client_id in ["admin-cli", "login-client"]:
            if not any(m['name'] == 'preferred_username' for m in mappers):
                logger.info(f"Adding 'preferred_username' protocol mapper to client '{client.client_id}'")
                mapper_payload = {
                    'name': 'preferred_username', 'protocol': 'openid-connect',
                    'protocolMapper': 'oidc-usermodel-property-mapper',
                    'config': {
                        'user.attribute': 'username', 'claim.name': 'preferred_username',
                        'jsonType.label': 'String', 'access.token.claim': 'true',
                        'id.token.claim': 'true', 'userinfo.token.claim': 'true',
                    }
                }
                admin_client.add_mapper_to_client(internal_client_id, mapper_payload)
            else:
                logger.info(f"Client '{client.client_id}' already has a 'preferred_username' protocol mapper.")
            
            if not any(m['name'] == 'subject id' for m in mappers):
                logger.info(f"Adding 'subject id' protocol mapper to client '{client.client_id}' to ensure 'sub' claim.")
                mapper_payload = {
                    'name': 'subject id', 'protocol': 'openid-connect',
                    'protocolMapper': 'oidc-usermodel-property-mapper',
                    'config': {
                        'user.attribute': 'id',
                        'claim.name': 'sub',
                        'jsonType.label': 'String',
                        'access.token.claim': 'true',
                        'id.token.claim': 'true',
                    }
                }
                admin_client.add_mapper_to_client(internal_client_id, mapper_payload)
            else:
                logger.info(f"Client '{client.client_id}' already has a 'subject id' protocol mapper.")

    groups_to_create = ["notebook-users", "gateway-service", "admin", "gateway-agents", "streamlit-users"]
    for group_name in groups_to_create:
        if not any(g['name'] == group_name for g in admin_client.get_groups()):
            logger.info(f"Creating group: {group_name}")
            admin_client.create_group({"name": group_name})
        else:
            logger.info(f"Group {group_name} already exists.")

    users_to_create = [
        {"username": "notebook-user", "password_env": "NOTEBOOK_USER_PASSWORD", "default_pass": "notebook-password", "group": "notebook-users"},
        {"username": "streamlit-user", "password_env": "STREAMLIT_USER_PASSWORD", "default_pass": "streamlit-password", "group": "streamlit-users"}
    ]

    for user_spec in users_to_create:
        existing_users = admin_client.get_users({"username": user_spec["username"]})
        if not existing_users:
            logger.info(f"Creating user: {user_spec['username']}")
            user_id = admin_client.create_user({
                "username": user_spec["username"],
                "enabled": True,
                "email": f"{user_spec['username']}@example.com",
                "emailVerified": True
            })
            password = os.getenv(user_spec["password_env"], user_spec["default_pass"])
            admin_client.set_user_password(user_id, password, temporary=False)
            group_id = next((g['id'] for g in admin_client.get_groups() if g['name'] == user_spec["group"]), None)
            if group_id:
                admin_client.group_user_add(user_id, group_id)
                logger.info(f"Assigned user '{user_spec['username']}' to group '{user_spec['group']}'.")
        else:
            logger.info(f"User {user_spec['username']} already exists. Ensuring email is set and verified.")
            user_id = existing_users[0]['id']
            # Update existing user to ensure email is set and verified
            admin_client.update_user(user_id, {
                "email": f"{user_spec['username']}@example.com",
                "emailVerified": True
            })
            logger.info(f"Updated {user_spec['username']} with verified email.")

    admin_user = admin_client.get_users({"username": "admin"})
    if admin_user:
        admin_user_id = admin_user[0]['id']
        # Ensure admin user has verified email
        admin_client.update_user(admin_user_id, {
            "email": "admin@example.com",
            "emailVerified": True
        })
        logger.info("Ensured admin user has verified email.")

        admin_group_id = next((g['id'] for g in admin_client.get_groups() if g['name'] == "admin"), None)
        if admin_group_id:
            user_groups = admin_client.get_user_groups(user_id=admin_user_id)
            if not any(g['id'] == admin_group_id for g in user_groups):
                admin_client.group_user_add(admin_user_id, admin_group_id)
                logger.info("Assigned admin user to admin group.")
            else:
                logger.info("Admin user is already in the admin group.")

    client_to_group_mapping = {
        "agent-gateway-client": ["gateway-service", "gateway-agents"],
        "gateway-client": ["gateway-service", "gateway-agents"],
        "n8n-client": ["gateway-agents"],
        "openwebui-client": ["gateway-agents"],
        "mgmt-ui-client": ["admin"],  # Keep admin for service operations; UI uses user tokens for user actions
        "gateway-registry-client": ["gateway-service"],
        "validation-runner-client": ["admin"],
    }
    
    all_groups = admin_client.get_groups()
    group_name_to_id = {g['name']: g['id'] for g in all_groups}

    for client_name, group_names in client_to_group_mapping.items():
        for group_name in group_names:
            group_id = group_name_to_id.get(group_name)
            if not group_id:
                logger.error(f"CRITICAL: Group '{group_name}' not found.")
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

def configure_globus_identity_provider(admin_client: KeycloakAdmin):
    """
    Configure Globus Auth (auth.globus.org) as an external OIDC Identity Provider
    in Keycloak, enabling federated login with institutional credentials.

    This function is idempotent: it skips creation if the IdP already exists,
    and only adds mappers that are not already present.

    Requires GLOBUS_CLIENT_ID and GLOBUS_CLIENT_SECRET environment variables.
    Gated by GLOBUS_ENABLED=true.
    """
    globus_enabled = os.getenv("GLOBUS_ENABLED", "false").lower() in ("true", "1", "yes")
    if not globus_enabled:
        logger.info("Globus IdP federation disabled (GLOBUS_ENABLED != true). Skipping.")
        return

    globus_client_id = os.getenv("GLOBUS_CLIENT_ID", "")
    globus_client_secret = os.getenv("GLOBUS_CLIENT_SECRET", "")

    if not globus_client_id or not globus_client_secret:
        logger.warning(
            "GLOBUS_CLIENT_ID or GLOBUS_CLIENT_SECRET not set. "
            "Skipping Globus IdP configuration."
        )
        return

    globus_auth_url = os.getenv("GLOBUS_AUTH_URL", "https://auth.globus.org")
    idp_alias = "globus"

    # --- Step 1: Create or skip the Globus Identity Provider ---
    existing_idps = admin_client.get_idps()
    if any(idp["alias"] == idp_alias for idp in existing_idps):
        logger.info(f"Identity Provider '{idp_alias}' already exists. Skipping creation.")
    else:
        logger.info(f"Creating Identity Provider '{idp_alias}' (Globus Auth OIDC)...")
        idp_payload = {
            "alias": idp_alias,
            "displayName": "Globus Auth",
            "providerId": "oidc",
            "enabled": True,
            "trustEmail": True,
            "storeToken": True,
            "firstBrokerLoginFlowAlias": "first broker login",
            "config": {
                "clientId": globus_client_id,
                "clientSecret": globus_client_secret,
                "authorizationUrl": f"{globus_auth_url}/v2/oauth2/authorize",
                "tokenUrl": f"{globus_auth_url}/v2/oauth2/token",
                "userInfoUrl": f"{globus_auth_url}/v2/oauth2/userinfo",
                "jwksUrl": f"{globus_auth_url}/jwks.json",
                "issuer": globus_auth_url,
                "defaultScope": "openid email profile",
                "validateSignature": "true",
                "useJwksUrl": "true",
                "syncMode": "INHERIT",
                "clientAuthMethod": "client_secret_post",
            },
        }
        try:
            admin_client.create_idp(idp_payload)
            logger.info(f"Successfully created Identity Provider '{idp_alias}'.")
        except Exception as e:
            logger.error(f"Failed to create Identity Provider '{idp_alias}': {e}")
            return

    # --- Step 2: Add identity provider mappers ---
    try:
        existing_mappers = admin_client.get_idp_mappers(idp_alias)
    except Exception as e:
        logger.warning(f"Could not retrieve mappers for IdP '{idp_alias}': {e}")
        existing_mappers = []

    existing_mapper_names = {m["name"] for m in existing_mappers}

    mappers_to_create = [
        {
            "name": "globus-sub-to-attribute",
            "identityProviderAlias": idp_alias,
            "identityProviderMapper": "oidc-user-attribute-idp-mapper",
            "config": {
                "syncMode": "INHERIT",
                "claim": "sub",
                "user.attribute": "globus_uid",
            },
        },
        {
            "name": "globus-email-mapper",
            "identityProviderAlias": idp_alias,
            "identityProviderMapper": "oidc-user-attribute-idp-mapper",
            "config": {
                "syncMode": "INHERIT",
                "claim": "email",
                "user.attribute": "email",
            },
        },
        {
            "name": "globus-username-mapper",
            "identityProviderAlias": idp_alias,
            "identityProviderMapper": "oidc-username-idp-mapper",
            "config": {
                "syncMode": "INHERIT",
                "template": "${CLAIM.preferred_username}",
            },
        },
    ]

    for mapper in mappers_to_create:
        if mapper["name"] in existing_mapper_names:
            logger.info(f"IdP mapper '{mapper['name']}' already exists. Skipping.")
        else:
            try:
                admin_client.add_mapper_to_idp(idp_alias, mapper)
                logger.info(f"Added IdP mapper '{mapper['name']}' to '{idp_alias}'.")
            except Exception as e:
                logger.error(f"Failed to add IdP mapper '{mapper['name']}': {e}")

    # --- Step 3: Add protocol mapper to include globus_identity in ADEPT JWTs ---
    # This is a realm-level client scope mapper so all clients get the claim
    try:
        realm_client_scopes = admin_client.get_client_scopes()
        # Find the default "profile" scope to attach the mapper
        profile_scope = next(
            (s for s in realm_client_scopes if s["name"] == "profile"), None
        )
        if profile_scope:
            scope_id = profile_scope["id"]
            scope_mappers = admin_client.get_mappers_from_client_scope(scope_id)
            globus_identity_mapper_name = "globus_identity"

            if not any(m["name"] == globus_identity_mapper_name for m in scope_mappers):
                logger.info(
                    f"Adding '{globus_identity_mapper_name}' protocol mapper "
                    "to 'profile' client scope for ADEPT JWT inclusion."
                )
                protocol_mapper_payload = {
                    "name": globus_identity_mapper_name,
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-usermodel-attribute-mapper",
                    "config": {
                        "user.attribute": "globus_uid",
                        "claim.name": "globus_identity",
                        "jsonType.label": "String",
                        "access.token.claim": "true",
                        "id.token.claim": "true",
                        "userinfo.token.claim": "true",
                    },
                }
                admin_client.add_mapper_to_client_scope(scope_id, protocol_mapper_payload)
                logger.info(f"Added '{globus_identity_mapper_name}' mapper to 'profile' client scope.")
            else:
                logger.info(f"Protocol mapper '{globus_identity_mapper_name}' already exists in 'profile' scope.")
        else:
            logger.warning("Could not find 'profile' client scope. Skipping globus_identity protocol mapper.")
    except Exception as e:
        logger.error(f"Failed to configure globus_identity protocol mapper: {e}")

    # --- Step 4: Create slurm-hpc-client for SLURM HPC oauth2_proxy ---
    def client_exists(client_id):
        all_clients = admin_client.get_clients()
        return any(c["clientId"] == client_id for c in all_clients)

    slurm_client_id = "slurm-hpc-client"
    public_fqdn = os.getenv("PUBLIC_BASE_URL", "https://api.agentic.local")
    if public_fqdn.endswith("/"):
        public_fqdn = public_fqdn.rstrip("/")

    if not client_exists(slurm_client_id):
        logger.info(f"Creating client: {slurm_client_id}")
        slurm_client_payload = {
            "clientId": slurm_client_id,
            "name": "SLURM HPC OAuth2 Proxy Client",
            "description": "OAuth2 client for SLURM HPC cluster access via oauth2-proxy",
            "serviceAccountsEnabled": False,
            "directAccessGrantsEnabled": False,
            "publicClient": False,
            "standardFlowEnabled": True,
            "redirectUris": [
                f"{public_fqdn}/slurm/oauth2/callback",
                "http://localhost:4181/oauth2/callback",
            ],
            "webOrigins": [
                public_fqdn,
                "http://localhost:4181",
            ],
        }
        try:
            admin_client.create_client(payload=slurm_client_payload)
            logger.info(f"Successfully created client '{slurm_client_id}'.")

            # Add group membership mapper
            internal_client_id = admin_client.get_client_id(slurm_client_id)
            if internal_client_id:
                mapper_payload = {
                    "name": "group membership",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-group-membership-mapper",
                    "config": {
                        "claim.name": "groups",
                        "full.path": "false",
                        "access.token.claim": "true",
                        "id.token.claim": "true",
                        "userinfo.token.claim": "true",
                        "multivalued": "true",
                    },
                }
                admin_client.add_mapper_to_client(internal_client_id, mapper_payload)
                logger.info(f"Added 'group membership' mapper to '{slurm_client_id}'.")
        except Exception as e:
            logger.error(f"Failed to create client '{slurm_client_id}': {e}")
    else:
        logger.info(f"Client '{slurm_client_id}' already exists. Skipping creation.")

    logger.info("Globus Identity Provider configuration complete.")


def generate_service_api_keys():
    """Generate secure service API keys for external clients."""
    import secrets
    import string
    
    def generate_api_key(prefix: str, length: int = 32) -> str:
        """Generate a cryptographically secure API key."""
        alphabet = string.ascii_letters + string.digits
        random_part = ''.join(secrets.choice(alphabet) for _ in range(length))
        return f"{prefix}{random_part}"
    
    service_api_keys = {
        "openwebui": {
            "api_key": generate_api_key("sk-service-openwebui-"),
            "client_id": "openwebui-client",
            "groups": ["gateway-agents"],
            "user_id": "service-openwebui",
            "username": "openwebui-service",
            "description": "OpenWebUI service API key for Agent Gateway access"
        },
        "n8n": {
            "api_key": generate_api_key("sk-service-n8n-"),
            "client_id": "n8n-client", 
            "groups": ["gateway-agents"],
            "user_id": "service-n8n",
            "username": "n8n-service",
            "description": "N8N service API key for Agent Gateway access"
        }
    }
    return service_api_keys

def generate_and_save_secrets(admin_client: KeycloakAdmin):
    """Generate and save secrets for Keycloak clients and service API keys."""
    clients_to_secure = [
        {"client_id": "gateway-client", "secret_env": "GATEWAY_CLIENT_SECRET", "id_env": None},
        {"client_id": "mgmt-ui-client", "secret_env": "KEYCLOAK_CLIENT_SECRET", "id_env": None},
        {"client_id": "n8n-client", "secret_env": "N8N_CLIENT_SECRET", "id_env": None},
        {"client_id": "openwebui-client", "secret_env": "OPENWEBUI_CLIENT_SECRET", "id_env": None},
        {"client_id": "jupyterlab-client", "secret_env": "JUPYTERLAB_CLIENT_SECRET", "id_env": "JUPYTERLAB_CLIENT_ID"},
        {"client_id": "gateway-registry-client", "secret_env": "REGISTRY_CLIENT_SECRET", "id_env": "REGISTRY_CLIENT_ID"},
        {"client_id": "agent-gateway-client", "secret_env": "AGENT_GATEWAY_CLIENT_SECRET", "id_env": "AGENT_GATEWAY_CLIENT_ID"},
        {"client_id": "validation-runner-client", "secret_env": "VALIDATION_RUNNER_CLIENT_SECRET", "id_env": "VALIDATION_RUNNER_CLIENT_ID"},
        {"client_id": "langfuse-client", "secret_env": "LANGFUSE_CLIENT_SECRET", "id_env": "LANGFUSE_CLIENT_ID"},
        {"client_id": "ragflow-client", "secret_env": "RAGFLOW_CLIENT_SECRET", "id_env": "RAGFLOW_CLIENT_ID"},
        # CRITICAL FIX (Session 36 Phase 11): admin-cli secret must be persisted to credentials file
        # NOTE: The admin-cli secret is discovered from Keycloak DB and used for initial authentication,
        # but is then REGENERATED here (like all other clients) to ensure a fresh, known-good secret.
        # The existing authentication session remains valid during secret regeneration.
        {"client_id": "admin-cli", "secret_env": "KC_ADMIN_CLI_SECRET", "id_env": None},
    ]

    # Only include slurm-hpc-client when Globus integration is enabled
    if os.getenv("GLOBUS_ENABLED", "false").lower() in ("true", "1", "yes"):
        clients_to_secure.append(
            {"client_id": "slurm-hpc-client", "secret_env": "SLURM_HPC_CLIENT_SECRET", "id_env": "SLURM_HPC_CLIENT_ID"},
        )
    
    secrets_to_write = {}
    
    # Generate service API keys
    service_api_keys = generate_service_api_keys()
    
    # Add service API keys to secrets
    for service_name, key_info in service_api_keys.items():
        env_var_name = f"{service_name.upper()}_SERVICE_API_KEY"
        secrets_to_write[env_var_name] = key_info["api_key"]
        logger.info(f"Generated service API key for {service_name}")
    
    # Save service API keys configuration using existing secrets manager
    service_keys_config = {
        key_info["api_key"]: {
            "client_id": key_info["client_id"],
            "groups": key_info["groups"], 
            "user_id": key_info["user_id"],
            "username": key_info["username"],
            "description": key_info["description"]
        }
        for key_info in service_api_keys.values()
    }
    
    # Add service API keys config as a JSON secret
    import json
    secrets_to_write["SERVICE_API_KEYS_CONFIG"] = json.dumps(service_keys_config)
    logger.info(f"Added service API keys configuration to secrets")

    # Generate BOOTSTRAP_SERVICE_TOKENS — stable tokens for pre-Redis auth.
    # These use the same generated API keys but with elevated groups
    # (gateway-service, admin) required for service-to-service communication.
    bootstrap_tokens = {
        key_info["api_key"]: {
            "client_id": key_info["client_id"],
            "groups": ["gateway-agents", "gateway-service", "admin"],
            "user_id": key_info["user_id"],
            "username": key_info["username"],
            "description": f"{key_info['description']} (bootstrap)"
        }
        for key_info in service_api_keys.values()
    }
    secrets_to_write["BOOTSTRAP_SERVICE_TOKENS"] = json.dumps(bootstrap_tokens)
    logger.info(f"Added BOOTSTRAP_SERVICE_TOKENS ({len(bootstrap_tokens)} tokens) to secrets")

    # Generate OAuth2 Proxy cookie secret (32-byte base64-encoded)
    import secrets
    import base64
    cookie_secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    secrets_to_write["OAUTH2_PROXY_COOKIE_SECRET"] = cookie_secret
    logger.info("Generated OAuth2 Proxy cookie secret")

    for client_info in clients_to_secure:
        client_id_str = client_info["client_id"]
        try:
            internal_client_id = admin_client.get_client_id(client_id_str)
            if not internal_client_id:
                logger.error(f"Could not find internal ID for client '{client_id_str}'.")
                continue
            
            if client_info["id_env"]:
                secrets_to_write[client_info["id_env"]] = client_id_str

            new_secret = admin_client.generate_client_secrets(internal_client_id)
            secret_value = new_secret['value']
            secrets_to_write[client_info["secret_env"]] = secret_value

            # Special case: oauth2-proxy uses jupyterlab-client credentials
            # Write OAUTH2_PROXY_CLIENT_SECRET as alias for JUPYTERLAB_CLIENT_SECRET
            if client_id_str == "jupyterlab-client":
                secrets_to_write["OAUTH2_PROXY_CLIENT_SECRET"] = secret_value
                logger.info("Added OAUTH2_PROXY_CLIENT_SECRET as alias for JUPYTERLAB_CLIENT_SECRET")

        except Exception as e:
            logger.error(f"Failed to generate secret for client '{client_id_str}': {e}")

    save_secrets(
        secrets_to_write,
        output_dir="/app/credentials",
        consolidated_file_name=".env-keycloak-credentials"
    )

if __name__ == "__main__":
    admin_client = get_keycloak_admin_client()
    if admin_client:
        configure_realm_token_settings(admin_client)
        bootstrap_keycloak(admin_client)
        configure_globus_identity_provider(admin_client)
        generate_and_save_secrets(admin_client)
        logger.info("Keycloak bootstrapping and secret generation finished successfully.")
    else:
        logger.error("Keycloak bootstrapping failed.")
        exit(1)