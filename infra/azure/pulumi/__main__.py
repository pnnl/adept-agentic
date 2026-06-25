import pulumi
import pulumi_azure_native as azure_native
from pulumi_azure_native import resources, containerservice, authorization

# --- Configuration ---
config = pulumi.Config()

# --- Resource Group ---
resource_group = resources.ResourceGroup("agentic-rg")

# --- Azure Container Registry (ACR) ---
container_registry = azure_native.containerregistry.Registry("agenticAcr",
    resource_group_name=resource_group.name,
    sku=azure_native.containerregistry.SkuArgs(name="Basic"),
    admin_user_enabled=True,
)

# --- AKS Cluster ---

# Create a system-assigned managed identity for the AKS cluster
aks_identity = azure_native.managedidentity.UserAssignedIdentity("aksIdentity",
    resource_group_name=resource_group.name,
)

# Grant the AKS identity the AcrPull role on the container registry
# This allows nodes in the AKS cluster to pull images from ACR
acr_pull_assignment = authorization.RoleAssignment("acrPullAssignment",
    principal_id=aks_identity.principal_id,
    principal_type=authorization.PrincipalType.SERVICE_PRINCIPAL,
    role_definition_id=pulumi.Output.concat(
        "/subscriptions/", authorization.get_subscription().subscription_id,
        "/providers/Microsoft.Authorization/roleDefinitions/7f951a00-0792-461c-b1e5-72e06c714de2" # AcrPull role
    ),
    scope=container_registry.id,
)

aks_cluster = containerservice.ManagedCluster("agenticAksCluster",
    resource_group_name=resource_group.name,
    # Define the cluster properties
    agent_pool_profiles=[{
        "count": 2,  # Number of nodes
        "max_pods": 110,
        "mode": "System",
        "name": "agentpool",
        "os_disk_size_gb": 30,
        "os_type": "Linux",
        "type": "VirtualMachineScaleSets",
        "vm_size": "Standard_DS2_v2",
    }],
    dns_prefix=resource_group.name,
    enable_rbac=True,
    kubernetes_version="1.28.5",
    # Assign the managed identity to the cluster
    identity=containerservice.ManagedClusterIdentityArgs(
        type=containerservice.ResourceIdentityType.USER_ASSIGNED,
        user_assigned_identities={
            aks_identity.id: {},
        },
    ),
    # Ensure the role assignment is created before the cluster
    opts=pulumi.ResourceOptions(depends_on=[acr_pull_assignment]),
)

# --- Detailed Implementation Plan ---
# This section outlines the additional Azure resources provisioned by Pulumi
# to support the comprehensive DevOps strategy for the Agentic Framework on AKS.

# 1. Azure Key Vault Provisioning
# Purpose: Securely store sensitive information (API keys, database credentials, Keycloak admin secrets).
key_vault = azure_native.keyvault.Vault("agenticKeyVault",
    resource_group_name=resource_group.name,
    location=resource_group.location,
    properties=azure_native.keyvault.VaultPropertiesArgs(
        sku=azure_native.keyvault.SkuArgs(
            family="A",
            name="standard",
        ),
        tenant_id=authorization.get_client_config().tenant_id,
        access_policies=[], # Access policies will be added later via Role Assignments
        enable_rbac_authorization=True, # Use Azure RBAC for Key Vault access
    ),
)
pulumi.export("keyVaultUri", key_vault.properties.vault_uri)

# 2. Managed Identity for AKS to Access Key Vault
# Purpose: Grant the AKS cluster's managed identity permissions to retrieve secrets from the Key Vault.
key_vault_secrets_user_assignment = authorization.RoleAssignment("keyVaultSecretsUserAssignment",
    principal_id=aks_cluster.identity.principal_id, # Use the principal_id of the AKS cluster's managed identity
    principal_type=authorization.PrincipalType.SERVICE_PRINCIPAL,
    role_definition_id=pulumi.Output.concat(
        "/subscriptions/", authorization.get_subscription().subscription_id,
        "/providers/Microsoft.Authorization/roleDefinitions/4633458b-17de-408a-b874-0445c86b69e6" # Key Vault Secrets User role
    ),
    scope=key_vault.id,
    opts=pulumi.ResourceOptions(depends_on=[key_vault, acr_pull_assignment]), # Ensure Key Vault is created and AKS identity is ready
)

# 3. Azure File Shares Provisioning
# Purpose: Provide persistent storage for stateful applications (Redis, n8n, JupyterLab, OpenWebUI, ChromaDB).
storage_account = azure_native.storage.StorageAccount("agenticStorageAccount",
    resource_group_name=resource_group.name,
    location=resource_group.location,
    sku=azure_native.storage.SkuArgs(name="Standard_LRS"), # Standard_LRS for locally redundant storage
    kind="StorageV2", # General-purpose v2 account
)

