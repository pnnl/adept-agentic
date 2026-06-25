# Agentic Framework - AWS CDK Deployment

This directory contains the AWS Cloud Development Kit (CDK) application for deploying the Agentic Framework's infrastructure and CI/CD pipeline to AWS.

## Architecture

This CDK application provisions the following AWS resources:

1.  **Base Infrastructure (`BaseInfraStack`)**:
    *   **Amazon ECR Repositories**: Private container registries for each service.
    *   **Amazon VPC**: A new Virtual Private Cloud to host the application securely.
    *   **Amazon EKS Cluster**: A managed Kubernetes cluster to run the application.

2.  **CI/CD Pipeline (`CicdStack`)**:
    *   **AWS CodePipeline**: Orchestrates the build and deploy process.
    *   **AWS S3 Bucket**: Stores the source code artifact for the pipeline.
    *   **AWS CodeBuild**: A build project responsible for:
        *   Building the Docker images for all services.
        *   Pushing the images to their respective ECR repositories.
        *   Deploying the application stack to EKS using Helm.

## Prerequisites

1.  **Git**: For cloning the source code repository.
2.  **AWS CLI**: Configured with credentials for your target AWS account.
3.  **AWS CDK CLI**: The command-line tool for AWS CDK.
4.  **Node.js**: Required by the AWS CDK.
5.  **Python**: Version 3.11 or higher.
6.  **Docker Desktop**: Must be running for the CI/CD pipeline's build stage.
7.  **Helm**: The Kubernetes package manager.

## Deployment Steps

### 1. Setup Python Virtual Environment

From the project root directory, set up a Python virtual environment for the CDK project.

    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r infra/aws/cdk/requirements.txt
    ```

### 2. Bootstrap CDK

If this is your first time using CDK in this AWS account/region, you need to bootstrap it.

    ```bash
    cd infra/aws/cdk
    cdk bootstrap
    ```

### 3. Deploy the Infrastructure and Pipeline

Deploy the CDK stacks. This will provision the ECR repositories, the EKS cluster, and the CodePipeline CI/CD workflow.

    ```bash
    cdk deploy --all --require-approval never
    ```

### 4. Trigger the Pipeline

The pipeline is configured to start when a `source.zip` file is uploaded to the S3 source bucket.

1.  Create a zip archive of the project root.
2.  Upload this `source.zip` to the S3 bucket created by the `CicdStack`. You can find the bucket name in the AWS S3 console.

This will trigger the pipeline, which will build the Docker images, push them to ECR, and deploy the application to your EKS cluster using the `agentic-framework-aws` Helm chart.

### 5. Cleaning Up

To remove all resources created by the CDK, run the destroy command from the `infra/aws/cdk` directory.

    ```bash
    cdk destroy --all
    ```
