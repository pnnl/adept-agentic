"""
This module provides the Streamlit-based Management UI for the Agent Gateway.

It offers a graphical interface for administrators to manage various aspects
of the agentic framework, including users, groups (roles), service clients,
and the tool registry.

Architectural Role:
-   **Administrative Interface:** Serves as the primary GUI for administrators.
-   **Keycloak Integration:** Interacts directly with the Keycloak Admin API
    (via the `KeycloakAdmin` client) to manage identity resources.
-   **Orchestrator API Client:** It makes authenticated API calls to the
    `orchestration_service`'s `/admin/` endpoints to manage the tool registry
    and view the gateway mesh.
"""
import streamlit as st
import httpx
import yaml
import os
import json
import asyncio
import redis.asyncio as redis
from typing import Dict, Any
from keycloak import KeycloakOpenID, KeycloakAuthenticationError
from agentic_framework_pkg.agent_gateway.identity import get_identity_providers
from agentic_framework_pkg.logger_config import get_logger
from agentic_framework_pkg.core.secrets_manager import get_secret

logger = get_logger(__name__)

# --- Configuration Loading ---
CONFIG_PATH = os.getenv("MGMT_UI_CONFIG_PATH", os.path.join(os.path.dirname(__file__), "config.yaml"))

try:
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
except FileNotFoundError:
    st.error(f"Configuration file not found at {CONFIG_PATH}")
    st.stop()
except yaml.YAMLError as e:
    st.error(f"Error parsing configuration file: {e}")
    st.stop()

# Prioritize environment variables over the YAML file
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", config.get('keycloak', {}).get('url'))
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", config.get('keycloak', {}).get('realm'))
KEYCLOAK_ADMIN_USER = os.getenv("KEYCLOAK_ADMIN_USER", config.get('keycloak', {}).get('admin_user'))
KEYCLOAK_ADMIN_PASSWORD = os.getenv("KEYCLOAK_ADMIN_PASSWORD", config.get('keycloak', {}).get('admin_password'))
KC_ADMIN_CLI_SECRET = os.getenv("KC_ADMIN_CLI_SECRET", config.get('keycloak', {}).get('admin_cli_secret'))
AGENT_GATEWAY_API_URL = os.getenv("AGENT_GATEWAY_API_URL", config.get('agent_gateway', {}).get('api_url', 'http://agent_gateway:8081'))


def authenticate_user_keycloak(username, password):
    """
    Authenticates a user against Keycloak using the ROPC flow and verifies admin role requirement.

    Note: mgmt-ui-client is configured as a confidential client with group membership mapper,
    so client_secret_key is required.

    Returns:
        Dict with user_info, access_token, refresh_token if admin user
        None if authentication fails or user lacks admin role
    """
    try:
        # Use mgmt-ui-client (has group membership mapper)
        client_id = os.getenv("KEYCLOAK_CLIENT_ID", "mgmt-ui-client")
        client_secret = get_secret("KEYCLOAK_CLIENT_SECRET")

        keycloak_openid = KeycloakOpenID(
            server_url=KEYCLOAK_URL,
            client_id=client_id,
            realm_name=KEYCLOAK_REALM,
            client_secret_key=client_secret
        )
        token = keycloak_openid.token(username, password)
        user_info = keycloak_openid.userinfo(token['access_token'])

        # SECURITY FIX: Verify user has admin role
        user_groups = user_info.get("groups", [])
        if "admin" not in user_groups:
            st.error("❌ Access Denied: Management UI requires admin role")
            logger.warning(f"Non-admin user '{username}' attempted to access Management UI (groups: {user_groups})")
            return None

        logger.info(f"Admin user '{username}' successfully authenticated")

        return {
            "user_info": user_info,
            "access_token": token['access_token'],
            "refresh_token": token['refresh_token'],
            "username": user_info.get('preferred_username', username)
        }
    except KeycloakAuthenticationError:
        st.error(f"Authentication failed for user: {username}")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred during authentication for user {username}: {e}")
        return None


