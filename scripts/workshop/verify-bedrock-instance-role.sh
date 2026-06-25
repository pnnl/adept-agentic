#!/bin/bash
# Verification Script: AWS Bedrock Access via EC2 Instance IAM Role
#
# Purpose: Comprehensive verification that Claude Code CLI can authenticate
#          to AWS Bedrock using EC2 instance IAM roles (no API keys needed)
#
# Usage:
#   # On EC2 instance (via SSH):
#   ./scripts/workshop/verify-bedrock-instance-role.sh
#
#   # From orchestrator (via SSM Session Manager):
#   aws ssm start-session --target i-1234567890abcdef0
#   bash /data/workspace/adept-agentic-framework-extended/scripts/workshop/verify-bedrock-instance-role.sh
#
# Exit codes:
#   0 - All checks passed
#   1 - IMDSv2 not accessible
#   2 - Instance role not attached
#   3 - AWS credentials not available
#   4 - Bedrock API access denied
#   5 - LiteLLM authentication failed
#   6 - Claude Code CLI failed

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
AWS_REGION="${AWS_REGION_NAME:-us-west-2}"
TEST_MODEL="anthropic.claude-3-5-sonnet-20241022-v2:0"
CODING_AGENT_MODEL="${CODING_AGENT_DEFAULT_MODEL:-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0}"
WORKSPACE_DIR="/data/workspace/adept-agentic-framework-extended"

# Output helpers
print_header() {
    echo ""
    echo -e "${BLUE}========================================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================================================${NC}"
    echo ""
}

print_step() {
    echo -e "${BLUE}[Step $1/$2]${NC} $3"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ ERROR: $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  WARNING: $1${NC}"
}

print_info() {
    echo -e "   $1"
}

# Check if running on EC2 instance
check_ec2_environment() {
    if ! curl -s -m 2 http://169.254.169.254/latest/meta-data/instance-id &>/dev/null; then
        print_error "Not running on an EC2 instance (metadata service not accessible)"
        print_info "This script must run on an EC2 instance with IMDSv2 enabled"
        return 1
    fi
    return 0
}

# Test 1: Verify IMDSv2 accessibility
test_imdsv2_access() {
    print_step 1 7 "Verifying EC2 Instance Metadata Service v2 (IMDSv2) accessibility"

    # Get IMDSv2 token
    local token
    if ! token=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
        -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" \
        --max-time 2); then
        print_error "Cannot obtain IMDSv2 token (metadata service not accessible)"
        print_info "Troubleshooting:"
        print_info "  1. Verify instance has IMDSv2 enabled"
        print_info "  2. Check security group allows outbound to 169.254.169.254"
        print_info "  3. Verify no network ACLs blocking metadata service"
        return 1
    fi

    # Get instance ID using token
    local instance_id
    if ! instance_id=$(curl -s -H "X-aws-ec2-metadata-token: $token" \
        http://169.254.169.254/latest/meta-data/instance-id \
        --max-time 2); then
        print_error "Cannot retrieve instance ID from metadata service"
        return 1
    fi

    print_success "IMDSv2 accessible"
    print_info "Instance ID: $instance_id"

    export IMDSV2_TOKEN="$token"
    export INSTANCE_ID="$instance_id"
    return 0
}

# Test 2: Verify instance IAM role attachment
test_instance_role_attachment() {
    print_step 2 7 "Verifying IAM role attachment to EC2 instance"

    # Get IAM role info from metadata
    local iam_info
    if ! iam_info=$(curl -s -H "X-aws-ec2-metadata-token: $IMDSV2_TOKEN" \
        http://169.254.169.254/latest/meta-data/iam/info \
        --max-time 2); then
        print_error "Instance does not have IAM role attached"
        print_info "Troubleshooting:"
        print_info "  1. Update CDK stack to attach IAM role:"
        print_info "     role=bedrock_role in ec2.Instance()"
        print_info "  2. Redeploy CloudFormation stack"
        print_info "  3. Verify stack outputs include InstanceRoleArn"
        return 2
    fi

    # Parse role ARN
    local role_arn
    role_arn=$(echo "$iam_info" | jq -r '.InstanceProfileArn // empty')

    if [[ -z "$role_arn" ]]; then
        print_error "Cannot parse instance profile ARN from metadata"
        print_info "Metadata response: $iam_info"
        return 2
    fi

    print_success "IAM role attached"
    print_info "Instance Profile ARN: $role_arn"

    # Get role name from metadata
    local role_name
    if role_name=$(curl -s -H "X-aws-ec2-metadata-token: $IMDSV2_TOKEN" \
        http://169.254.169.254/latest/meta-data/iam/security-credentials/ \
        --max-time 2); then
        print_info "IAM Role Name: $role_name"
        export IAM_ROLE_NAME="$role_name"
    fi

    return 0
}

