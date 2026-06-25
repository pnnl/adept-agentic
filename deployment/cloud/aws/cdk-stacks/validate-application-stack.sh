#!/bin/bash
# Validate ADEPT Application Stack Deployment

ENV_LABEL="$1"
USER_LABEL="$2"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ -z "$ENV_LABEL" ] || [ -z "$USER_LABEL" ]; then
    echo "Usage: $0 <env> <user>"
    echo "Example: $0 dev alice"
    exit 1
fi

STACK_NAME="ADE-${ENV_LABEL}-${USER_LABEL}-App-Stack"

echo "========================================"
echo "  Validating Application Stack"
echo "========================================"
echo "  Stack: ${STACK_NAME}"
echo ""

PASSED=0
FAILED=0
WARNINGS=0

# 1. Check stack status
echo "1. Stack Status:"
STATUS=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].StackStatus" \
    --output text 2>/dev/null)

if [ "$STATUS" = "CREATE_COMPLETE" ] || [ "$STATUS" = "UPDATE_COMPLETE" ]; then
    echo -e "${GREEN}  ✓ Stack deployed successfully: ${STATUS}${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}  ✗ Stack status: ${STATUS}${NC}"
    FAILED=$((FAILED + 1))
fi

# 2. Check ALB
echo ""
echo "2. ALB Status:"
ALB_ARN=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='LoadBalancerArn'].OutputValue" \
    --output text 2>/dev/null)

if [ -z "$ALB_ARN" ]; then
    echo -e "${RED}  ✗ ALB ARN not found in stack outputs${NC}"
    FAILED=$((FAILED + 1))
else
    ALB_STATE=$(aws elbv2 describe-load-balancers \
        --load-balancer-arns "${ALB_ARN}" \
        --query "LoadBalancers[0].State.Code" \
        --output text 2>/dev/null)

    if [ "$ALB_STATE" = "active" ]; then
        echo -e "${GREEN}  ✓ ALB is active${NC}"
        PASSED=$((PASSED + 1))
    else
        echo -e "${YELLOW}  ⚠ ALB state: ${ALB_STATE}${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
fi

# 3. Check target health
echo ""
echo "3. Target Health:"
STREAMLIT_TG_ARN=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='StreamlitTargetGroupArn'].OutputValue" \
    --output text 2>/dev/null)

JUPYTER_TG_ARN=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='JupyterTargetGroupArn'].OutputValue" \
    --output text 2>/dev/null)

if [ -z "$STREAMLIT_TG_ARN" ] || [ -z "$JUPYTER_TG_ARN" ]; then
    echo -e "${RED}  ✗ Target group ARNs not found${NC}"
    FAILED=$((FAILED + 1))
else
    # Check Streamlit targets
    STREAMLIT_HEALTH=$(aws elbv2 describe-target-health \
        --target-group-arn "${STREAMLIT_TG_ARN}" \
        --query "TargetHealthDescriptions[*].TargetHealth.State" \
        --output text 2>/dev/null)

    if echo "$STREAMLIT_HEALTH" | grep -q "healthy"; then
        HEALTHY_COUNT=$(echo "$STREAMLIT_HEALTH" | grep -o "healthy" | wc -l)
        echo -e "${GREEN}  ✓ Streamlit: ${HEALTHY_COUNT} healthy targets${NC}"
        PASSED=$((PASSED + 1))
    elif [ -z "$STREAMLIT_HEALTH" ]; then
        echo -e "${YELLOW}  ⚠ Streamlit: No targets registered${NC}"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "${YELLOW}  ⚠ Streamlit: ${STREAMLIT_HEALTH}${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi

    # Check Jupyter targets
    JUPYTER_HEALTH=$(aws elbv2 describe-target-health \
        --target-group-arn "${JUPYTER_TG_ARN}" \
        --query "TargetHealthDescriptions[*].TargetHealth.State" \
        --output text 2>/dev/null)

    if echo "$JUPYTER_HEALTH" | grep -q "healthy"; then
        HEALTHY_COUNT=$(echo "$JUPYTER_HEALTH" | grep -o "healthy" | wc -l)
        echo -e "${GREEN}  ✓ Jupyter: ${HEALTHY_COUNT} healthy targets${NC}"
        PASSED=$((PASSED + 1))
    elif [ -z "$JUPYTER_HEALTH" ]; then
        echo -e "${YELLOW}  ⚠ Jupyter: No targets registered${NC}"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "${YELLOW}  ⚠ Jupyter: ${JUPYTER_HEALTH}${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
