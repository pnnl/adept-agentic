#!/bin/bash
# Schedule EC2 instance stop after N minutes.
# Usage: ./scripts/cdk-schedule-stop.sh [minutes]  (default: 120)
# Env: CDK_ENV_LABEL (default: dev), CDK_USER_LABEL (default: $USER)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

SKYPILOT_IMAGE="${SKYPILOT_IMAGE:-adept-skypilot:latest}"
CDK_ENV_LABEL="${CDK_ENV_LABEL:-dev}"
CDK_USER_LABEL="${CDK_USER_LABEL:-${USER}}"
STACK_NAME="ADE-${CDK_ENV_LABEL}-${CDK_USER_LABEL}-Stack"
STOP_MINUTES="${1:-120}"

if [[ -z "${AWS_ACCESS_KEY_ID:-}" ]]; then
    source "$PROJECT_ROOT/setup-claude-bedrock.sh"
fi

# Resolve instance ID
INSTANCE_ID=$(docker run --rm \
  -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  -e AWS_DEFAULT_REGION=us-west-2 \
  --entrypoint aws "$SKYPILOT_IMAGE" \
  cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' --output text)

echo "Instance: $INSTANCE_ID"
echo "Scheduling shutdown in $STOP_MINUTES minutes..."

# Send shutdown command via SSM
export INSTANCE_ID
python3 -c "
import json, os
json.dump({
    'DocumentName': 'AWS-RunShellScript',
    'InstanceIds': [os.environ['INSTANCE_ID']],
    'TimeoutSeconds': 60,
    'Parameters': {'commands': ['sudo shutdown -c 2>/dev/null; sudo shutdown -h +' + os.environ.get('STOP_MINUTES', '120')]}
}, open('/tmp/ssm-cmd.json', 'w'))
"
export STOP_MINUTES

CMD_ID=$(docker run --rm \
  -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  -e AWS_DEFAULT_REGION=us-west-2 \
  -v /tmp/ssm-cmd.json:/tmp/ssm-cmd.json:ro \
  --entrypoint aws "$SKYPILOT_IMAGE" \
  ssm send-command --cli-input-json file:///tmp/ssm-cmd.json \
  --query Command.CommandId --output text)

sleep 3

RESULT=$(docker run --rm \
  -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  -e AWS_DEFAULT_REGION=us-west-2 \
  --entrypoint aws "$SKYPILOT_IMAGE" \
  ssm get-command-invocation \
    --command-id "$CMD_ID" \
    --instance-id "$INSTANCE_ID" \
    --query Status --output text)

echo "Status: $RESULT"
echo "Instance will stop in $STOP_MINUTES minutes."