def ensure_token_valid() -> bool:
    """
    Checks if user's access token is still valid and refreshes if needed.

    Returns:
        True if token is valid/refreshed successfully
        False if refresh fails (user must re-login)
    """
    from datetime import datetime, timedelta

    # Check if token will expire in next 60 seconds
    expires_at = st.session_state.get("token_expires_at")
    if not expires_at:
        logger.warning("Token expiration time not found in session state")
        return False

    if datetime.utcnow() < expires_at - timedelta(seconds=60):
        return True  # Token still valid

    # Refresh token
    try:
        # Use mgmt-ui-client (same as authentication)
        client_id = os.getenv("KEYCLOAK_CLIENT_ID", "mgmt-ui-client")
        client_secret = get_secret("KEYCLOAK_CLIENT_SECRET")

        keycloak_openid = KeycloakOpenID(
            server_url=KEYCLOAK_URL,
            client_id=client_id,
            realm_name=KEYCLOAK_REALM,
            client_secret_key=client_secret
        )

        new_token = keycloak_openid.refresh_token(
            st.session_state.refresh_token
        )

        # Update session state with new tokens
        st.session_state.access_token = new_token['access_token']
        st.session_state.refresh_token = new_token['refresh_token']
        st.session_state.token_expires_at = (
            datetime.utcnow() + timedelta(minutes=5)
        )

        logger.info(f"Refreshed token for user '{st.session_state.username}'")
        return True

    except Exception as e:
        logger.error(f"Token refresh failed for {st.session_state.username}: {e}")
        st.session_state.logged_in = False
        return False


# --- Keycloak Admin Client ---
@st.cache_resource
def get_keycloak_admin_client():
    """
    Initializes and caches the Keycloak Admin client.
    """
    try:
        # Use the identity provider factory to get the configured admin client
        _, admin_client = get_identity_providers()
        return admin_client
    except Exception as e:
        st.error(f"Unexpected error initializing Keycloak Admin Client: {e}")
        st.stop()

keycloak_admin = get_keycloak_admin_client()

def get_keycloak_groups():
    """
    Retrieves all groups from Keycloak.
    """
    try:
        return keycloak_admin.get_groups()
    except Exception as e:
        st.error(f"Error fetching groups: {e}")
        return []

def get_keycloak_users():
    """
    Retrieves all users from Keycloak.
    """
    try:
        return keycloak_admin.get_users()
    except Exception as e:
        st.error(f"Error fetching users: {e}")
        return []

# --- Keycloak Client Credentials Token Management ---
@st.cache_resource
def get_service_token_manager():
    """
    Initializes and caches the token manager for the UI's own service client.
    """
    client_id = os.getenv("KEYCLOAK_CLIENT_ID")
    client_secret = get_secret("KEYCLOAK_CLIENT_SECRET")
    
    logger.info(f"MGMT_UI: Initializing token manager for client_id: '{client_id}'")
    
    if not client_id or not client_secret:
        st.error("CRITICAL ERROR: The Management UI is missing its own credentials. KEYCLOAK_CLIENT_ID or KEYCLOAK_CLIENT_SECRET are not set in the environment. Please check the docker-compose.core.yaml file and the .env-keycloak-credentials-dir/.env-keycloak-credentials file.")
        st.stop()

    keycloak_openid = KeycloakOpenID(server_url=KEYCLOAK_URL,
                                     client_id=client_id,
                                     realm_name=KEYCLOAK_REALM,
                                     client_secret_key=client_secret)
    return keycloak_openid

def get_service_access_token():
    """
    Fetches a service-to-service access token for the UI.
    """
    keycloak_openid = get_service_token_manager()
    token = keycloak_openid.token(grant_type='client_credentials')
    return token['access_token']

