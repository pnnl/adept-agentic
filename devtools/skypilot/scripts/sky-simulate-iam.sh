#!/bin/bash
# Simulate IAM policy evaluation for SkyPilot-required actions (no state changes).
# Tests IAM, EC2, and S3 action permissions for the current user.
# Usage: ./scripts/sky-simulate-iam.sh
# Env: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (or sources setup-claude-bedrock.sh)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

SKYPILOT_IMAGE="${SKYPILOT_IMAGE:-adept-skypilot:latest}"

if [[ -z "${AWS_ACCESS_KEY_ID:-}" ]]; then
    source "$PROJECT_ROOT/setup-claude-bedrock.sh"
fi

AWS_DOCKER="docker run --rm \
  -e AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID \
  -e AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY \
  -e AWS_DEFAULT_REGION=us-west-2 \
  --entrypoint aws $SKYPILOT_IMAGE"

USER_ARN=$($AWS_DOCKER sts get-caller-identity --query Arn --output text)
echo "User ARN: $USER_ARN"
echo ""

echo "=== IAM Actions (instance profile, role management) ==="
$AWS_DOCKER iam simulate-principal-policy \
  --policy-source-arn "$USER_ARN" \
  --action-names \
    iam:CreateRole iam:CreateInstanceProfile iam:AddRoleToInstanceProfile \
    iam:AttachRolePolicy iam:PutRolePolicy iam:PassRole iam:GetRole \
    iam:GetInstanceProfile iam:ListAttachedRolePolicies iam:ListInstanceProfiles \
    iam:TagRole iam:TagInstanceProfile \
  --query 'EvaluationResults[*].{Action:EvalActionName,Decision:EvalDecision}' \
  --output table

echo ""
echo "=== EC2 Actions (launch, networking, tags) ==="
$AWS_DOCKER iam simulate-principal-policy \
  --policy-source-arn "$USER_ARN" \
  --action-names \
    ec2:RunInstances ec2:DescribeInstances ec2:TerminateInstances \
    ec2:CreateSecurityGroup ec2:AuthorizeSecurityGroupIngress \
    ec2:DeleteSecurityGroup ec2:DescribeSecurityGroups \
    ec2:CreateTags ec2:DescribeVpcs ec2:DescribeSubnets \
    ec2:DescribeImages ec2:CreateKeyPair ec2:DeleteKeyPair \
    ec2:StartInstances ec2:StopInstances \
  --query 'EvaluationResults[*].{Action:EvalActionName,Decision:EvalDecision}' \
  --output table

echo ""
echo "=== S3 Actions (SkyPilot file mounts, logs) ==="
$AWS_DOCKER iam simulate-principal-policy \
  --policy-source-arn "$USER_ARN" \
  --action-names \
    s3:CreateBucket s3:PutObject s3:GetObject s3:DeleteObject \
    s3:ListBucket s3:DeleteBucket \
  --query 'EvaluationResults[*].{Action:EvalActionName,Decision:EvalDecision}' \
  --output table

echo ""
echo "Note: simulate-principal-policy does not evaluate AWS Organizations SCPs."
echo "Use 'make sky-dry-run' for a real EC2 dry-run that includes SCP evaluation."
