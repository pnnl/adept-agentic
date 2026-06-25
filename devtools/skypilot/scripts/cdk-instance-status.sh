#!/bin/bash
# Quick instance state check: running/stopped, SSM ping, Nessus agent status.
# Usage: ./scripts/cdk-instance-status.sh
# Env: CDK_ENV_LABEL (default: dev), CDK_USER_LABEL (default: $USER)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

SKYPILOT_IMAGE="${SKYPILOT_IMAGE:-adept-skypilot:latest}"
CDK_ENV_LABEL="${CDK_ENV_LABEL:-dev}"
CDK_USER_LABEL="${CDK_USER_LABEL:-${USER}}"
STACK_NAME="ADE-${CDK_ENV_LABEL}-${CDK_USER_LABEL}-Stack"

if [[ -z "${AWS_ACCESS_KEY_ID:-}" ]]; then
    source "$PROJECT_ROOT/setup-claude-bedrock.sh"
fi

docker run --rm \
  -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  -e AWS_DEFAULT_REGION=us-west-2 \
  --entrypoint bash "$SKYPILOT_IMAGE" -c "
    STACK_NAME='$STACK_NAME'
    INSTANCE_ID=\$(aws cloudformation describe-stacks --stack-name \$STACK_NAME \
      --query 'Stacks[0].Outputs[?OutputKey==\`InstanceId\`].OutputValue' --output text)
    IP=\$(aws cloudformation describe-stacks --stack-name \$STACK_NAME \
      --query 'Stacks[0].Outputs[?OutputKey==\`PrivateIP\`].OutputValue' --output text)
    STATE=\$(aws ec2 describe-instances --instance-ids \$INSTANCE_ID \
      --query 'Reservations[0].Instances[0].State.Name' --output text)
    SSM=\$(aws ssm describe-instance-information \
      --filters Key=InstanceIds,Values=\$INSTANCE_ID \
      --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo N/A)
    echo \"Stack:    \$STACK_NAME\"
    echo \"Instance: \$INSTANCE_ID\"
    echo \"IP:       \$IP\"
    echo \"State:    \$STATE\"
    echo \"SSM:      \$SSM\"
    if [ \"\$STATE\" = running ] && [ \"\$SSM\" = Online ]; then
      CMD_ID=\$(aws ssm send-command \
        --instance-ids \$INSTANCE_ID \
        --document-name AWS-RunShellScript \
        --parameters commands=['systemctl is-active nessusagent 2>/dev/null || echo not-found'] \
        --query Command.CommandId --output text)
      sleep 3
      NESSUS=\$(aws ssm get-command-invocation \
        --command-id \$CMD_ID \
        --instance-id \$INSTANCE_ID \
        --query StandardOutputContent --output text | tr -d '\n')
      echo \"Nessus:   \$NESSUS\"
    fi
  "