# --- Agent Gateway API Interactions ---
async def get_agent_gateway_models():
    """Fetches the list of available agent models using logged-in user's token."""
    # Ensure token is fresh
    if not ensure_token_valid():
        st.error("Session expired. Please log in again.")
        st.session_state.logged_in = False
        st.rerun()
        return []

    try:
        token = st.session_state.access_token
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{AGENT_GATEWAY_API_URL}/v1/models", headers=headers)
            response.raise_for_status()
            logger.info(f"ADMIN_ACTION: User '{st.session_state.username}' fetched agent models list")
            return response.json()["data"]
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            st.error("Access denied. Admin role required.")
        else:
            st.error(f"Error fetching models: {e.response.status_code} - {e.response.text}")
    except httpx.RequestError as e:
        st.error(f"Network error fetching models: {e}")
    return []

async def get_agent_gateway_tools(model_id: str):
    """Fetches the list of tools for a specific agent model using logged-in user's token."""
    # Ensure token is fresh
    if not ensure_token_valid():
        st.error("Session expired. Please log in again.")
        st.session_state.logged_in = False
        st.rerun()
        return []

    try:
        token = st.session_state.access_token
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{AGENT_GATEWAY_API_URL}/v1/models/{model_id}/tools", headers=headers)
            response.raise_for_status()
            logger.info(f"ADMIN_ACTION: User '{st.session_state.username}' fetched tools for model '{model_id}'")
            return response.json()["tools"]
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            st.error("Access denied. Admin role required.")
        else:
            st.error(f"Error fetching tools for model {model_id}: {e.response.status_code} - {e.response.text}")
    except httpx.RequestError as e:
        st.error(f"Network error fetching tools: {e}")
    return []

async def register_agent_gateway_tool(tool_config: Dict[str, Any]):
    """Registers a new tool with the orchestration service using logged-in user's token."""
    # Ensure token is fresh
    if not ensure_token_valid():
        st.error("Session expired. Please log in again.")
        st.session_state.logged_in = False
        st.rerun()
        return {"status": "error", "message": "Session expired"}

    try:
        token = st.session_state.access_token
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{AGENT_GATEWAY_API_URL}/v1/tools/register", json=tool_config, headers=headers)
            response.raise_for_status()

            # Log successful admin action
            logger.info(
                f"ADMIN_ACTION: User '{st.session_state.username}' "
                f"registered tool '{tool_config.get('name')}'"
            )
            return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            st.error("Access denied. Admin role required.")
        else:
            st.error(f"Error registering tool: {e.response.status_code} - {e.response.text}")
        return {"status": "error", "message": str(e)}
    except httpx.RequestError as e:
        st.error(f"Network error registering tool: {e}")
        return {"status": "error", "message": "Failed to register tool due to network error."}

async def delete_agent_gateway_tool(tool_name: str):
    """Deletes a tool from the orchestration service using logged-in user's token."""
    # Ensure token is fresh
    if not ensure_token_valid():
        st.error("Session expired. Please log in again.")
        st.session_state.logged_in = False
        st.rerun()
        return {"status": "error", "message": "Session expired"}

    try:
        token = st.session_state.access_token
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            response = await client.delete(f"{AGENT_GATEWAY_API_URL}/v1/tools/{tool_name}", headers=headers)
            response.raise_for_status()

            # Log successful admin action
            logger.info(
                f"ADMIN_ACTION: User '{st.session_state.username}' "
                f"deleted tool '{tool_name}'"
            )
            return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            st.error("Access denied. Admin role required.")
        else:
            st.error(f"Error deleting tool: {e.response.status_code} - {e.response.text}")
        return {"status": "error", "message": str(e)}
    except httpx.RequestError as e:
        st.error(f"Network error deleting tool: {e}")
        return {"status": "error", "message": "Failed to delete tool due to network error."}

