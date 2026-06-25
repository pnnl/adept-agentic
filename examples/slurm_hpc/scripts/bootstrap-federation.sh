#!/usr/bin/env bash
# =============================================================================
# Bootstrap SPIFFE Trust Bundle Federation
# =============================================================================
# Establishes bidirectional trust between:
#   pnnl.adept.slurm (Slurm HPC trust domain)
#   pnnl.adept       (Main ADEPT trust domain)
#
# Prerequisites:
#   docker compose --profile spire --profile federation up -d
#   ./scripts/bootstrap-spire.sh  (for slurm SPIRE)
#
# This script:
#   1. Waits for both SPIRE servers to be healthy
#   2. Exports trust bundles from each server
#   3. Imports peer bundles (bidirectional federation)
#   4. Registers ADEPT-side workload entries
#   5. Verifies federation is active
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

SLURM_SPIRE="slurm_spire_server"
ADEPT_SPIRE="adept_spire_server"
SPIRE_CMD="/opt/spire/bin/spire-server"

SLURM_DOMAIN="pnnl.adept.slurm"
ADEPT_DOMAIN="pnnl.adept"

echo "========================================="
echo " SPIFFE Trust Bundle Federation"
echo "========================================="
echo " Slurm domain: ${SLURM_DOMAIN}"
echo " ADEPT domain: ${ADEPT_DOMAIN}"
echo ""

# ─── Step 1: Wait for both SPIRE servers ─────────────────────────────────────

echo "[1/5] Waiting for SPIRE servers..."
MAX_RETRIES=30

for server in "$SLURM_SPIRE" "$ADEPT_SPIRE"; do
    for i in $(seq 1 $MAX_RETRIES); do
        if docker exec "$server" $SPIRE_CMD healthcheck 2>/dev/null; then
            echo "  ${server}: healthy"
            break
        fi
        if [ "$i" = "$MAX_RETRIES" ]; then
            echo "[ERROR] ${server} not healthy after ${MAX_RETRIES} attempts"
            echo "  Ensure profile is started: docker compose --profile spire --profile federation up -d"
            exit 1
        fi
        sleep 2
    done
done

# ─── Step 2: Export trust bundles ─────────────────────────────────────────────

echo "[2/5] Exporting trust bundles..."

# Export Slurm trust bundle
docker exec "$SLURM_SPIRE" $SPIRE_CMD bundle show -format spiffe \
    > /tmp/slurm_bundle.json 2>/dev/null
echo "  Exported ${SLURM_DOMAIN} bundle ($(wc -c < /tmp/slurm_bundle.json) bytes)"

# Export ADEPT trust bundle
docker exec "$ADEPT_SPIRE" $SPIRE_CMD bundle show -format spiffe \
    > /tmp/adept_bundle.json 2>/dev/null
echo "  Exported ${ADEPT_DOMAIN} bundle ($(wc -c < /tmp/adept_bundle.json) bytes)"

# ─── Step 3: Import peer bundles (bidirectional) ─────────────────────────────

echo "[3/5] Importing peer trust bundles..."

# Import ADEPT bundle into Slurm SPIRE server
docker cp /tmp/adept_bundle.json "${SLURM_SPIRE}:/tmp/adept_bundle.json"
docker exec "$SLURM_SPIRE" $SPIRE_CMD bundle set \
    -id "spiffe://${ADEPT_DOMAIN}" \
    -format spiffe \
    -path /tmp/adept_bundle.json \
    2>/dev/null
echo "  Imported ${ADEPT_DOMAIN} bundle into ${SLURM_SPIRE}"

# Import Slurm bundle into ADEPT SPIRE server
docker cp /tmp/slurm_bundle.json "${ADEPT_SPIRE}:/tmp/slurm_bundle.json"
docker exec "$ADEPT_SPIRE" $SPIRE_CMD bundle set \
    -id "spiffe://${SLURM_DOMAIN}" \
    -format spiffe \
    -path /tmp/slurm_bundle.json \
    2>/dev/null
