#!/bin/bash
# Run arbitrary command on EC2 instance via SSM.
#
# Usage:
#   ./scripts/cdk-ssm-run.sh "docker ps"
#   ./scripts/cdk-ssm-run.sh 'docker ps --format "{{.Names}}" | wc -l'
#   ./scripts/cdk-ssm-run.sh '#!/bin/bash
#     cd /data/workspace/adept-*
#     docker ps --format "{{.Names}}"
#     echo "Running: $(docker ps -q | wc -l)"'
#
# All shell features work: pipes, $(), backticks, {{.}}, $!, multiline.
# For bash features (arrays, [[), start CMD with #!/bin/bash.
#
# Requires: setup-claude-bedrock.sh sourced (or AWS_* env vars set),
#           adept-skypilot:latest image built.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKYPILOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SKYPILOT_DIR/../.." && pwd)"

SKYPILOT_IMAGE="${SKYPILOT_IMAGE:-adept-skypilot:latest}"
CDK_ENV_LABEL="${CDK_ENV_LABEL:-dev}"
CDK_USER_LABEL="${CDK_USER_LABEL:-${USER}}"
STACK_NAME="ADE-${CDK_ENV_LABEL}-${CDK_USER_LABEL}-Stack"
SSM_WAIT="${SSM_WAIT:-10}"

CMD="${1:-${CMD:-}}"
if [[ -z "$CMD" ]]; then
    echo "ERROR: Command required. Pass as argument or set CMD env var."
    echo "Usage: $0 '<command>'  OR  CMD='...' $0"
    exit 1
fi

# Source AWS credentials if not already set
if [[ -z "${AWS_ACCESS_KEY_ID:-}" ]]; then
    if [[ -f "$PROJECT_ROOT/setup-claude-bedrock.sh" ]]; then
        source "$PROJECT_ROOT/setup-claude-bedrock.sh"
    else
        echo "ERROR: AWS credentials not set and setup-claude-bedrock.sh not found"
        exit 1
    fi
fi

# Resolve instance ID from CloudFormation stack
echo "Target stack: $STACK_NAME (CDK_ENV_LABEL=$CDK_ENV_LABEL, CDK_USER_LABEL=$CDK_USER_LABEL)"
INSTANCE_ID=$(docker run --rm \
    -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    -e AWS_DEFAULT_REGION=us-west-2 \
    --entrypoint aws "$SKYPILOT_IMAGE" \
    cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' --output text)

echo "Instance: $INSTANCE_ID"

# Build SSM command payload as JSON (Python handles all escaping)
export INSTANCE_ID
python3 -c "
import json, os, sys
json.dump({
    'DocumentName': 'AWS-RunShellScript',
    'InstanceIds': [os.environ['INSTANCE_ID']],
    'TimeoutSeconds': 600,
    'Parameters': {'commands': [sys.argv[1]]}
}, open('/tmp/ssm-cmd.json', 'w'))
" "$CMD"

# Send command via SSM
CMD_ID=$(docker run --rm \
    -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    -e AWS_DEFAULT_REGION=us-west-2 \
    -v /tmp/ssm-cmd.json:/tmp/ssm-cmd.json:ro \
    --entrypoint aws "$SKYPILOT_IMAGE" \
    ssm send-command --cli-input-json file:///tmp/ssm-cmd.json \
    --query Command.CommandId --output text)

echo "Command: $CMD_ID"
echo "Waiting ${SSM_WAIT}s for execution..."
sleep "$SSM_WAIT"

# Poll for result
docker run --rm \
    -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    -e AWS_DEFAULT_REGION=us-west-2 \
    --entrypoint aws "$SKYPILOT_IMAGE" \
    ssm get-command-invocation \
      --command-id "$CMD_ID" \
      --instance-id "$INSTANCE_ID" \
      --query '{Status:Status,Output:StandardOutputContent,Errors:StandardErrorContent}' \
      --output table