async def update_agent_gateway_tool_acl(tool_name: str, new_acl: Dict[str, Any]):
    """Updates the ACL for a tool in the orchestration service using logged-in user's token."""
    # Ensure token is fresh
    if not ensure_token_valid():
        st.error("Session expired. Please log in again.")
        st.session_state.logged_in = False
        st.rerun()
        return {"status": "error", "message": "Session expired"}

    try:
        token = st.session_state.access_token
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient() as client:
            response = await client.put(f"{AGENT_GATEWAY_API_URL}/v1/tools/{tool_name}/acl", json=new_acl, headers=headers)
            response.raise_for_status()

            # Log successful admin action with ACL details
            logger.info(
                f"ADMIN_ACTION: User '{st.session_state.username}' "
                f"updated ACL for tool '{tool_name}' (global={new_acl.get('global')}, "
                f"groups={len(new_acl.get('groups', []))})"
            )
            return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            st.error("Access denied. Admin role required.")
        else:
            st.error(f"Error updating tool ACL: {e.response.status_code} - {e.response.text}")
        return {"status": "error", "message": str(e)}
    except httpx.RequestError as e:
        st.error(f"Network error updating tool ACL: {e}")
        return {"status": "error", "message": "Failed to update tool ACL due to network error."}

# --- Streamlit UI --- 
st.set_page_config(page_title="Agent Gateway Management", layout="wide")
st.title("Agent Gateway Management UI")

# --- Session State Management ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "current_page" not in st.session_state:
    st.session_state.current_page = "Login"
if "access_token" not in st.session_state:
    st.session_state.access_token = None
if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = None
if "token_expires_at" not in st.session_state:
    st.session_state.token_expires_at = None