# Test 3: Verify AWS credentials are available via boto3
test_aws_credentials() {
    print_step 3 7 "Verifying AWS credentials are available to boto3/AWS CLI"

    # Check if AWS CLI is installed
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI not installed"
        print_info "Install: sudo apt-get install -y awscli"
        return 3
    fi

    # Verify credentials work
    local caller_identity
    if ! caller_identity=$(aws sts get-caller-identity --region "$AWS_REGION" 2>&1); then
        print_error "Cannot authenticate with AWS"
        print_info "Error: $caller_identity"
        print_info "Troubleshooting:"
        print_info "  1. Verify IAM role is attached (see Test 2)"
        print_info "  2. Check if AWS_ACCESS_KEY_ID is set (should be unset):"
        print_info "     env | grep AWS_ACCESS_KEY_ID"
        print_info "  3. If set, unset it to use instance role:"
        print_info "     unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY"
        return 3
    fi

    # Parse caller identity
    local role_arn account_id user_id
    role_arn=$(echo "$caller_identity" | jq -r '.Arn')
    account_id=$(echo "$caller_identity" | jq -r '.Account')
    user_id=$(echo "$caller_identity" | jq -r '.UserId')

    print_success "AWS credentials available"
    print_info "Role ARN: $role_arn"
    print_info "Account ID: $account_id"
    print_info "User ID: $user_id"

    # Verify credentials are from assumed role (not API keys)
    if [[ "$role_arn" == *"assumed-role"* ]]; then
        print_success "Using temporary credentials from instance IAM role (correct)"
    else
        print_warning "Using non-instance-role credentials"
        print_info "Expected: assumed-role/ade-*-bedrock-instance-role/*"
        print_info "Actual: $role_arn"
        print_info "This may indicate AWS_ACCESS_KEY_ID is set in environment"
    fi

    export ROLE_ARN="$role_arn"
    return 0
}

# Test 4: Verify Bedrock API access
test_bedrock_api_access() {
    print_step 4 7 "Verifying AWS Bedrock API access"

    # List Bedrock foundation models
    local models
    if ! models=$(aws bedrock list-foundation-models \
        --region "$AWS_REGION" \
        --max-items 5 \
        --output json 2>&1); then
        print_error "Cannot access Bedrock API"
        print_info "Error: $models"
        print_info "Troubleshooting:"
        print_info "  1. Verify IAM role has Bedrock permissions:"
        print_info "     aws iam list-attached-role-policies --role-name \$IAM_ROLE_NAME"
        print_info "  2. Expected policy: AmazonBedrockFullAccess or custom Bedrock policy"
        print_info "  3. Attach policy if missing:"
        print_info "     aws iam attach-role-policy \\"
        print_info "       --role-name \$IAM_ROLE_NAME \\"
        print_info "       --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess"
        return 4
    fi

    # Count Claude models
    local claude_count
    claude_count=$(echo "$models" | jq '[.modelSummaries[] | select(.modelId | contains("claude"))] | length')

    print_success "Bedrock API access confirmed"
    print_info "Found $claude_count Claude models available"

    # Display first 3 Claude models
    echo "$models" | jq -r '.modelSummaries[] | select(.modelId | contains("claude")) | .modelId' | head -3 | while read -r model_id; do
        print_info "  - $model_id"
    done

    return 0
}

