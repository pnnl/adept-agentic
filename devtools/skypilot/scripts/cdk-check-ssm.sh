#!/bin/bash
# Check SSM connectivity: instance status, agent version, test command.
# Usage: ./scripts/cdk-check-ssm.sh
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
    echo \"Instance: \$INSTANCE_ID\"
    echo '--- Instance Status ---'
    aws ec2 describe-instance-status --instance-ids \$INSTANCE_ID \
      --query 'InstanceStatuses[0].{State:InstanceState.Name,SystemStatus:SystemStatus.Status,InstanceStatus:InstanceStatus.Status}' \
      --output table
    echo '--- SSM Agent Status ---'
    aws ssm describe-instance-information \
      --filters Key=InstanceIds,Values=\$INSTANCE_ID \
      --query 'InstanceInformationList[0].{PingStatus:PingStatus,AgentVersion:AgentVersion,PlatformName:PlatformName,PlatformVersion:PlatformVersion,IPAddress:IPAddress}' \
      --output table
    echo '--- SSM Send-Command Test (hostname) ---'
    CMD_ID=\$(aws ssm send-command \
      --instance-ids \$INSTANCE_ID \
      --document-name AWS-RunShellScript \
      --parameters commands=['hostname && uname -a && df -h /data'] \
      --query Command.CommandId --output text)
    sleep 5
    aws ssm get-command-invocation \
      --command-id \$CMD_ID \
      --instance-id \$INSTANCE_ID \
      --query '{Status:Status,Output:StandardOutputContent}' \
      --output table
  "
