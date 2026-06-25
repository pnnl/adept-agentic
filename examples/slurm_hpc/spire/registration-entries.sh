#!/usr/bin/env bash
# Register SPIFFE workload entries for slurm_hpc services
# Run after SPIRE server is healthy and agent is attested

set -euo pipefail

SPIRE_SERVER_CMD="/opt/spire/bin/spire-server"
TRUST_DOMAIN="pnnl.adept.slurm"

echo "[spire-registration] Registering workload entries..."

# Register slurm_mcp_server (federates with pnnl.adept for cross-domain trust)
$SPIRE_SERVER_CMD entry create \
    -spiffeID "spiffe://${TRUST_DOMAIN}/slurm-mcp-server" \
    -parentID "spiffe://${TRUST_DOMAIN}/spire-agent" \
    -selector "docker:label:spiffe.workload:slurm-mcp-server" \
    -ttl 3600 \
    -federatesWith "spiffe://pnnl.adept" \
    2>/dev/null || echo "[spire-registration] slurm-mcp-server entry already exists"

# Register slurmrestd (federation with pnnl.adept for cross-domain trust)
$SPIRE_SERVER_CMD entry create \
    -spiffeID "spiffe://${TRUST_DOMAIN}/slurmrestd" \
    -parentID "spiffe://${TRUST_DOMAIN}/spire-agent" \
    -selector "docker:label:spiffe.workload:slurmrestd" \
    -ttl 3600 \
    -federatesWith "spiffe://pnnl.adept" \
    2>/dev/null || echo "[spire-registration] slurmrestd entry already exists"

echo "[spire-registration] Listing all entries:"
$SPIRE_SERVER_CMD entry show

echo "[spire-registration] Done."