# Azure File Share for shared_uploads (e.g., for RAG documents)
shared_uploads_share = azure_native.storage.FileShare("sharedUploadsShare",
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
    share_name="shared-uploads",
    share_properties=azure_native.storage.FileSharePropertiesArgs(
        share_quota=50, # GB
    ),
    opts=pulumi.ResourceOptions(depends_on=[storage_account]),
)
pulumi.export("sharedUploadsShareName", shared_uploads_share.name)

# Azure File Share for BLAST databases (HPC server)
blast_databases_share = azure_native.storage.FileShare("blastDatabasesShare",
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
    share_name="blast-databases",
    share_properties=azure_native.storage.FileSharePropertiesArgs(
        share_quota=50, # GB
    ),
    opts=pulumi.ResourceOptions(depends_on=[storage_account]),
)
pulumi.export("blastDatabasesShareName", blast_databases_share.name)

# Azure File Share for Vector DB persistence (ChromaDB)
vector_db_persistence_share = azure_native.storage.FileShare("vectorDbPersistenceShare",
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
    share_name="vector-db-persistence",
    share_properties=azure_native.storage.FileSharePropertiesArgs(
        share_quota=50, # GB
    ),
    opts=pulumi.ResourceOptions(depends_on=[storage_account]),
)
pulumi.export("vectorDbPersistenceShareName", vector_db_persistence_share.name)

# Azure File Share for Redis data
redis_data_share = azure_native.storage.FileShare("redisDataShare",
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
    share_name="redis-data",
    share_properties=azure_native.storage.FileSharePropertiesArgs(
        share_quota=10, # GB
    ),
    opts=pulumi.ResourceOptions(depends_on=[storage_account]),
)
pulumi.export("redisDataShareName", redis_data_share.name)

# Azure File Share for n8n data
n8n_data_share = azure_native.storage.FileShare("n8nDataShare",
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
    share_name="n8n-data",
    share_properties=azure_native.storage.FileSharePropertiesArgs(
        share_quota=10, # GB
    ),
    opts=pulumi.ResourceOptions(depends_on=[storage_account]),
)
pulumi.export("n8nDataShareName", n8n_data_share.name)

# Azure File Share for JupyterLab data
jupyterlab_data_share = azure_native.storage.FileShare("jupyterlabDataShare",
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
    share_name="jupyterlab-data",
    share_properties=azure_native.storage.FileSharePropertiesArgs(
        share_quota=20, # GB
    ),
    opts=pulumi.ResourceOptions(depends_on=[storage_account]),
)
pulumi.export("jupyterlabDataShareName", jupyterlab_data_share.name)

# Azure File Share for OpenWebUI data
openwebui_data_share = azure_native.storage.FileShare("openwebuiDataShare",
    resource_group_name=resource_group.name,
    account_name=storage_account.name,
    share_name="openwebui-data",
    share_properties=azure_native.storage.FileSharePropertiesArgs(
        share_quota=20, # GB
    ),
    opts=pulumi.ResourceOptions(depends_on=[storage_account]),
)
pulumi.export("openwebuiDataShareName", openwebui_data_share.name)

# 4. Azure AD Application Registration (for Keycloak)
# Purpose: If Keycloak is configured to use Azure Active Directory as an identity provider,
# it will need an Azure AD Application Registration.
ad_app = azure_native.graphservices.Application("keycloakAdApp",
    display_name="KeycloakAgenticFramework",
    sign_in_audience="AzureADMyOrg", # Or AzureADMultipleOrgs, depending on your AAD setup
)
# Service Principal for the application
ad_sp = azure_native.graphservices.ServicePrincipal("keycloakAdSp",
    app_id=ad_app.app_id,
    opts=pulumi.ResourceOptions(depends_on=[ad_app]),
)
pulumi.export("keycloakAdAppId", ad_app.app_id)
pulumi.export("keycloakAdSpId", ad_sp.id)

# --- Exports ---

# Export the kubeconfig to access the cluster
creds = pulumi.Output.all(resource_group.name, aks_cluster.name).apply(
    lambda args: containerservice.list_managed_cluster_user_credentials(
        resource_group_name=args[0],
        resource_name=args[1],
    )
)
kubeconfig = creds.kubeconfigs[0].value.apply(lambda enc: enc.decode("utf-8"))

pulumi.export("resourceGroupName", resource_group.name)
pulumi.export("acrLoginServer", container_registry.login_server)
pulumi.export("aksClusterName", aks_cluster.name)
pulumi.export("kubeconfig", pulumi.Output.secret(kubeconfig))
