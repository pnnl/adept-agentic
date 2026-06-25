#!/usr/bin/env bash
# validate-ansible-parity.sh — Verify SkyPilot YAMLs cover critical Ansible phases
#
# Compares task YAMLs against deployment/ansible/playbooks/prepare-rocky-vm.yml
# to ensure no critical setup phase is missing.
#
# Usage:
#   ./scripts/validate-ansible-parity.sh [yaml_dir]
#   Default: /app/skypilot/tasks/

set -euo pipefail

YAML_DIR="${1:-/app/skypilot/tasks}"
ERRORS=0

echo "============================================"
echo "SkyPilot Ansible Parity Validation"
echo "============================================"
echo ""
echo "Reference: deployment/ansible/playbooks/prepare-rocky-vm.yml (10 phases)"

# Define Ansible phases and their required grep patterns per YAML type
# Format: "phase_name|pattern|cloud_required|existing_vm_required"
CHECKS=(
  "Phase 1: Disk validation|AVAILABLE_GB|yes|no"
  "Phase 2: Docker CE install|get.docker.com|yes|yes"
  "Phase 3: Docker data root|data-root|yes|yes"
  "Phase 5: Unprivileged ports|unprivileged_port_start|yes|yes"
  "Phase 5: /etc/hosts|api.agentic.local|yes|yes"
  "Phase 5: Firewall rules|firewall-cmd|no|yes"
  "Phase 6: Podman cleanup|podman.*reset|no|yes"
  "Phase 7: Docker smoke test|hello-world|yes|yes"
  "Phase 8: TLS certificate|openssl req|yes|yes"
  "Phase 8: Data dir init|init-shared-volume-permissions|yes|yes"
  "Phase 9: .env config|NGINX_PUBLIC_FQDN|yes|yes"
)

check_yaml() {
  local yaml_file="$1"
  local filename
  filename=$(basename "$yaml_file")

  # Detect type: cloud task has "resources:" key
  local is_cloud="no"
  if grep -q '^resources:' "$yaml_file"; then
    is_cloud="yes"
  fi

  echo ""
  echo "--- ${filename} (type: $([ "$is_cloud" = "yes" ] && echo "cloud" || echo "existing-vm")) ---"

  for check in "${CHECKS[@]}"; do
    IFS='|' read -r phase pattern cloud_req vm_req <<< "$check"

    # Determine if this check applies
    local required="no"
    if [ "$is_cloud" = "yes" ] && [ "$cloud_req" = "yes" ]; then
      required="yes"
    fi
    if [ "$is_cloud" = "no" ] && [ "$vm_req" = "yes" ]; then
      required="yes"
    fi

    if [ "$required" = "no" ]; then
      printf "  %-35s N/A\n" "$phase:"
      continue
    fi

    # Check if pattern exists in YAML
    if grep -qE "$pattern" "$yaml_file" 2>/dev/null; then
      printf "  %-35s PASS\n" "$phase:"
    else
      printf "  %-35s FAIL\n" "$phase:"
      ERRORS=$((ERRORS + 1))
    fi
  done
}

# Validate all YAMLs
for yaml_file in "$YAML_DIR"/*.yaml; do
  check_yaml "$yaml_file"
done

# --- AWS CDK Parity (resource specs) ---
echo ""
echo "--- AWS CDK Resource Spec Parity ---"
echo "  Reference: devtools/aws-cdk/stacks/dev_environment_stack.py"

CLOUD_YAML="$YAML_DIR/deploy-adept-cloud.yaml"
if [ -f "$CLOUD_YAML" ]; then
  # Check disk size matches CDK (500 GB)
  printf "  %-35s " "disk_size >= 500:"
  if grep -q 'disk_size: 500' "$CLOUD_YAML"; then
    echo "PASS"
  else
    echo "FAIL"
    ERRORS=$((ERRORS + 1))
  fi

  # Check CPU spec matches CDK (8+ for t3.2xlarge)
  printf "  %-35s " "cpus >= 8:"
  if grep -q 'cpus: 8' "$CLOUD_YAML"; then
    echo "PASS"
  else
    echo "FAIL"
    ERRORS=$((ERRORS + 1))
  fi

  # Check memory spec matches CDK (32+ GB)
  printf "  %-35s " "memory >= 32:"
  if grep -q 'memory: 32' "$CLOUD_YAML"; then
    echo "PASS"
  else
    echo "FAIL"
    ERRORS=$((ERRORS + 1))
  fi

  # Check use_spot is false (ADEPT is stateful)
  printf "  %-35s " "use_spot: false:"
  if grep -q 'use_spot: false' "$CLOUD_YAML"; then
    echo "PASS"
  else
    echo "FAIL"
    ERRORS=$((ERRORS + 1))
  fi

  # Check critical ports exposed
  for port in 443 80 8083 8180; do
    printf "  %-35s " "port ${port} exposed:"
    if grep -qE "^\s+- ${port}\b" "$CLOUD_YAML"; then
      echo "PASS"
    else
      echo "FAIL"
      ERRORS=$((ERRORS + 1))
    fi
  done
fi

# --- Summary ---
echo ""
echo "============================================"
if [ $ERRORS -eq 0 ]; then
  echo "ALL PARITY CHECKS PASSED"
  exit 0
else
  echo "FAILED: ${ERRORS} parity check(s) failed"
  exit 1
fi
