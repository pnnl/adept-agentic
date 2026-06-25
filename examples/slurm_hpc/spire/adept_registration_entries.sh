#!/usr/bin/env bash
# Register SPIFFE workload entries for ADEPT services in pnnl.adept trust domain.
# These entries represent the ADEPT orchestration side that communicates
# with Slurm HPC services across the federation boundary.

set -euo pipefail

SPIRE_SERVER_CMD="/opt/spire/bin/spire-server"
TRUST_DOMAIN="pnnl.adept"

echo "[adept-spire-registration] Registering ADEPT workload entries..."

# Register orchestration service (would call slurm_mcp_server across federation)
$SPIRE_SERVER_CMD entry create \
    -spiffeID "spiffe://${TRUST_DOMAIN}/orchestration-service" \
    -parentID "spiffe://${TRUST_DOMAIN}/spire-agent" \
    -selector "docker:label:spiffe.workload:orchestration-service" \
    -ttl 3600 \
    -federatesWith "spiffe://pnnl.adept.slurm" \
    2>/dev/null || echo "[adept-spire-registration] orchestration-service entry already exists"

# Register agent gateway
$SPIRE_SERVER_CMD entry create \
    -spiffeID "spiffe://${TRUST_DOMAIN}/agent-gateway" \
    -parentID "spiffe://${TRUST_DOMAIN}/spire-agent" \
    -selector "docker:label:spiffe.workload:agent-gateway" \
    -ttl 3600 \
    -federatesWith "spiffe://pnnl.adept.slurm" \
    2>/dev/null || echo "[adept-spire-registration] agent-gateway entry already exists"

echo "[adept-spire-registration] Listing all entries:"
$SPIRE_SERVER_CMD entry show

echo "[adept-spire-registration] Done."
