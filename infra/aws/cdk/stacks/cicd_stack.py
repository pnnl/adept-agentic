from constructs import Construct
from aws_cdk import (
    Stack,
    aws_ecr as ecr,
    aws_s3 as s3,
    aws_iam as iam,
    aws_codebuild as codebuild,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as codepipeline_actions,
    RemovalPolicy,
)

class CicdStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.services = ["mcp_server", "streamlit_app", "hpc_mcp_server", "sandbox_mcp_server"]
        self.ecr_repos = {}

        # 1. Create ECR repository for each service
        for service_name in self.services:
            repo = ecr.Repository(
                self, f"{service_name}EcrRepo",
                repository_name=f"{service_name.lower()}-repo",
                removal_policy=RemovalPolicy.DESTROY,
                auto_delete_images=True
            )
            self.ecr_repos[service_name] = repo

        # 2. Create S3 bucket for source code
        source_bucket = s3.Bucket(
            self, "SourceCodeBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            versioned=True
        )

        # 3. Create IAM Role for CodeBuild
        codebuild_role = iam.Role(
            self, "CodeBuildRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3ReadOnlyAccess"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEC2ContainerRegistryPowerUser"),
                # Add permissions for CDK deployment
                iam.ManagedPolicy.from_aws_managed_policy_name("AWSCloudFormationFullAccess"),
                iam.ManagedPolicy.from_aws_managed_policy_name("IAMFullAccess"), # Needed for creating task roles
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonECS_FullAccess"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEC2FullAccess"), # For VPC lookups, SG creation
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEFSFullAccess"),
                iam.ManagedPolicy.from_aws_managed_policy_name("elasticloadbalancing-full-access"),
            ]
        )

        # 4. Create CodeBuild Project
        build_project = codebuild.PipelineProject(
            self, "AgenticFrameworkBuild",
            role=codebuild_role,
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,  # Required for Docker-in-Docker builds
                compute_type=codebuild.ComputeType.LARGE,
                environment_variables={
                    "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(value=self.account)
                }
            ),
            # Use an external buildspec file for better maintainability
            build_spec=codebuild.BuildSpec.from_source_filename(
                "infra/aws/cdk/buildspec.yml"
            )
        )

        # 5. Create CodePipeline
        source_output = codepipeline.Artifact()

        codepipeline.Pipeline(
            self, "AgenticFrameworkPipeline",
            pipeline_name="AgenticFramework-Pipeline",
            stages=[
                codepipeline.StageProps(
                    stage_name="Source",
                    actions=[
                        codepipeline_actions.S3SourceAction(
                            action_name="S3_Source",
                            bucket=source_bucket,
                            bucket_key="source.zip", # Expects a zip of the repo
                            output=source_output,
                        )
                    ]
                ),
                codepipeline.StageProps(
                    stage_name="Build-and-Deploy",
                    actions=[
                        codepipeline_actions.CodeBuildAction(
                            action_name="Build_Push_Deploy",
                            project=build_project,
                            input=source_output,
                        )
                    ]
                )
            ]
        )