fi

# 4. Check Cognito User Pool
echo ""
echo "4. Cognito User Pool:"
USER_POOL_ID=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" \
    --output text 2>/dev/null)

if [ -z "$USER_POOL_ID" ]; then
    echo -e "${RED}  ✗ User Pool ID not found${NC}"
    FAILED=$((FAILED + 1))
else
    USER_COUNT=$(aws cognito-idp list-users \
        --user-pool-id "${USER_POOL_ID}" \
        --query "length(Users)" \
        --output text 2>/dev/null)

    echo -e "${GREEN}  ✓ User Pool exists (${USER_COUNT} users)${NC}"
    PASSED=$((PASSED + 1))
fi

# 5. Check DNS resolution
echo ""
echo "5. DNS Resolution:"
DEPLOYMENT_ID="ade-${ENV_LABEL}-${USER_LABEL}"
WAF_ID=$(echo "${STACK_NAME}" | grep -oP 'waf-\w+' || echo "")

STREAMLIT_URL=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='StreamlitURL'].OutputValue" \
    --output text 2>/dev/null | sed 's|https://||')

if [ -z "$STREAMLIT_URL" ]; then
    echo -e "${YELLOW}  ⚠ Could not determine Streamlit URL${NC}"
    WARNINGS=$((WARNINGS + 1))
else
    if command -v dig &> /dev/null; then
        RESOLVED=$(dig +short "${STREAMLIT_URL}" | head -1)
        if [ ! -z "$RESOLVED" ]; then
            echo -e "${GREEN}  ✓ DNS resolves: ${STREAMLIT_URL} → ${RESOLVED}${NC}"
            PASSED=$((PASSED + 1))
        else
            echo -e "${YELLOW}  ⚠ DNS does not resolve: ${STREAMLIT_URL}${NC}"
            WARNINGS=$((WARNINGS + 1))
        fi
    else
        echo -e "${YELLOW}  ⚠ 'dig' command not found, skipping DNS check${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
fi

# 6. Check WAF association
echo ""
echo "6. WAF Association:"
WAF_ARN=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='WAFWebACLArn'].OutputValue" \
    --output text 2>/dev/null)

if [ -z "$WAF_ARN" ]; then
    echo -e "${YELLOW}  ⚠ WAF ARN not found in outputs${NC}"
    WARNINGS=$((WARNINGS + 1))
else
    WAF_RESOURCES=$(aws wafv2 list-resources-for-web-acl \
        --web-acl-arn "${WAF_ARN}" \
        --resource-type APPLICATION_LOAD_BALANCER \
        --query "ResourceArns[?contains(@, '${ALB_ARN}')]" \
        --output text 2>/dev/null)

    if [ ! -z "$WAF_RESOURCES" ]; then
        echo -e "${GREEN}  ✓ WAF associated with ALB${NC}"
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}  ✗ WAF not associated with ALB${NC}"
        FAILED=$((FAILED + 1))
    fi
fi

# Summary
echo ""
echo "========================================"
echo "  Validation Summary"
echo "========================================"
echo -e "${GREEN}  Passed: ${PASSED}${NC}"
echo -e "${YELLOW}  Warnings: ${WARNINGS}${NC}"
echo -e "${RED}  Failed: ${FAILED}${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ Validation successful!${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}Note: There are ${WARNINGS} warnings that may require attention.${NC}"
    fi
    exit 0
else
    echo -e "${RED}✗ Validation failed with ${FAILED} errors.${NC}"
    echo "Review the errors above and check the deployment logs."
    exit 1
fi
