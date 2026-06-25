#!/bin/bash
# Register EC2 instances to ALB target groups (Streamlit and JupyterLab)

set -e

ENV_LABEL="$1"
USER_LABEL="$2"
INSTANCE_IDS="$3"  # Comma-separated

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ -z "$ENV_LABEL" ] || [ -z "$USER_LABEL" ] || [ -z "$INSTANCE_IDS" ]; then
    echo -e "${RED}Usage: $0 <env> <user> <instance-ids>${NC}"
    echo ""
    echo "Example:"
    echo "  $0 dev alice i-1234567890abcdef0,i-0987654321fedcba0"
    echo ""
    echo "Or get instance ID from EC2 stack:"
    echo "  INSTANCE_ID=\$(aws cloudformation describe-stacks \\"
    echo "    --stack-name ADE-dev-alice-Stack \\"
    echo "    --query \"Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue\" \\"
    echo "    --output text)"
    echo "  $0 dev alice \$INSTANCE_ID"
    exit 1
fi

STACK_NAME="ADE-${ENV_LABEL}-${USER_LABEL}-App-Stack"

echo "========================================"
echo "  Register EC2 Instances to ALB"
echo "========================================"
echo "  Stack: ${STACK_NAME}"
echo "  Instances: ${INSTANCE_IDS}"
echo ""

# Get target group ARNs from CloudFormation outputs
echo "Fetching target group ARNs..."

STREAMLIT_TG_ARN=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='StreamlitTargetGroupArn'].OutputValue" \
    --output text 2>/dev/null)

JUPYTER_TG_ARN=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='JupyterTargetGroupArn'].OutputValue" \
    --output text 2>/dev/null)

if [ -z "$STREAMLIT_TG_ARN" ] || [ -z "$JUPYTER_TG_ARN" ]; then
    echo -e "${RED}Error: Could not fetch target group ARNs from stack ${STACK_NAME}${NC}"
    echo "Ensure the application stack is deployed successfully."
    exit 1
fi

echo "  Streamlit TG: ${STREAMLIT_TG_ARN:0:60}..."
echo "  Jupyter TG:   ${JUPYTER_TG_ARN:0:60}..."
echo ""

# Register instances
IFS=',' read -ra INSTANCES <<< "$INSTANCE_IDS"
FAILED=0

for INSTANCE_ID in "${INSTANCES[@]}"; do
    INSTANCE_ID=$(echo "$INSTANCE_ID" | xargs)  # Trim whitespace

    if [ -z "$INSTANCE_ID" ]; then
        continue
    fi

    echo "Processing ${INSTANCE_ID}..."

    # Get private IP
    PRIVATE_IP=$(aws ec2 describe-instances \
        --instance-ids "${INSTANCE_ID}" \
        --query "Reservations[0].Instances[0].PrivateIpAddress" \
        --output text 2>/dev/null)

    if [ -z "$PRIVATE_IP" ] || [ "$PRIVATE_IP" = "None" ]; then
        echo -e "${RED}  ✗ Could not find instance ${INSTANCE_ID}${NC}"
        FAILED=$((FAILED + 1))
        continue
    fi

    # Check instance state
    INSTANCE_STATE=$(aws ec2 describe-instances \
        --instance-ids "${INSTANCE_ID}" \
        --query "Reservations[0].Instances[0].State.Name" \
        --output text 2>/dev/null)

    if [ "$INSTANCE_STATE" != "running" ]; then
        echo -e "${YELLOW}  ⚠ Warning: Instance ${INSTANCE_ID} is not running (state: ${INSTANCE_STATE})${NC}"
    fi

    # Register to Streamlit target group
    aws elbv2 register-targets \
        --target-group-arn "${STREAMLIT_TG_ARN}" \
        --targets Id="${INSTANCE_ID}" 2>/dev/null

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  ✓ Registered to Streamlit TG${NC}"
    else
        echo -e "${RED}  ✗ Failed to register to Streamlit TG${NC}"
        FAILED=$((FAILED + 1))
    fi

    # Register to JupyterLab target group
    aws elbv2 register-targets \
        --target-group-arn "${JUPYTER_TG_ARN}" \
        --targets Id="${INSTANCE_ID}" 2>/dev/null

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  ✓ Registered to Jupyter TG${NC}"
    else
        echo -e "${RED}  ✗ Failed to register to Jupyter TG${NC}"
        FAILED=$((FAILED + 1))
    fi

    echo "  Private IP: ${PRIVATE_IP}"
    echo ""
done

# Show target health
echo "========================================"
echo "  Target Health Status"
echo "========================================"
echo ""

echo "Streamlit Target Group:"
aws elbv2 describe-target-health \
    --target-group-arn "${STREAMLIT_TG_ARN}" \
    --query "TargetHealthDescriptions[*].[Target.Id,TargetHealth.State,TargetHealth.Description]" \
    --output table

echo ""
echo "JupyterLab Target Group:"
aws elbv2 describe-target-health \
    --target-group-arn "${JUPYTER_TG_ARN}" \
    --query "TargetHealthDescriptions[*].[Target.Id,TargetHealth.State,TargetHealth.Description]" \
    --output table

echo ""
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}Registration complete!${NC}"
    echo ""
    echo "Note: Targets may take 1-2 minutes to become healthy."
    echo "Check health status with:"
    echo "  aws elbv2 describe-target-health --target-group-arn ${STREAMLIT_TG_ARN}"
else
    echo -e "${YELLOW}Registration completed with ${FAILED} failures.${NC}"
    echo "Check the errors above for details."
    exit 1
fi