# --- Login Page ---
def show_login_page():
    """Renders the login page."""
    st.header("Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit_button = st.form_submit_button("Login")

        if submit_button:
            auth_result = authenticate_user_keycloak(username, password)
            if auth_result:
                from datetime import datetime, timedelta
                st.session_state.logged_in = True
                st.session_state.username = auth_result['username']
                st.session_state.access_token = auth_result['access_token']
                st.session_state.refresh_token = auth_result['refresh_token']
                st.session_state.token_expires_at = datetime.utcnow() + timedelta(minutes=5)
                st.session_state.current_page = "Dashboard"
                st.success("Logged in successfully!")
                st.rerun()
            else:
                st.error("Invalid username or password or insufficient privileges")
    
    

# --- Dashboard Page ---
async def show_dashboard_page():
    """Renders the main dashboard and navigation sidebar."""
    st.sidebar.title(f"Welcome, {st.session_state.username}!")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.current_page = "Login"
        st.rerun()

    st.sidebar.header("Navigation")
    if st.sidebar.button("User Management"):
        st.session_state.current_page = "User Management"
    if st.sidebar.button("Group Management"):
        st.session_state.current_page = "Group Management"
    if st.sidebar.button("Tool Management"):
        st.session_state.current_page = "Tool Management"
    if st.sidebar.button("Client Management (Service Tokens)"):
        st.session_state.current_page = "Client Management"
    if st.sidebar.button("Gateway Mesh"):
        st.session_state.current_page = "Gateway Mesh"

    if st.session_state.current_page == "Dashboard":
        st.header("Dashboard")
        st.write("Use the sidebar to navigate.")
    elif st.session_state.current_page == "User Management":
        show_user_management_page()
    elif st.session_state.current_page == "Group Management":
        show_group_management_page()
    elif st.session_state.current_page == "Tool Management":
        await show_tool_management_page()
    elif st.session_state.current_page == "Client Management":
        show_client_management_page()
    elif st.session_state.current_page == "Gateway Mesh":
        await show_gateway_mesh_page()

# --- User Management Page (Keycloak) ---
def show_user_management_page():
    """Renders the page for managing Keycloak users."""
    st.header("Keycloak User Management")

    st.subheader("Create New User")
    with st.form("create_user_form"):
        new_username = st.text_input("Username", key="create_user_username")
        new_password = st.text_input("Password", type="password", key="create_user_password")
        
        groups = get_keycloak_groups()
        group_names = [g['name'] for g in groups]
        selected_groups = st.multiselect("Assign to Groups (Roles)", group_names, key="new_user_groups")

        create_button = st.form_submit_button("Create User")

        if create_button:
            if new_username and new_password:
                try:
                    user_id = keycloak_admin.create_user(new_username, new_password)
                    st.success(f"User '{new_username}' created in Keycloak with ID: {user_id}")
                    for group_name in selected_groups:
                        group_id = next((g['id'] for g in groups if g['name'] == group_name), None)
                        if group_id:
                            keycloak_admin.add_user_to_group(user_id, group_id)
                    st.success(f"Assigned groups to '{new_username}'.")
                except Exception as e:
                    st.error(f"Failed to create user or assign groups: {e}")
            else:
                st.warning("Please enter both username and password.")
            st.rerun()

    st.subheader("Existing Users")
    users = get_keycloak_users()
    all_groups = get_keycloak_groups()
    all_group_names = [g['name'] for g in all_groups]

    if users:
        for user in users:
            with st.container():
                st.write(f"**Username:** {user['username']}")
                
                user_groups = keycloak_admin.get_user_groups(user['id'])
                current_group_names = [g['name'] for g in user_groups]
                
                selected_groups = st.multiselect(
                    "Assigned Groups (Roles)", 
                    all_group_names, 
                    default=current_group_names, 
                    key=f"user_groups_{user['id']}"
                )

                col1, col2 = st.columns([0.8, 0.2])
                with col1:
                    if st.button("Update Groups", key=f"update_groups_{user['id']}"):
                        current_group_ids = {g['id'] for g in user_groups}
                        selected_group_ids = {g['id'] for g in all_groups if g['name'] in selected_groups}
                        
                        # Add new groups
                        for group_id in selected_group_ids - current_group_ids:
                            keycloak_admin.add_user_to_group(user['id'], group_id)
                        
                        # Remove old groups
                        for group_id in current_group_ids - selected_group_ids:
                            keycloak_admin.remove_user_from_group(user['id'], group_id)
                        
                        st.success(f"Updated groups for {user['username']}.")
                        st.rerun()
                with col2:
                    if st.button("Delete User", key=f"delete_user_{user['id']}"):
                        keycloak_admin.delete_user(user['id'])
                        st.success(f"User '{user['username']}' deleted.")
                        st.rerun()
                st.markdown("---")
    else:
        st.info("No users found in Keycloak.")

# --- Group Management Page (Keycloak) ---
def show_group_management_page():
    """Renders the page for managing Keycloak groups (roles)."""
    st.header("Keycloak Group (Role) Management")

    st.subheader("Create New Group")
    with st.form("create_group_form"):
        new_group_name = st.text_input("Group Name")
        create_button = st.form_submit_button("Create Group")
        if create_button and new_group_name:
            try:
                keycloak_admin.create_group(new_group_name)
                st.success(f"Group '{new_group_name}' created.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to create group: {e}")

    st.subheader("Existing Groups")
    groups = get_keycloak_groups()
    if groups:
        for group in groups:
            col1, col2 = st.columns([0.8, 0.2])
            with col1:
                st.write(f"**Name:** {group['name']}")
            with col2:
                if st.button("Delete Group", key=f"delete_group_{group['id']}"):
                    try:
                        keycloak_admin.delete_group(group['id'])
                        st.success(f"Group '{group['name']}' deleted.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to delete group: {e}")
            st.markdown("---")
    else:
        st.info("No groups found.")

# --- Tool Management Page (Agent Gateway API) ---
async def show_tool_management_page():
    """Renders the page for managing registered tools."""
    st.header("Agent Gateway Tool Management")

    st.subheader("Registered Tools")
    # This part remains largely the same, but the ACL section will now use the group names
    # fetched from Keycloak for the multiselect.
    models = await get_agent_gateway_models()
    if models:
        selected_model_id = st.selectbox("Select Agent Model to view tools:", [m["id"] for m in models], key="tool_mgmt_model_select")
        if selected_model_id:
            tools = await get_agent_gateway_tools(selected_model_id)
            if tools:
                for tool in tools:
                    st.write(f"**Name:** {tool['name']}")
                    st.write(f"**Description:** {tool['description']}")
                    st.json(tool.get("args_schema", {}))
                    
                    col_delete, col_acl = st.columns(2)
                    with col_delete:
                        if st.button(f"Delete {tool['name']}", key=f"delete_tool_{tool['name']}"):
                            result = await delete_agent_gateway_tool(tool["name"])
                            if result.get("status") == "success":
                                st.success(f"Tool '{tool['name']}' deleted.")
                            else:
                                st.error(f"Failed to delete tool: {result.get('message', 'Unknown error')}")
                            st.rerun()
                    with col_acl:
                        with st.expander(f"Update ACL for {tool['name']}"):
                            current_acl = tool.get("acl", {"global": False, "users": [], "groups": []})
                            keycloak_groups = get_keycloak_groups()
                            keycloak_group_names = [g['name'] for g in keycloak_groups]
                            
                            # This logic correctly finds the names of the groups currently in the ACL
                            current_acl_group_ids = set(current_acl.get("groups", []))
                            current_acl_group_names = [g['name'] for g in keycloak_groups if g['id'] in current_acl_group_ids]

                            is_global = st.checkbox("Global Access", value=current_acl.get("global", False), key=f"acl_global_{tool['name']}")
                            selected_acl_groups = st.multiselect("Allowed Groups (Roles)", keycloak_group_names, default=current_acl_group_names, key=f"acl_groups_{tool['name']}")
                            
                            if st.button("Apply ACL", key=f"apply_acl_{tool['name']}"):
                                # This logic correctly maps the selected names back to IDs for the API call
                                selected_group_ids = [g['id'] for g in keycloak_groups if g['name'] in selected_acl_groups]
                                new_acl = {
                                    "global": is_global,
                                    "users": current_acl.get("users", []), # User-based ACLs are preserved but not editable in this UI
                                    "groups": selected_group_ids
                                }
                                result = await update_agent_gateway_tool_acl(tool["name"], new_acl)
                                if result.get("status") == "success":
                                    st.success(f"ACL for '{tool['name']}' updated.")
                                else:
                                    st.error(f"Failed to update ACL: {result.get('message', 'Unknown error')}")
                                st.rerun()
            else:
                st.info("No tools registered for this model.")
    else:
        st.warning("No agent models found. Ensure agent_gateway is running.")

    st.subheader("Register New Tool")
    with st.form("register_tool_form"):
        tool_name = st.text_input("Tool Name", key="reg_tool_name")
        tool_description = st.text_area("Tool Description", key="reg_tool_description")
        tool_config_json = st.text_area("Tool Configuration (JSON)", height=300,
            value="""{
  "args_schema": {},
  "invocation": {
    "protocol": "http",
    "connection": { "url": "http://example.com/api" }
  },
  "acl": { "global": true, "users": [], "groups": [] }
}""", key="reg_tool_config_json")
        register_button = st.form_submit_button("Register Tool")

        if register_button:
            try:
                parsed_config = json.loads(tool_config_json)
                parsed_config["name"] = tool_name
                parsed_config["description"] = tool_description
                result = await register_agent_gateway_tool(parsed_config)
                if result.get("status") == "success":
                    st.success(f"Tool '{tool_name}' registered.")
                else:
                    st.error(f"Failed to register tool: {result.get('message', 'Unknown error')}")
            except json.JSONDecodeError:
                st.error("Invalid JSON format.")
            except Exception as e:
                st.error(f"Error: {e}")
            st.rerun()

# --- Client Management Page (Keycloak) ---
def show_client_management_page():
    """Renders the page for managing Keycloak service clients."""
    st.header("Keycloak Client Management (Service Tokens)")

    st.subheader("Create New Client")
    with st.form("create_client_form"):
        client_id_input = st.text_input("Client ID", key="create_client_id")
        create_button = st.form_submit_button("Create Client")

        if create_button and client_id_input:
            try:
                client_info = keycloak_admin.create_or_get_service_client(client_id_input)
                st.success(f"Client '{client_id_input}' created or verified.")
                st.code(f"Client Secret: {client_info['client_secret']}", language="text")
                st.warning("Copy this secret now! It will not be shown again.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to create client: {e}")

    st.subheader("Existing Service Clients")
    try:
        clients = keycloak_admin.get_clients()
        all_groups = get_keycloak_groups()
        all_group_names = [g['name'] for g in all_groups]
        service_clients = [c for c in clients if c.get("serviceAccountsEnabled")]

        if service_clients:
            for client in service_clients:
                with st.container():
                    st.write(f"**Client ID:** {client['clientId']}")
                    
                    client_groups = keycloak_admin.get_client_groups(client['id'])
                    current_group_names = [g['name'] for g in client_groups]
                    
                    selected_groups = st.multiselect(
                        "Assigned Groups (Roles)",
                        all_group_names,
                        default=current_group_names,
                        key=f"client_groups_{client['id']}"
                    )

                    col1, col2 = st.columns([0.8, 0.2])
                    with col1:
                        if st.button("Update Groups", key=f"update_client_groups_{client['id']}"):
                            # This logic correctly calculates which groups to add and remove
                            current_group_ids = {g['id'] for g in client_groups}
                            selected_group_ids = {g['id'] for g in all_groups if g['name'] in selected_groups}
                            
                            groups_to_add = selected_group_ids - current_group_ids
                            groups_to_remove = current_group_ids - selected_group_ids
                            
                            for group_id in groups_to_add:
                                keycloak_admin.add_client_to_group(client['id'], group_id)
                            for group_id in groups_to_remove:
                                keycloak_admin.remove_client_from_group(client['id'], group_id)
                            
                            st.success(f"Updated groups for {client['clientId']}.")
                            st.rerun()
                    with col2:
                        if st.button("Delete Client", key=f"delete_client_{client['id']}"):
                            keycloak_admin.delete_client(client['id'])
                            st.success(f"Client '{client['clientId']}' deleted.")
                            st.rerun()
                    st.markdown("---")
        else:
            st.info("No service clients found.")
    except Exception as e:
        st.error(f"Failed to fetch clients: {e}")

# --- Gateway Mesh Page ---
async def show_gateway_mesh_page():
    """Renders the page for viewing the status of the gateway mesh."""
    st.header("Agent Gateway Mesh")
    st.write("This page shows all Agent Gateways that have registered themselves, forming the mesh.")

    try:
        token = get_service_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        # Fetch health status from Redis
        redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        health_data_raw = await redis_client.hgetall("gateway_health")
        health_data = {k.decode(): v.decode() for k, v in health_data_raw.items()}

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{AGENT_GATEWAY_API_URL}/v1/gateways", headers=headers)
            response.raise_for_status()
            gateways = response.json()

        if gateways:
            for gateway in gateways:
                alias = gateway.get('alias')
                if not alias:
                    continue
                
                health_status = health_data.get(alias, "Unknown")
                
                # Color-code the status
                if health_status == "Healthy":
                    st.subheader(f"Gateway Alias: `{alias}` - :large_green_circle: {health_status}")
                else:
                    st.subheader(f"Gateway Alias: `{alias}` - :red_circle: {health_status}")

                st.text(f"URL: {gateway.get('public_url', 'N/A')}")
                st.text(f"Description: {gateway.get('description', 'No description provided.')}")
                st.markdown("---")
        else:
            st.info("No other gateways have registered themselves yet.")

    except Exception as e:
        st.error(f"Failed to fetch gateway mesh data: {e}")

# --- Main App Logic ---
if st.session_state.logged_in:
    asyncio.run(show_dashboard_page()) # Run async dashboard
else:
    show_login_page()