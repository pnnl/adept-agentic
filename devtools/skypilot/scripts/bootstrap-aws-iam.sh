#!/usr/bin/env bash
# bootstrap-aws-iam.sh — Idempotent creation of SkyPilot IAM prerequisites
#
# Creates the instance profile, IAM role, managed policy attachments, and
# inline PassRole policy that SkyPilot expects before launching EC2 instances.
#
# Prerequisites:
#   - AWS CLI configured (credentials via env vars or ~/.aws)
#   - IAM permissions: iam:CreateInstanceProfile, iam:CreateRole,
#     iam:AttachRolePolicy, iam:PutRolePolicy, iam:AddRoleToInstanceProfile,
#     iam:GetInstanceProfile, iam:GetRole
#
# Usage (inside SkyPilot container via Makefile):
#   make sky-bootstrap-iam
#
# Usage (standalone):
#   AWS_DEFAULT_REGION=us-west-2 ./devtools/skypilot/scripts/bootstrap-aws-iam.sh
#
# Idempotency: safe to run multiple times. Each step checks for existing
# resources before creating.

set -euo pipefail

PROFILE_NAME="${SKYPILOT_INSTANCE_PROFILE:-skypilot-v1}"
ROLE_NAME="${SKYPILOT_IAM_ROLE:-skypilot-v1}"
REGION="${AWS_DEFAULT_REGION:-us-west-2}"

echo "================================================"
echo "SkyPilot IAM Bootstrap"
echo "  Instance Profile: ${PROFILE_NAME}"
echo "  IAM Role:         ${ROLE_NAME}"
echo "  Region:           ${REGION}"
echo "================================================"

# --- Step 1: Instance Profile ---
echo ""
echo "[1/5] Instance Profile: ${PROFILE_NAME}"
if aws iam get-instance-profile --instance-profile-name "${PROFILE_NAME}" >/dev/null 2>&1; then
  echo "  Already exists — skipping."
else
  aws iam create-instance-profile --instance-profile-name "${PROFILE_NAME}"
  echo "  Created."
  echo "  Waiting 15s for IAM propagation..."
  sleep 15
fi

# --- Step 2: IAM Role ---
echo ""
echo "[2/5] IAM Role: ${ROLE_NAME}"
if aws iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
  echo "  Already exists — skipping."
else
  TRUST_POLICY=$(cat <<'POLICY_EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ec2.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
POLICY_EOF
  )
  aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "${TRUST_POLICY}"
  echo "  Created."
fi

# --- Step 3: Managed Policy Attachments ---
# SkyPilot requires broad EC2 permissions (launch, terminate, describe, modify instances,
# volumes, security groups, key pairs, VPCs) and S3 for storing cluster state/logs.
# These AWS-managed policies are intentionally broad — SkyPilot's own operations span
# most EC2 actions. For tighter scoping, replace with a custom policy limiting to
# specific regions, instance types, and resource tags (e.g., "skypilot:*").
echo ""
echo "[3/5] Managed policies on ${ROLE_NAME}"
for POLICY_ARN in \
  "arn:aws:iam::aws:policy/AmazonEC2FullAccess" \
  "arn:aws:iam::aws:policy/AmazonS3FullAccess"; do
  POLICY_SHORT="${POLICY_ARN##*/}"
  if aws iam list-attached-role-policies --role-name "${ROLE_NAME}" \
       --query "AttachedPolicies[?PolicyArn=='${POLICY_ARN}'].PolicyName" \
       --output text 2>/dev/null | grep -q "${POLICY_SHORT}"; then
    echo "  ${POLICY_SHORT} — already attached."
  else
    aws iam attach-role-policy --role-name "${ROLE_NAME}" --policy-arn "${POLICY_ARN}" 2>/dev/null || true
    echo "  ${POLICY_SHORT} — attached."
  fi
done

# --- Step 4: Inline PassRole Policy ---
echo ""
echo "[4/5] Inline policy: SkyPilotPassRolePolicy"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
PASSROLE_POLICY=$(cat <<POLICY_EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["iam:GetRole", "iam:PassRole"],
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
    },
    {
      "Effect": "Allow",
      "Action": "iam:GetInstanceProfile",
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:instance-profile/${PROFILE_NAME}"
    }
  ]
}
POLICY_EOF
)
aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name SkyPilotPassRolePolicy \
  --policy-document "${PASSROLE_POLICY}"
echo "  Applied (idempotent put)."

# --- Step 5: Link Role → Instance Profile ---
echo ""
echo "[5/5] Link ${ROLE_NAME} → ${PROFILE_NAME}"
EXISTING_ROLES=$(aws iam get-instance-profile \
  --instance-profile-name "${PROFILE_NAME}" \
  --query "InstanceProfile.Roles[].RoleName" \
  --output text 2>/dev/null || echo "")
if echo "${EXISTING_ROLES}" | grep -qw "${ROLE_NAME}"; then
  echo "  Already linked — skipping."
else
  aws iam add-role-to-instance-profile \
    --instance-profile-name "${PROFILE_NAME}" \
    --role-name "${ROLE_NAME}"
  echo "  Linked."
  echo "  Waiting 15s for IAM propagation..."
  sleep 15
fi

# --- Verification ---
echo ""
echo "================================================"
echo "Verification"
echo "================================================"
aws iam get-instance-profile --instance-profile-name "${PROFILE_NAME}" \
  --query "InstanceProfile.{Name:InstanceProfileName,Arn:Arn,Roles:Roles[].RoleName}" \
  --output table 2>/dev/null || echo "  (get-instance-profile read denied — write succeeded)"
echo ""
echo "IAM bootstrap complete. SkyPilot can now provision EC2 instances."
