# AWS CDK Application Stack - Deployment Scripts

This directory contains deployment automation scripts for the ADEPT Application Stack (ALB + Cognito + WAF).

## Quick Start

```bash
# 1. Copy and configure environment variables
cp .env.example .env
# Edit .env with your AWS account details

# 2. Source environment variables
source .env

# 3. Deploy application stack
./deploy-application-stack.sh

# 4. Register EC2 instances to ALB
./link-ec2-to-alb.sh $CDK_ENV_LABEL $CDK_USER_LABEL $CDK_TARGET_INSTANCE_IDS

# 5. Create Cognito users
python manage-cognito-users.py create $CDK_ENV_LABEL $CDK_USER_LABEL user@example.com

# 6. Validate deployment
./validate-application-stack.sh $CDK_ENV_LABEL $CDK_USER_LABEL
```

## Scripts

### `deploy-application-stack.sh`
Deploys the application stack (ALB, Cognito, WAF, certificates, DNS).

**Usage**:
```bash
export CDK_ENV_LABEL=dev
export CDK_USER_LABEL=alice
export CDK_VPC_ID=vpc-xxxxx
export CDK_WAF_WEBACL_ARN=arn:aws:wafv2:...
export CDK_DOMAIN_NAME=amazonaws.com
export CDK_WAF_ID=waf-abc123

./deploy-application-stack.sh
```

### `link-ec2-to-alb.sh`
Registers EC2 instances to ALB target groups.

**Usage**:
```bash
./link-ec2-to-alb.sh <env> <user> <instance-ids>

# Example:
./link-ec2-to-alb.sh dev alice i-1234567890abcdef0,i-0987654321fedcba0

# Get instance ID from CloudFormation:
INSTANCE_ID=$(aws cloudformation describe-stacks \
  --stack-name ADE-dev-alice-Stack \
  --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" \
  --output text)
./link-ec2-to-alb.sh dev alice $INSTANCE_ID
```

### `manage-cognito-users.py`
Manages Cognito users (create, delete, reset password, list).

**Usage**:
```bash
# Create user
python manage-cognito-users.py create <env> <user> <email>

# List users
python manage-cognito-users.py list <env> <user>

# Reset password
python manage-cognito-users.py reset-password <env> <user> <email>

# Delete user
python manage-cognito-users.py delete <env> <user> <email>

# Show User Pool info
python manage-cognito-users.py info <env> <user>
```

**Dependencies**:
```bash
pip install boto3 click
```

### `validate-application-stack.sh`
Validates deployment (stack status, ALB, targets, Cognito, DNS, WAF).

**Usage**:
```bash
./validate-application-stack.sh <env> <user>

# Example:
./validate-application-stack.sh dev alice
```

## Configuration

### Environment Variables (`.env`)

Required:
- `CDK_ENV_LABEL` - Environment label (e.g., `dev`, `test`, `prod`)
- `CDK_USER_LABEL` - User label (e.g., `alice`, `bob`)
- `CDK_VPC_ID` - VPC ID for deployment
- `CDK_WAF_WEBACL_ARN` - Existing WAF WebACL ARN
- `CDK_DOMAIN_NAME` - Base domain name
- `CDK_WAF_ID` - WAF identifier for DNS

Optional:
- `CDK_TARGET_INSTANCE_IDS` - Comma-separated EC2 instance IDs
- `CDK_ACCOUNT` - AWS account ID (auto-detected if not set)
- `CDK_REGION` - AWS region (defaults to `us-west-2`)

## Prerequisites

1. **Existing Infrastructure**:
   - EC2 instance(s) via `dev_environment_stack`
   - WAF WebACL (created manually)
   - Route53 hosted zone
   - AWS account bootstrapped for CDK

2. **Tools**:
   - AWS CLI configured
   - CDK CLI installed (`npm install -g aws-cdk`)
   - Python 3.10+ with boto3, click

## Architecture

```
Route53 → WAF → Internal ALB (Cognito Auth) → Target Groups → EC2 Instances
                     ↓
              Cognito User Pool
```

**Domain Pattern**:
- `streamlit.ade-{env}-{user}.{waf-id}.{domain}`
- `jupyter.ade-{env}-{user}.{waf-id}.{domain}`

## Documentation

- **Implementation Summary**: `docs/infrastructure/aws-cdk/IMPLEMENTATION_SUMMARY.md`
- **Detailed Plan**: `docs/infrastructure/aws-cdk/APPLICATION_STACK_DETAILED_PLAN.md`

## Troubleshooting

**Certificate validation stuck**: Wait 5-10 minutes for DNS propagation.

**Target health failing**: Verify applications running on ports 8503/8888 and security groups allow ALB traffic.

**Cognito auth loop**: Check callback URLs match ALB DNS exactly.

**WAF association fails**: Verify WAF ARN is correct and in same region as ALB.

## Support

For issues or questions, refer to the detailed documentation in `docs/infrastructure/aws-cdk/`.
