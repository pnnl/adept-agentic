"""Pydantic models for SSH key lifecycle management tools.

These models provide structured, validated input for all SSH key
management operations across HPC clusters.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class ClusterSSHKeyStatus(BaseModel):
    """Status report for an SSH key pair on a specific cluster."""

    cluster: str = Field(..., description="Cluster identifier (e.g., 'deception', 'tahoma')")
    display_name: str = Field(..., description="Human-readable cluster name")
    host: str = Field(..., description="Cluster hostname")
    username: str = Field(..., description="SSH username for this cluster")
    transport_modes: List[str] = Field(..., description="Supported transports (ssh, rest)")
    ssh_key_exists: bool = Field(..., description="Whether private key file exists locally")
    ssh_key_algorithm: str = Field(..., description="Key algorithm (ed25519, ecdsa, rsa)")
    fingerprint_prefix: str = Field(
        default="(no key)",
        description="First 19 chars of SHA256 fingerprint (redacted for safety)",
    )
    age_days: Optional[int] = Field(
        None, description="Age of the key in days since creation"
    )
    rotation_due: bool = Field(
        default=False, description="Whether key has exceeded rotation_reminder_days"
    )
    permissions_ok: bool = Field(
        default=False, description="Whether private key has correct 0600 permissions"
    )


class ClusterListResponse(BaseModel):
    """Response from hpc_list_clusters tool."""

    status: str = Field(..., description="Operation status: 'success' or 'error'")
    cluster_count: int = Field(..., description="Number of configured clusters")
    clusters: List[ClusterSSHKeyStatus] = Field(
        ..., description="Status of each configured cluster"
    )


class SSHKeyCheckRequest(BaseModel):
    """Request to check SSH key status for a cluster."""

    cluster_name: str = Field(
        ...,
        description="Cluster identifier from clusters.yaml (e.g., 'deception', 'tahoma')",
    )


class SSHKeyCheckResponse(BaseModel):
    """Detailed SSH key status for a single cluster."""

    status: str = Field(
        ..., description="Overall status: 'ok' or 'issues_found'"
    )
    cluster: str = Field(..., description="Cluster identifier")
    private_key_exists: bool = Field(..., description="Private key file exists")
    public_key_exists: bool = Field(..., description="Public key file exists")
    private_key_path: str = Field(..., description="Path to private key file")
    public_key_path: str = Field(..., description="Path to public key file")
    algorithm: str = Field(..., description="Key algorithm (ed25519, ecdsa, rsa)")
    fingerprint_prefix: str = Field(
        default="", description="Truncated SHA256 fingerprint"
    )
    created_at: Optional[str] = Field(
        None, description="ISO8601 timestamp of key creation"
    )
    age_days: Optional[int] = Field(None, description="Key age in days")
    rotation_due: bool = Field(
        default=False, description="Whether key exceeds rotation threshold"
    )
    permissions_ok: bool = Field(
        default=False, description="Whether file permissions are correct (0600)"
    )
    errors: List[str] = Field(
        default_factory=list, description="List of issues found"
    )


class SSHKeyGenerateRequest(BaseModel):
    """Request to generate a new SSH key pair for a cluster."""

    cluster_name: str = Field(
        ...,
        description="Cluster identifier from clusters.yaml (e.g., 'deception', 'tahoma')",
    )
    overwrite: bool = Field(
        default=False,
        description="If True, replace existing key pair. If False, fail if key exists.",
    )


class SSHKeyGenerateResponse(BaseModel):
    """Response after generating a new SSH key pair."""

    status: str = Field(..., description="'generated' on success, 'error' on failure")
    cluster: Optional[str] = Field(None, description="Cluster identifier")
    algorithm: Optional[str] = Field(None, description="Key algorithm used")
    public_key_path: Optional[str] = Field(None, description="Path to public key file")
    fingerprint: Optional[str] = Field(None, description="Full key fingerprint")
    public_key: Optional[str] = Field(
        None,
        description="Public key content (safe to share — user copies this to cluster)",
    )
    provisioning_method: Optional[str] = Field(
        None, description="How to provision the key on the cluster"
    )
    instructions: Optional[str] = Field(
        None,
        description="Step-by-step instructions for the user to add the public key to their authorized_keys",
    )
    message: Optional[str] = Field(None, description="Error message if failed")


class SSHConnectivityTestRequest(BaseModel):
    """Request to test SSH connectivity to a cluster."""

    cluster_name: str = Field(
        ...,
        description="Cluster identifier from clusters.yaml (e.g., 'deception', 'tahoma')",
    )


class SSHConnectivityTestResponse(BaseModel):
    """Result of an SSH connectivity test."""

    success: bool = Field(..., description="Whether SSH connection succeeded")
    cluster: Optional[str] = Field(None, description="Cluster identifier")
    host: Optional[str] = Field(None, description="Target hostname")
    username: Optional[str] = Field(None, description="SSH username attempted")
    message: Optional[str] = Field(
        None, description="Success message or error details"
    )
    error: Optional[str] = Field(None, description="Error message if failed")


class ProvisioningInstructionsRequest(BaseModel):
    """Request to get provisioning instructions for a cluster's SSH key."""

    cluster_name: str = Field(
        ...,
        description="Cluster identifier from clusters.yaml (e.g., 'deception', 'tahoma')",
    )


class ProvisioningInstructionsResponse(BaseModel):
    """Provisioning instructions for adding a public key to a cluster."""

    status: str = Field(
        ..., description="'ready' if key exists, 'no_key' if generation needed, 'error' otherwise"
    )
    cluster: str = Field(..., description="Cluster identifier")
    host: Optional[str] = Field(None, description="Cluster hostname")
    username: Optional[str] = Field(None, description="SSH username")
    public_key: Optional[str] = Field(
        None,
        description="Public key content for the user to copy to authorized_keys on the cluster",
    )
    instructions: Optional[str] = Field(
        None,
        description="Step-by-step instructions for manual provisioning",
    )
    message: Optional[str] = Field(None, description="Status message or error")