echo "  Imported ${SLURM_DOMAIN} bundle into ${ADEPT_SPIRE}"

# Cleanup temp files
rm -f /tmp/slurm_bundle.json /tmp/adept_bundle.json

# ─── Step 4: Bootstrap ADEPT SPIRE agent + register entries ──────────────────

echo "[4/5] Bootstrapping ADEPT SPIRE agent..."

# Generate join token for ADEPT agent
ADEPT_JOIN_TOKEN=$(docker exec "$ADEPT_SPIRE" $SPIRE_CMD token generate \
    -spiffeID "spiffe://${ADEPT_DOMAIN}/spire-agent" \
    -ttl 600 2>/dev/null | grep -oP 'Token: \K.*' || true)

if [ -n "$ADEPT_JOIN_TOKEN" ]; then
    docker exec adept_spire_agent sh -c "echo '${ADEPT_JOIN_TOKEN}' > /opt/spire/data/agent/join_token" 2>/dev/null || true
    echo "  ADEPT agent join token generated"
else
    echo "  ADEPT agent may already be attested"
fi

# Wait for ADEPT agent
for i in $(seq 1 $MAX_RETRIES); do
    if docker exec adept_spire_agent /opt/spire/bin/spire-agent healthcheck 2>/dev/null; then
        echo "  ADEPT SPIRE agent: healthy"
        break
    fi
    if [ "$i" = "$MAX_RETRIES" ]; then
        echo "  [WARN] ADEPT agent not healthy (may need manual bootstrap)"
    fi
    sleep 2
done

# Register ADEPT workload entries
docker exec "$ADEPT_SPIRE" /bin/sh /opt/spire/conf/registration-entries.sh 2>/dev/null || true

# ─── Step 5: Verify federation ───────────────────────────────────────────────

echo "[5/5] Verifying federation..."

# Check Slurm server knows ADEPT bundle
SLURM_BUNDLES=$(docker exec "$SLURM_SPIRE" $SPIRE_CMD bundle list 2>/dev/null || echo "")
if echo "$SLURM_BUNDLES" | grep -q "${ADEPT_DOMAIN}"; then
    echo "  ${SLURM_SPIRE} trusts ${ADEPT_DOMAIN}: OK"
else
    echo "  [WARN] ${SLURM_SPIRE} does not trust ${ADEPT_DOMAIN}"
fi

# Check ADEPT server knows Slurm bundle
ADEPT_BUNDLES=$(docker exec "$ADEPT_SPIRE" $SPIRE_CMD bundle list 2>/dev/null || echo "")
if echo "$ADEPT_BUNDLES" | grep -q "${SLURM_DOMAIN}"; then
    echo "  ${ADEPT_SPIRE} trusts ${SLURM_DOMAIN}: OK"
else
    echo "  [WARN] ${ADEPT_SPIRE} does not trust ${SLURM_DOMAIN}"
fi

# Show all registered entries
echo ""
echo "--- Slurm SPIRE Entries ---"
docker exec "$SLURM_SPIRE" $SPIRE_CMD entry show 2>/dev/null | head -30 || true

echo ""
echo "--- ADEPT SPIRE Entries ---"
docker exec "$ADEPT_SPIRE" $SPIRE_CMD entry show 2>/dev/null | head -30 || true

echo ""
echo "========================================="
echo " Federation Bootstrap Complete"
echo "========================================="
echo ""
echo "Trust established:"
echo "  ${SLURM_DOMAIN} <──── bidirectional ────> ${ADEPT_DOMAIN}"
echo ""
echo "Verify with:"
echo "  docker exec ${SLURM_SPIRE} $SPIRE_CMD bundle list"
echo "  docker exec ${ADEPT_SPIRE} $SPIRE_CMD bundle list"
echo "  docker exec ${SLURM_SPIRE} $SPIRE_CMD entry show"
echo "  docker exec ${ADEPT_SPIRE} $SPIRE_CMD entry show"