# Test 5: Verify LiteLLM can authenticate with instance role
test_litellm_authentication() {
    print_step 5 7 "Verifying LiteLLM can authenticate with instance role credentials"

    # Check if Python 3 is available
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 not installed"
        return 5
    fi

    # Create temporary test script
    local test_script="/tmp/test_litellm_bedrock_$$.py"
    cat > "$test_script" << 'PYTHON_EOF'
import sys
import os

# Only set region, no API keys (force boto3 to use instance role)
os.environ['AWS_REGION_NAME'] = os.getenv('AWS_REGION', 'us-west-2')

# Remove any API keys from environment (ensure instance role is used)
for key in ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN']:
    os.environ.pop(key, None)

try:
    import litellm

    # Test LiteLLM with Bedrock (should auto-discover instance role credentials)
    response = litellm.completion(
        model=os.getenv('TEST_MODEL', 'bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0'),
        messages=[{
            "role": "user",
            "content": "Respond with exactly: 'Instance role authentication successful'"
        }],
        max_tokens=50,
        timeout=30
    )

    content = response.choices[0].message.content.strip()
    print(f"SUCCESS:{content}")
    sys.exit(0)

except ImportError as e:
    print(f"ERROR:LiteLLM not installed - {e}")
    sys.exit(5)
except Exception as e:
    print(f"ERROR:{e}")
    sys.exit(5)
PYTHON_EOF

    # Run LiteLLM test
    local output
    if output=$(AWS_REGION="$AWS_REGION" TEST_MODEL="bedrock/$TEST_MODEL" python3 "$test_script" 2>&1); then
        if [[ "$output" == SUCCESS:* ]]; then
            local response_content="${output#SUCCESS:}"
            print_success "LiteLLM authentication successful"
            print_info "Model response: $response_content"
            rm -f "$test_script"
            return 0
        else
            print_error "LiteLLM test failed: $output"
            rm -f "$test_script"
            return 5
        fi
    else
        print_error "LiteLLM authentication failed"
        print_info "Error: $output"
        print_info "Troubleshooting:"
        print_info "  1. Verify litellm is installed: pip3 list | grep litellm"
        print_info "  2. Install if missing: pip3 install litellm"
        print_info "  3. Check boto3 version: pip3 show boto3"
        rm -f "$test_script"
        return 5
    fi
}

# Test 6: Verify Claude Code CLI can authenticate
test_claude_code_cli() {
    print_step 6 7 "Verifying Claude Code CLI can authenticate with Bedrock"

    # Check if claude-code is installed
    if ! command -v claude-code &> /dev/null; then
        print_warning "Claude Code CLI not installed (optional)"
        print_info "Install: npm install -g @anthropic-ai/claude-code"
        print_info "Skipping CLI test"
        return 0
    fi

    # Test Claude Code CLI with non-interactive prompt
    local cli_test_output="/tmp/claude_code_test_$$.txt"

    print_info "Testing Claude Code CLI (this may take 10-15 seconds)..."

    # Create test prompt file
    echo "Test instance role authentication. Respond with: Authentication successful" > /tmp/claude_prompt_$$.txt

    # Run Claude Code with timeout
    if timeout 30 claude-code \
        --model "$CODING_AGENT_MODEL" \
        --prompt-file /tmp/claude_prompt_$$.txt \
        > "$cli_test_output" 2>&1; then

        print_success "Claude Code CLI authentication successful"
        print_info "CLI output: $(head -1 "$cli_test_output")"
        rm -f "$cli_test_output" /tmp/claude_prompt_$$.txt
        return 0
    else
        local exit_code=$?
        if [[ $exit_code -eq 124 ]]; then
            print_warning "Claude Code CLI test timed out (may indicate network issues)"
        else
            print_error "Claude Code CLI test failed (exit code: $exit_code)"
            print_info "Output: $(cat "$cli_test_output")"
        fi
        rm -f "$cli_test_output" /tmp/claude_prompt_$$.txt
        return 6
    fi
}

