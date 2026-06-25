#!/bin/bash
# Run command on EC2 instance via SSM with proper poll-until-complete.
#
# Unlike cdk-ssm-run.sh (single 10s poll), this script retries until
# the command reaches a terminal state (Success/Failed/TimedOut).
#
# Usage:
#   SSM_WAIT=5 SSM_MAX_POLLS=60 ./scripts/cdk-ssm-run-wait.sh 'make validate-cli-config'
#   CMD='make validate-cli-all' ./scripts/cdk-ssm-run-wait.sh
#
# Environment:
#   CMD                - Command to execute (or pass as $1)
#   CDK_ENV_LABEL      - Stack env label (default: dev)
#   CDK_USER_LABEL     - Stack user label (default: $USER)
#   SSM_WAIT           - Seconds between polls (default: 15)
#   SSM_MAX_POLLS      - Max poll attempts before giving up (default: 40 = 10 min)
#   SSM_TIMEOUT        - SSM command timeout in seconds (default: 600)
#   WORKSPACE_PATH     - Override workspace path (default: auto-detect)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKYPILOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SKYPILOT_DIR/../.." && pwd)"

SKYPILOT_IMAGE="${SKYPILOT_IMAGE:-adept-skypilot:latest}"
CDK_ENV_LABEL="${CDK_ENV_LABEL:-dev}"
CDK_USER_LABEL="${CDK_USER_LABEL:-${USER}}"
STACK_NAME="ADE-${CDK_ENV_LABEL}-${CDK_USER_LABEL}-Stack"
SSM_WAIT="${SSM_WAIT:-15}"
SSM_MAX_POLLS="${SSM_MAX_POLLS:-40}"
SSM_TIMEOUT="${SSM_TIMEOUT:-600}"

CMD="${1:-${CMD:-}}"
if [[ -z "$CMD" ]]; then
    echo "ERROR: Command required. Pass as argument or set CMD env var."
    exit 1
fi

# Source AWS credentials
if [[ -z "${AWS_ACCESS_KEY_ID:-}" ]]; then
    if [[ -f "$PROJECT_ROOT/setup-claude-bedrock.sh" ]]; then
        source "$PROJECT_ROOT/setup-claude-bedrock.sh"
    else
        echo "ERROR: AWS credentials not set and setup-claude-bedrock.sh not found"
        exit 1
    fi
fi

AWS_RUN="docker run --rm \
    -e AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID \
    -e AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY \
    -e AWS_DEFAULT_REGION=us-west-2 \
    --entrypoint aws $SKYPILOT_IMAGE"

# Resolve instance ID
echo "Target stack: $STACK_NAME (CDK_ENV_LABEL=$CDK_ENV_LABEL, CDK_USER_LABEL=$CDK_USER_LABEL)"
INSTANCE_ID=$($AWS_RUN cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' --output text)
echo "Instance: $INSTANCE_ID"

# Build SSM payload
export INSTANCE_ID SSM_TIMEOUT
python3 -c "
import json, os, sys
json.dump({
    'DocumentName': 'AWS-RunShellScript',
    'InstanceIds': [os.environ['INSTANCE_ID']],
    'TimeoutSeconds': int(os.environ['SSM_TIMEOUT']),
    'Parameters': {'commands': [sys.argv[1]]}
}, open('/tmp/ssm-cmd.json', 'w'))
" "$CMD"

# Send command
CMD_ID=$(docker run --rm \
    -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    -e AWS_DEFAULT_REGION=us-west-2 \
    -v /tmp/ssm-cmd.json:/tmp/ssm-cmd.json:ro \
    --entrypoint aws "$SKYPILOT_IMAGE" \
    ssm send-command --cli-input-json file:///tmp/ssm-cmd.json \
    --query Command.CommandId --output text)

echo "Command: $CMD_ID"
echo "Polling every ${SSM_WAIT}s (max ${SSM_MAX_POLLS} attempts)..."

# Poll loop
for i in $(seq 1 "$SSM_MAX_POLLS"); do
    sleep "$SSM_WAIT"
    RESULT=$(docker run --rm \
        -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
        -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
        -e AWS_DEFAULT_REGION=us-west-2 \
        --entrypoint aws "$SKYPILOT_IMAGE" \
        ssm get-command-invocation \
          --command-id "$CMD_ID" \
          --instance-id "$INSTANCE_ID" \
          --output json 2>&1) || true

    STATUS=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('Status','Unknown'))" 2>/dev/null || echo "Unknown")

    case "$STATUS" in
        Success)
            echo ""
            echo "=== SUCCESS (poll $i/${SSM_MAX_POLLS}) ==="
            echo "$RESULT" | python3 -c "
import json, sys
r = json.load(sys.stdin)
out = r.get('StandardOutputContent', '')
err = r.get('StandardErrorContent', '')
if out: print(out.rstrip())
if err: print('--- STDERR ---'); print(err.rstrip())
"
            exit 0
            ;;
        Failed|TimedOut|Cancelled)
            echo ""
            echo "=== FAILED (Status: $STATUS, poll $i/${SSM_MAX_POLLS}) ==="
            echo "$RESULT" | python3 -c "
import json, sys
r = json.load(sys.stdin)
out = r.get('StandardOutputContent', '')
err = r.get('StandardErrorContent', '')
if out: print(out.rstrip())
if err: print('--- STDERR ---'); print(err.rstrip())
"
            exit 1
            ;;
        InProgress|Pending|Delayed)
            printf "  [%d/%d] %s...\r" "$i" "$SSM_MAX_POLLS" "$STATUS"
            ;;
        *)
            echo "  [${i}/${SSM_MAX_POLLS}] Unexpected status: $STATUS"
            ;;
    esac
done

echo ""
echo "ERROR: Command still running after $((SSM_MAX_POLLS * SSM_WAIT))s. CommandId: $CMD_ID"
echo "Manual check: aws ssm get-command-invocation --command-id $CMD_ID --instance-id $INSTANCE_ID"
exit 2
