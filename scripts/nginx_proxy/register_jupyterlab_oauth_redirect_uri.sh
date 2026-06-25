#!/bin/bash
# Register OAuth2 Redirect URI for JupyterLab External Access (v2 - Zero Downtime)
#
# Purpose: Adds OAuth2 callback redirect URIs to Keycloak for external IP addresses
#          or production hostnames used to access JupyterLab via nginx_proxy.
#
# Why needed: Keycloak validates OAuth2 redirect_uri against a pre-configured allow-list.
#             When accessing JupyterLab via a new IP or hostname (e.g., production domain,
#             EC2 public IP), you must register that host's callback URL in Keycloak.
#
# Version 2 Features:
#   ✅ Zero downtime - no service restarts needed
#   ✅ Hot-reload via Keycloak Admin API (kcadm.sh)
#   ✅ Idempotent - safe to run multiple times (checks for duplicates)
#   ✅ Proper API usage instead of raw SQL
#
# Usage:
#   ./register_jupyterlab_oauth_redirect_uri.sh [hostname_or_ip]
#
# Examples:
#   ./register_jupyterlab_oauth_redirect_uri.sh 10.16.17.5              # EC2 public IP
#   ./register_jupyterlab_oauth_redirect_uri.sh myapp.example.com       # Production domain
#   ./register_jupyterlab_oauth_redirect_uri.sh ec2-54-123-45-67.compute-1.amazonaws.com
#
# Default: 10.16.17.5 (if no argument provided)
#
# Note: Registers HTTPS (port 443) only - browsers omit :443 from URLs

HOST=${1:-10.16.17.5}
NEW_URI="https://$HOST/oauth2/callback"
CONFIG_FILE="/tmp/kcadm.config"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Registering OAuth2 Redirect URI for External Access (v2)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Host/IP:       $HOST"
echo "  Redirect URI:  $NEW_URI"
echo "  Protocol:      HTTPS (port 443)"
echo "  Method:        Keycloak Admin API (zero downtime)"
echo ""

# Step 1: Get KC_ADMIN_CLI_SECRET from credentials directory
echo "Loading admin-cli client secret..."
CREDENTIALS_DIR="deployment/local/docker-compose/.env-keycloak-credentials-dir"

if [ ! -f "$CREDENTIALS_DIR/KC_ADMIN_CLI_SECRET" ]; then
  echo "ERROR: KC_ADMIN_CLI_SECRET not found in $CREDENTIALS_DIR"
  echo "Run 'make fix-credentials' to regenerate credentials."
  exit 1
fi

KC_ADMIN_CLI_SECRET=$(cat "$CREDENTIALS_DIR/KC_ADMIN_CLI_SECRET")

if [ -z "$KC_ADMIN_CLI_SECRET" ]; then
  echo "ERROR: KC_ADMIN_CLI_SECRET is empty"
  exit 1
fi

# Step 2: Authenticate kcadm.sh with admin credentials + client secret
echo "Authenticating with Keycloak Admin API..."
docker exec keycloak /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8180 \
  --realm master \
  --user admin \
  --password admin \
  --client admin-cli \
  --secret "$KC_ADMIN_CLI_SECRET" \
  --config "$CONFIG_FILE" \
  >/dev/null 2>&1

if [ $? -ne 0 ]; then
  echo "ERROR: Failed to authenticate with Keycloak Admin API"
  echo "Check that Keycloak is running and admin credentials are correct."
  exit 1
fi

# Step 3: Get jupyterlab-client UUID
echo "Getting jupyterlab-client UUID..."
CLIENT_UUID=$(docker exec keycloak /opt/keycloak/bin/kcadm.sh get clients \
  -r master \
  --fields id,clientId \
  --format csv \
  --noquotes \
  --config "$CONFIG_FILE" 2>/dev/null | grep "jupyterlab-client" | cut -d',' -f1)

if [ -z "$CLIENT_UUID" ]; then
  echo "ERROR: Could not find jupyterlab-client"
  exit 1
fi

echo "Client UUID: $CLIENT_UUID"

# Step 4: Get current redirect URIs (JSON format)
echo "Fetching current redirect URIs..."
REDIRECT_URIS_JSON=$(docker exec keycloak /opt/keycloak/bin/kcadm.sh get clients/"$CLIENT_UUID" \
  -r master \
  --fields redirectUris \
  --config "$CONFIG_FILE" 2>/dev/null)

if [ -z "$REDIRECT_URIS_JSON" ]; then
  echo "ERROR: Could not fetch current redirect URIs"
  exit 1
fi

# Extract redirect URIs from JSON (extract all quoted http/https URLs)
CURRENT_URIS=$(echo "$REDIRECT_URIS_JSON" | grep -o '"https\?://[^"]*"' | sed 's/"//g' | xargs)

echo "Current redirect URIs: $CURRENT_URIS"

# Step 5: Check if new URI already exists (idempotency)
if echo "$CURRENT_URIS" | grep -qF "$NEW_URI"; then
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "✅ Redirect URI Already Registered (Idempotent)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  echo "The redirect URI is already registered:"
  echo "  $NEW_URI"
  echo ""
  echo "No changes needed. You can access JupyterLab at:"
  echo "  https://$HOST/jupyter/"
  echo ""
  echo "Login credentials:"
  echo "  Username: notebook-user"
  echo "  Password: notebook-password"
  echo ""
  exit 0
fi

# Step 6: Append new URI to list
echo "Adding new redirect URI..."

# Build JSON array from current URIs + new URI
# Convert space-separated list to JSON array format
ALL_URIS="$CURRENT_URIS $NEW_URI"
URIS_JSON=$(echo "$ALL_URIS" | tr ' ' '\n' | awk '{print "\"" $0 "\""}' | paste -sd ',' -)

# Step 7: Update client with new redirect URIs (hot-reload, no restart)
echo "Updating client configuration via Admin API..."
docker exec keycloak /opt/keycloak/bin/kcadm.sh update clients/"$CLIENT_UUID" \
  -r master \
  -s "redirectUris=[$URIS_JSON]" \
  --config "$CONFIG_FILE" \
  >/dev/null 2>&1

if [ $? -ne 0 ]; then
  echo "ERROR: Failed to update client redirect URIs"
  echo "Check Keycloak logs for details: docker logs keycloak --tail 50"
  exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Registration Complete (Zero Downtime)!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Redirect URI added successfully:"
echo "  $NEW_URI"
echo ""
echo "Changes took effect immediately (no restarts needed)."
echo ""
echo "You can now access JupyterLab at:"
echo "  https://$HOST/jupyter/"
echo ""
echo "Login credentials:"
echo "  Username: notebook-user"
echo "  Password: notebook-password"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "All registered redirect URIs for jupyterlab-client:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker exec keycloak /opt/keycloak/bin/kcadm.sh get clients/"$CLIENT_UUID" \
  -r master \
  --fields redirectUris \
  --config "$CONFIG_FILE" 2>/dev/null | grep -o '"https\?://[^"]*"' | sed 's/"//g' | awk '{print "  " $0}'
echo ""