# Test 7: Verify environment configuration
test_environment_config() {
    print_step 7 7 "Verifying environment configuration (.env file)"

    local env_file="$WORKSPACE_DIR/.env"

    if [[ ! -f "$env_file" ]]; then
        print_warning ".env file not found at $env_file"
        print_info "Skipping environment configuration check"
        return 0
    fi

    # Check if AWS_ACCESS_KEY_ID is set in .env (should NOT be set)
    if grep -q "^AWS_ACCESS_KEY_ID=" "$env_file"; then
        print_warning "AWS_ACCESS_KEY_ID found in .env file"
        print_info "For instance role authentication, remove AWS_ACCESS_KEY_ID from .env"
        print_info "boto3 will use instance role credentials automatically"
    else
        print_success ".env file does not set AWS_ACCESS_KEY_ID (correct)"
    fi

    # Check if AWS_REGION_NAME is set
    if grep -q "^AWS_REGION_NAME=" "$env_file"; then
        local region_value
        region_value=$(grep "^AWS_REGION_NAME=" "$env_file" | cut -d'=' -f2)
        print_success "AWS_REGION_NAME set to: $region_value"
    else
        print_warning "AWS_REGION_NAME not set in .env file"
        print_info "Add: AWS_REGION_NAME=$AWS_REGION"
    fi

    # Check if CODING_AGENT_DEFAULT_MODEL is set
    if grep -q "^CODING_AGENT_DEFAULT_MODEL=" "$env_file"; then
        local model_value
        model_value=$(grep "^CODING_AGENT_DEFAULT_MODEL=" "$env_file" | cut -d'=' -f2)
        print_success "CODING_AGENT_DEFAULT_MODEL set to: $model_value"
    else
        print_warning "CODING_AGENT_DEFAULT_MODEL not set in .env file"
        print_info "Add: CODING_AGENT_DEFAULT_MODEL=$CODING_AGENT_MODEL"
    fi

    return 0
}

# Generate summary report
generate_summary() {
    local total_tests=7
    local passed_tests=$1
    local failed_tests=$((total_tests - passed_tests))

    print_header "Verification Summary"

    echo -e "Total Tests: $total_tests"
    echo -e "${GREEN}Passed: $passed_tests${NC}"

    if [[ $failed_tests -gt 0 ]]; then
        echo -e "${RED}Failed: $failed_tests${NC}"
    else
        echo -e "Failed: 0"
    fi

    echo ""

    if [[ $failed_tests -eq 0 ]]; then
        print_success "All verification checks passed!"
        echo ""
        print_info "Claude Code CLI is ready to use AWS Bedrock via instance IAM role"
        print_info "Usage: claude-code --model $CODING_AGENT_MODEL"
        echo ""
        print_info "No API keys needed - credentials managed by EC2 instance IAM role"
        print_info "Role ARN: $ROLE_ARN"
        echo ""
        return 0
    else
        print_error "Some verification checks failed"
        echo ""
        print_info "Review error messages above for troubleshooting steps"
        print_info "Common issues:"
        print_info "  1. IAM role not attached to EC2 instance"
        print_info "  2. IAM role missing Bedrock permissions"
        print_info "  3. AWS_ACCESS_KEY_ID set in environment (overrides instance role)"
        echo ""
        return 1
    fi
}

# Main execution
main() {
    print_header "AWS Bedrock Instance Role Authentication Verification"

    echo "This script verifies that Claude Code CLI can authenticate to AWS Bedrock"
    echo "using EC2 instance IAM roles (no long-term API keys required)."
    echo ""
    echo "Configuration:"
    print_info "AWS Region: $AWS_REGION"
    print_info "Test Model: $TEST_MODEL"
    print_info "Coding Agent Model: $CODING_AGENT_MODEL"
    echo ""

    local passed=0
    local total=7

    # Pre-flight check
    if ! check_ec2_environment; then
        print_error "Not running on EC2 instance - cannot verify instance role authentication"
        exit 1
    fi

    # Run all tests
    if test_imdsv2_access; then ((passed++)); fi
    if test_instance_role_attachment; then ((passed++)); fi
    if test_aws_credentials; then ((passed++)); fi
    if test_bedrock_api_access; then ((passed++)); fi
    if test_litellm_authentication; then ((passed++)); fi
    if test_claude_code_cli; then ((passed++)); fi
    if test_environment_config; then ((passed++)); fi

    # Generate summary
    generate_summary "$passed"

    # Return appropriate exit code
    if [[ $passed -eq $total ]]; then
        exit 0
    else
        exit 1
    fi
}

# Run main function
main "$@"
