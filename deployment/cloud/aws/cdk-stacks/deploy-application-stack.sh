#!/bin/bash
# Deploy the ADEPT Application Stack (ALB + Cognito + WAF)

set -e

echo "========================================"
echo "  Deploy ADEPT Application Stack"
echo "========================================"
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check required environment variables
check_env_var() {
    if [ -z "${!1}" ]; then
        echo -e "${RED}Error: $1 is not set${NC}"
        echo ""
        echo "Required environment variables:"
        echo "  export CDK_ENV_LABEL='dev'"
        echo "  export CDK_USER_LABEL='yourname'"
        echo "  export CDK_VPC_ID='vpc-xxxxx'"
        echo "  export CDK_WAF_WEBACL_ARN='arn:aws:wafv2:region:account:regional/webacl/...'"
        echo "  export CDK_DOMAIN_NAME='amazonaws.com'"
        echo "  export CDK_WAF_ID='waf-abc123'"
        echo "  export CDK_TARGET_INSTANCE_IDS='i-xxxxx,i-yyyyy'  # Optional"
        echo ""
        echo "Example:"
        echo "  export CDK_ENV_LABEL=dev"
        echo "  export CDK_USER_LABEL=alice"
        echo "  export CDK_VPC_ID=vpc-099149e2d85e01e4b"
        echo "  export CDK_WAF_WEBACL_ARN=arn:aws:wafv2:us-west-2:123456789012:regional/webacl/example/abc123"
        echo "  export CDK_DOMAIN_NAME=amazonaws.com"
        echo "  export CDK_WAF_ID=waf-abc123"
        exit 1
    fi
}

echo "Checking environment variables..."
check_env_var "CDK_ENV_LABEL"
check_env_var "CDK_USER_LABEL"
check_env_var "CDK_VPC_ID"
check_env_var "CDK_WAF_WEBACL_ARN"
check_env_var "CDK_DOMAIN_NAME"
check_env_var "CDK_WAF_ID"

# AWS Account ID
if [ -z "$CDK_ACCOUNT" ]; then
    CDK_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
    if [ $? -ne 0 ] || [ -z "$CDK_ACCOUNT" ]; then
        echo -e "${RED}Could not determine AWS Account ID${NC}"
        echo "Please ensure AWS CLI is configured and you have valid credentials"
        exit 1
    fi
    export CDK_ACCOUNT
fi

# AWS Region (default to us-west-2 if not set)
if [ -z "$CDK_REGION" ]; then
    CDK_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
    export CDK_REGION
fi

# Change to CDK directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CDK_DIR="${SCRIPT_DIR}/../../../../devtools/aws-cdk"

if [ ! -d "$CDK_DIR" ]; then
    echo -e "${RED}Error: CDK directory not found at $CDK_DIR${NC}"
    exit 1
fi

cd "$CDK_DIR"

# Deploy stack
echo ""
echo -e "${GREEN}Deploying Application Stack...${NC}"
echo "  Environment: ${CDK_ENV_LABEL}"
echo "  User: ${CDK_USER_LABEL}"
echo "  VPC: ${CDK_VPC_ID}"
echo "  Domain: ${CDK_DOMAIN_NAME}"
echo "  WAF ID: ${CDK_WAF_ID}"
echo "  Region: ${CDK_REGION}"
echo "  Account: ${CDK_ACCOUNT}"
echo ""

# Run CDK deploy
cdk deploy \
    -c env="${CDK_ENV_LABEL}" \
    -c user="${CDK_USER_LABEL}" \
    -c deploy_ec2=false \
    -c deploy_app=true \
    -c vpc="${CDK_VPC_ID}" \
    -c waf_arn="${CDK_WAF_WEBACL_ARN}" \
    -c domain_name="${CDK_DOMAIN_NAME}" \
    -c waf_id="${CDK_WAF_ID}" \
    -c account="${CDK_ACCOUNT}" \
    -c region="${CDK_REGION}" \
    --require-approval never

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}========================================"
    echo "  Deployment Successful!"
    echo "========================================${NC}"
    echo ""

    DEPLOYMENT_ID="ade-${CDK_ENV_LABEL}-${CDK_USER_LABEL}"
    STACK_NAME="ADE-${CDK_ENV_LABEL}-${CDK_USER_LABEL}-App-Stack"

    echo "Application URLs:"
    echo "  Streamlit:  https://streamlit.${DEPLOYMENT_ID}.${CDK_WAF_ID}.${CDK_DOMAIN_NAME}"
    echo "  JupyterLab: https://jupyter.${DEPLOYMENT_ID}.${CDK_WAF_ID}.${CDK_DOMAIN_NAME}"
    echo ""
    echo "Next steps:"
    echo "1. Register EC2 instances as ALB targets:"
    echo "   ./link-ec2-to-alb.sh ${CDK_ENV_LABEL} ${CDK_USER_LABEL} <instance-ids>"
    echo ""
    echo "2. Create Cognito users:"
    echo "   python ./manage-cognito-users.py create ${CDK_ENV_LABEL} ${CDK_USER_LABEL} user@example.com"
    echo ""
    echo "3. Validate deployment:"
    echo "   ./validate-application-stack.sh ${CDK_ENV_LABEL} ${CDK_USER_LABEL}"
    echo ""
else
    echo ""
    echo -e "${RED}Deployment failed!${NC}"
    echo "Check the error messages above for details."
    exit 1
fi
