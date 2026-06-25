from constructs import Construct
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_eks as eks,
    aws_iam as iam,
    CfnOutput
)

class EksStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.IVpc, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 1. EKS Cluster IAM Role
        eks_cluster_role = iam.Role(
            self, "EksClusterRole",
            assumed_by=iam.ServicePrincipal("eks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEKSClusterPolicy")
            ]
        )

        # 2. EKS Node Group IAM Role
        eks_node_role = iam.Role(
            self, "EksNodeRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEKSWorkerNodePolicy"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEC2ContainerRegistryReadOnly"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEKS_CNI_Policy")
            ]
        )

        # 3. Create the EKS Cluster
        cluster = eks.Cluster(
            self, "AgenticEksCluster",
            vpc=vpc,
            cluster_name="agentic-framework-cluster",
            masters_role=eks_cluster_role,
            default_capacity_instance=ec2.InstanceType("t3.large"),
            default_capacity=2,
            version=eks.KubernetesVersion.V1_28
        )

        # Add the node group with the specified role
        cluster.add_nodegroup_capacity(
            "custom-nodegroup",
            instance_types=[ec2.InstanceType("t3.large")],
            min_size=2,
            max_size=4,
            node_role=eks_node_role
        )

        # 4. Output the cluster details
        CfnOutput(self, "EksClusterName", value=cluster.cluster_name)
        CfnOutput(self, "EksClusterEndpoint", value=cluster.cluster_endpoint)
        CfnOutput(self, "EksClusterArn", value=cluster.cluster_arn)
        CfnOutput(self, "EksClusterConfigCommand", value=f"aws eks update-kubeconfig --name {cluster.cluster_name} --region {self.region}")
