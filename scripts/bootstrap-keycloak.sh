#!/bin/bash
# bootstrap-keycloak.sh

# This script is executed inside the Keycloak container to perform a full,
# idempotent setup of all necessary realms, clients, users, and roles.

set -ex

# --- Configuration ---
REALM="master"
ADMIN_USER="${KEYCLOAK_ADMIN:-admin}"
ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
KCADM="/opt/keycloak/bin/kcadm.sh"

# List of clients to create. Add new clients here.
CLIENTS=(
  "gateway-client"
  "mgmt-ui-client"
  "n8n-client"
  "openwebui-client"
)

# --- Helper Functions ---
kcadm() {
    $KCADM "$@" --server http://keycloak:8180 --realm $REALM --user $ADMIN_USER --password $ADMIN_PASSWORD
}

# --- Main Logic ---
echo "Keycloak bootstrap script started." >&2

# 1. Log in to the admin CLI
echo "Attempting to log in to Keycloak admin CLI..." >&2
$KCADM config credentials --server http://keycloak:8180 --realm $REALM --user $ADMIN_USER --password $ADMIN_PASSWORD

echo "Login successful." >&2

# 2. Create clients and retrieve secrets
for CLIENT_NAME in "${CLIENTS[@]}"; do
    echo "Processing client: $CLIENT_NAME" >&2
    
    # Check if client already exists
    CLIENT_ID=$(kcadm get clients --fields id,clientId | jp "[?clientId=='$CLIENT_NAME'].id | [0]")

    if [ -z "$CLIENT_ID" ]; then
        echo "Client '$CLIENT_NAME' does not exist. Creating..." >&2
        kcadm create clients -s clientId="$CLIENT_NAME" -s enabled=true -s serviceAccountsEnabled=true -s 'protocol=openid-connect' -s 'publicClient=false' -s 'bearerOnly=false' -s 'standardFlowEnabled=false' -s 'directAccessGrantsEnabled=true'
        CLIENT_ID=$(kcadm get clients --fields id,clientId | jp "[?clientId=='$CLIENT_NAME'].id | [0]")
        echo "Client '$CLIENT_NAME' created with ID: $CLIENT_ID" >&2
    else
        echo "Client '$CLIENT_NAME' already exists with ID: $CLIENT_ID" >&2
    fi

    # Get the client secret
    SECRET=$(kcadm get "clients/$CLIENT_ID/client-secret" | jp "value")
    if [ -z "$SECRET" ]; then
        echo "Could not get secret for client '$CLIENT_NAME'. Regenerating..." >&2
        SECRET=$(kcadm create "clients/$CLIENT_ID/client-secret" | jp "value")
    fi

    # Echo the secret for the calling script to eval
    # Convert client name to a valid shell variable name (e.g., mgmt-ui-client -> MGMT_UI_CLIENT_SECRET)
    VAR_NAME=$(echo "$CLIENT_NAME" | tr '[:lower:]-' '[:upper:]_' "_SECRET")
    echo "export $VAR_NAME=\"$SECRET\""
done

# 3. Create notebook user and group
echo "Processing notebook user and group..." >&2
GROUP_NAME="notebook-users"
USER_NAME="notebook-user"
USER_PASS="notebook-password"

# Check if group exists
GROUP_ID=$(kcadm get groups --fields id,name | jp "[?name=='$GROUP_NAME'].id | [0]")
if [ -z "$GROUP_ID" ]; then
    echo "Group '$GROUP_NAME' does not exist. Creating..." >&2
    kcadm create groups -s name="$GROUP_NAME"
    GROUP_ID=$(kcadm get groups --fields id,name | jp "[?name=='$GROUP_NAME'].id | [0]")
    echo "Group '$GROUP_NAME' created with ID: $GROUP_ID" >&2
else
    echo "Group '$GROUP_NAME' already exists with ID: $GROUP_ID" >&2
fi

# Check if user exists
USER_ID=$(kcadm get users -q username="$USER_NAME" --fields id,username | jp "[0].id")
if [ -z "$USER_ID" ]; then
    echo "User '$USER_NAME' does not exist. Creating..." >&2
    kcadm create users -s username="$USER_NAME" -s enabled=true
    USER_ID=$(kcadm get users -q username="$USER_NAME" --fields id,username | jp "[0].id")
    echo "User '$USER_NAME' created with ID: $USER_ID" >&2
    
    echo "Setting password for user '$USER_NAME'..." >&2
    kcadm set-password -r $REALM --username "$USER_NAME" --new-password "$USER_PASS"
else
    echo "User '$USER_NAME' already exists with ID: $USER_ID" >&2
fi

# Add user to group
echo "Adding user '$USER_NAME' to group '$GROUP_NAME'..." >&2
kcadm update "users/$USER_ID/groups/$GROUP_ID" -r $REALM -s realm="$REALM" -s userId="$USER_ID" -s groupId="$GROUP_ID" -n

echo "Keycloak bootstrap script finished successfully." >&2