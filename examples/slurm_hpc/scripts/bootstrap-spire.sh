#!/usr/bin/env bash
# Bootstrap SPIRE server and agent for slurm_hpc
# Run after docker compose --profile spire up

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "========================================="
echo " SPIRE Bootstrap for Slurm HPC"
echo "========================================="

# 1. Wait for SPIRE server health
echo "[1/4] Waiting for SPIRE server..."
MAX_RETRIES=30
for i in $(seq 1 $MAX_RETRIES); do
    if docker exec slurm_spire_server /opt/spire/bin/spire-server healthcheck 2>/dev/null; then
        echo "[1/4] SPIRE server healthy."
        break
    fi
    if [ "$i" = "$MAX_RETRIES" ]; then
        echo "[ERROR] SPIRE server not healthy after ${MAX_RETRIES} attempts"
        exit 1
    fi
    sleep 2
done

# 2. Generate join token for agent
echo "[2/4] Generating agent join token..."
JOIN_TOKEN=$(docker exec slurm_spire_server /opt/spire/bin/spire-server token generate \
    -spiffeID "spiffe://pnnl.adept.slurm/spire-agent" \
    -ttl 600 2>/dev/null | grep -oP 'Token: \K.*' || true)

if [ -z "$JOIN_TOKEN" ]; then
    echo "[WARN] Could not extract join token (agent may already be attested)"
else
    echo "[2/4] Join token generated (TTL: 600s)"
    # Write join token for agent to pick up
    docker exec slurm_spire_agent sh -c "echo '${JOIN_TOKEN}' > /opt/spire/data/agent/join_token"
fi

# 3. Wait for SPIRE agent
echo "[3/4] Waiting for SPIRE agent..."
for i in $(seq 1 $MAX_RETRIES); do
    if docker exec slurm_spire_agent /opt/spire/bin/spire-agent healthcheck 2>/dev/null; then
        echo "[3/4] SPIRE agent healthy."
        break
    fi
    if [ "$i" = "$MAX_RETRIES" ]; then
        echo "[WARN] SPIRE agent not healthy after ${MAX_RETRIES} attempts (may need manual join token)"
    fi
    sleep 2
done

# 4. Register workload entries
echo "[4/4] Registering workload entries..."
docker exec slurm_spire_server /bin/sh /opt/spire/conf/registration-entries.sh

echo ""
echo "========================================="
echo " SPIRE Bootstrap Complete"
echo "========================================="
echo ""
echo "Verify with:"
echo "  docker exec slurm_spire_server /opt/spire/bin/spire-server healthcheck"
echo "  docker exec slurm_spire_server /opt/spire/bin/spire-server entry show"
echo "  docker exec slurm_mcp_server python -c 'from slurm_mcp.spiffe_auth import get_jwt_svid; print(get_jwt_svid())'"
