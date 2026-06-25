#!/usr/bin/env python3
import os
import aws_cdk as cdk
from dotenv import load_dotenv

from stacks.cicd_stack import CicdStack
from stacks.eks_stack import EksStack
from aws_cdk import aws_ec2 as ec2

# Load environment variables from .env file
load_dotenv()

app = cdk.App()

# --- Configuration ---
project_name = os.getenv("PROJECT_NAME", "AgenticFramework")
aws_env = cdk.Environment(
    account=os.getenv("AWS_ACCOUNT"),
    region=os.getenv("AWS_REGION")
)

if not all([aws_env.account, aws_env.region]):
    raise ValueError(
        "Please set AWS_ACCOUNT and AWS_REGION in your .env file."
    )

# --- Stack Definitions ---

# 1. CI/CD Stack: Creates ECR repos and the pipeline to build/push images.
cicd_stack = CicdStack(
    app,
    f"{project_name}CicdStack",
    env=aws_env
)

# 2. VPC Stack for EKS
vpc_stack = cdk.Stack(app, f"{project_name}VpcStack", env=aws_env)
vpc = ec2.Vpc(vpc_stack, "EksVpc", max_azs=2)

# 3. EKS Cluster Stack: Deploys the EKS cluster.
EksStack(
    app,
    f"{project_name}EksStack",
    vpc=vpc,
    env=aws_env
)

app.synth()

