#!/bin/bash
# Generic operational utility commands for any ADEPT EC2 instance.
#
# Usage:
#   ./scripts/instance-ops.sh <context> <command>
#   ./scripts/instance-ops.sh aws-123456789012-rc6 check-health
#   ./scripts/instance-ops.sh aws-123456789012-dev ssh
#
# Context is resolved from contexts/<context>/context.env
# If context.env doesn't exist, falls back to README.md parsing or env vars.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKYPILOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SKYPILOT_DIR/../.." && pwd)"

# --- Argument parsing ---
if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <deploy-context> <command>"
    echo ""
    echo "Examples:"
    echo "  $0 aws-123456789012-rc6 check-health"
    echo "  $0 aws-123456789012-dev ssh"
    echo "  $0 aws-123456789012-rc6 validate-cli"
    echo ""
    echo "Available contexts:"
    for ctx in "$SKYPILOT_DIR"/contexts/*/; do
        if [ -d "$ctx" ]; then
            echo "  $(basename "$ctx")"
        fi
    done
    echo ""
    echo "Commands:"
    echo "  ssh-test        Test SSH connectivity"
    echo "  ssh             Open interactive SSH session"
    echo "  check-services  Count running containers"
    echo "  check-health    Full health check (containers + healthchecks)"
    echo "  tail-quickstart Tail quickstart log on remote"
    echo "  tail-deploy     Tail latest local deploy log"
    echo "  check-creds     Verify credential files non-empty"
    echo "  check-llm-yaml  Verify config/llm.yaml exists"
    echo "  docker-ps       List all containers with status"
    echo "  disk-usage      Check /data disk usage"
    echo "  nessus-status   Check Nessus agent state"
    echo "  validate-cli    Run CLI E2E tests (polls until complete)"
    echo "  validate TARGET Run arbitrary make target (polls until complete)"
    echo "  inject-pubkey   Inject CDK key into authorized_keys (via SSM)"
    exit 0
fi

DEPLOY_CONTEXT="$1"
COMMAND="$2"
shift 2

CONTEXT_DIR="$SKYPILOT_DIR/contexts/$DEPLOY_CONTEXT"
if [[ ! -d "$CONTEXT_DIR" ]]; then
    echo "ERROR: Context directory not found: $CONTEXT_DIR"
    echo "Available: $(ls "$SKYPILOT_DIR/contexts/" 2>/dev/null | tr '\n' ' ')"
    exit 1
fi

# --- Load context configuration ---
# Try context.env first (key=value file), then fall back to conventions
if [[ -f "$CONTEXT_DIR/context.env" ]]; then
    source "$CONTEXT_DIR/context.env"
else
    # Derive from DEPLOY_CONTEXT naming convention: aws-{account}-{label}
    # Pattern: aws-123456789012-rc6 → env=rc, user=rc6
    ACCOUNT=$(echo "$DEPLOY_CONTEXT" | cut -d'-' -f2)
    LABEL=$(echo "$DEPLOY_CONTEXT" | cut -d'-' -f3-)

    # Heuristic: if label starts with "rc" it's env=rc user=label
    # Otherwise env=dev user=label
    if [[ "$LABEL" == rc* ]]; then
        CDK_ENV_LABEL="${CDK_ENV_LABEL:-rc}"
        CDK_USER_LABEL="${CDK_USER_LABEL:-$LABEL}"
    elif [[ "$LABEL" == "dev" || "$LABEL" == "$USER" ]]; then
        CDK_ENV_LABEL="${CDK_ENV_LABEL:-dev}"
        CDK_USER_LABEL="${CDK_USER_LABEL:-${USER}}"
    else
        CDK_ENV_LABEL="${CDK_ENV_LABEL:-dev}"
        CDK_USER_LABEL="${CDK_USER_LABEL:-$LABEL}"
    fi
fi

export CDK_ENV_LABEL="${CDK_ENV_LABEL:-dev}"
export CDK_USER_LABEL="${CDK_USER_LABEL:-${USER}}"
export DEPLOY_CONTEXT

# Find SSH key
SSH_KEY=$(find "$CONTEXT_DIR" -name "*.pem" -type f 2>/dev/null | head -1)
TARGET_HOST="${TARGET_HOST:-}"
SSH_USER="${SSH_USER:-ubuntu}"

# Try to extract IP from README if not set
if [[ -z "$TARGET_HOST" && -f "$CONTEXT_DIR/README.md" ]]; then
    TARGET_HOST=$(grep -oP '(?<=Private IP \| )\d+\.\d+\.\d+\.\d+' "$CONTEXT_DIR/README.md" 2>/dev/null || true)
fi

# --- SSM helper (uses cdk-ssm-run-wait for long commands, cdk-ssm-run for quick ones) ---
ssm_quick() {
    CMD="$1" make -C "$SKYPILOT_DIR" cdk-ssm-run 2>&1 | grep -v "^#\|CACHED\|exporting\|naming\|writing\|DONE\|load build\|transferring\|docker build\|Building\|SkyPilot"
}

ssm_wait() {
    CMD="$1" "$SKYPILOT_DIR/scripts/cdk-ssm-run-wait.sh"
}

# --- Commands ---
case "$COMMAND" in
    ssh-test)
        if [[ -z "$SSH_KEY" || -z "$TARGET_HOST" ]]; then
            echo "ERROR: SSH key or target host not found for context $DEPLOY_CONTEXT"
            exit 1
        fi
        ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
            -i "$SSH_KEY" "$SSH_USER@$TARGET_HOST" 'hostname && uptime'
        ;;
    ssh)
        if [[ -z "$SSH_KEY" || -z "$TARGET_HOST" ]]; then
            echo "ERROR: SSH key or target host not found for context $DEPLOY_CONTEXT"
            exit 1
        fi
        ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" "$SSH_USER@$TARGET_HOST"
        ;;
    check-services)
        ssm_quick 'docker ps --format "{{.Names}}: {{.Status}}" | wc -l; docker ps --format "{{.Names}}: {{.Status}}" | grep -c healthy || echo 0 healthy'
        ;;
    check-health)
        ssm_quick 'echo "=== Containers ==="; docker ps --format "table {{.Names}}\t{{.Status}}" | head -30; echo; echo "=== Unhealthy ==="; docker ps --filter health=unhealthy --format "{{.Names}}: {{.Status}}" || echo NONE'
        ;;
    tail-quickstart)
        ssm_quick 'tail -50 /data/workspace/adept-*/logs/quickstart-*.log 2>/dev/null || echo NO_LOG'
        ;;
    tail-deploy)
        LATEST_LOG=$(ls -t "$CONTEXT_DIR/logs/" 2>/dev/null | head -1)
        if [[ -n "$LATEST_LOG" ]]; then
            tail -50 "$CONTEXT_DIR/logs/$LATEST_LOG"
        else
            echo "No local deploy logs found in $CONTEXT_DIR/logs/"
        fi
        ;;
    check-creds)
        ssm_quick 'cd /data/workspace/adept-*/ && wc -c deployment/local/docker-compose/.env-keycloak-credentials-dir/VALIDATION_RUNNER_CLIENT_SECRET deployment/local/docker-compose/.env-keycloak-credentials-dir/KC_ADMIN_CLI_SECRET 2>/dev/null || echo MISSING'
        ;;
    check-llm-yaml)
        ssm_quick 'ls -la /data/workspace/adept-*/config/llm.yaml 2>/dev/null || echo MISSING; cat /data/workspace/adept-*/config/llm.yaml 2>/dev/null | head -5 || true'
        ;;
    docker-ps)
        ssm_quick 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | head -35'
        ;;
    disk-usage)
        ssm_quick 'df -h /data; du -sh /data/workspace/adept-*/data/ 2>/dev/null | head -5'
        ;;
    nessus-status)
        ssm_quick 'sudo /opt/nessus_agent/sbin/nessuscli agent status 2>/dev/null || echo NOT_INSTALLED'
        ;;
    validate-cli)
        echo "Running CLI E2E on $DEPLOY_CONTEXT (polls until complete)..."
        ssm_wait 'cd /data/workspace/adept-*/ && make validate-cli-all'
        ;;
    validate)
        MAKE_TARGET="${1:-validate-all}"
        echo "Running 'make $MAKE_TARGET' on $DEPLOY_CONTEXT (polls until complete)..."
        ssm_wait "cd /data/workspace/adept-*/ && make $MAKE_TARGET"
        ;;
    inject-pubkey)
        if [[ -z "$SSH_KEY" ]]; then
            echo "ERROR: SSH key not found for context $DEPLOY_CONTEXT"
            exit 1
        fi
        PUBKEY=$(ssh-keygen -y -f "$SSH_KEY")
        ssm_quick "mkdir -p /home/$SSH_USER/.ssh && echo '$PUBKEY' > /home/$SSH_USER/.ssh/authorized_keys && chmod 700 /home/$SSH_USER/.ssh && chmod 600 /home/$SSH_USER/.ssh/authorized_keys && chown -R $SSH_USER:$SSH_USER /home/$SSH_USER/.ssh && echo DONE"
        ;;
    *)
        echo "Unknown command: $COMMAND"
        echo "Run '$0' without arguments for usage."
        exit 1
        ;;
esac
