"""MCP tools for SSH key lifecycle management.

These tools allow the agent to manage SSH keys for HPC cluster access
WITHOUT exposing private key material in responses. The reasoning model
sees only metadata (paths, fingerprints, connectivity status).
"""

import logging
from typing import Any, Dict

from .app import app
from .ssh_key_models import (
    SSHConnectivityTestRequest,
    SSHKeyCheckRequest,
    SSHKeyGenerateRequest,
    ProvisioningInstructionsRequest,
)
from .ssh_keys import (
    check_key_status,
    generate_key_pair,
    get_cluster_key_configs,
    test_connectivity,
)

logger = logging.getLogger(__name__)


@app.tool
async def hpc_list_clusters() -> Dict[str, Any]:
    """List all configured HPC clusters and their SSH key status.

    Shows which clusters are configured, their transport modes,
    and whether SSH keys exist (without exposing key material).
    """
    try:
        configs = get_cluster_key_configs()
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    clusters = []
    for name, cfg in configs.items():
        key_status = check_key_status(name)
        clusters.append(
            {
                "name": name,
                "display_name": cfg.display_name,
                "host": cfg.host,
                "username": cfg.username,
                "transport_modes": cfg.transport_modes,
                "ssh_key_exists": key_status.private_key_exists,
                "ssh_key_algorithm": cfg.algorithm,
                "fingerprint_prefix": key_status.fingerprint_prefix or "(no key)",
                "age_days": key_status.age_days,
                "rotation_due": key_status.rotation_due,
                "permissions_ok": key_status.permissions_ok,
            }
        )

    return {"status": "success", "cluster_count": len(clusters), "clusters": clusters}


@app.tool
async def hpc_check_ssh_key(request: SSHKeyCheckRequest) -> Dict[str, Any]:
    """Check SSH key status for a specific HPC cluster.

    Returns key existence, age, permissions, and fingerprint prefix.
    Does NOT return private key material.
    """
    status = check_key_status(request.cluster_name)
    return {
        "status": "ok" if status.private_key_exists and status.permissions_ok else "issues_found",
        "cluster": status.cluster,
        "private_key_exists": status.private_key_exists,
        "public_key_exists": status.public_key_exists,
        "private_key_path": status.private_key_path,
        "public_key_path": status.public_key_path,
        "algorithm": status.algorithm,
        "fingerprint_prefix": status.fingerprint_prefix,
        "created_at": status.created_at,
        "age_days": status.age_days,
        "rotation_due": status.rotation_due,
        "permissions_ok": status.permissions_ok,
        "errors": status.errors,
    }


@app.tool
async def hpc_generate_ssh_key(request: SSHKeyGenerateRequest) -> Dict[str, Any]:
    """Generate a new SSH key pair for an HPC cluster.

    Creates the key locally and provides instructions for the user to
    add the public key to their authorized_keys on the remote cluster.

    Returns the PUBLIC key (safe to share) and provisioning instructions.
    Does NOT return the private key.
    """
    result = generate_key_pair(request.cluster_name, overwrite=request.overwrite)

    if not result["success"]:
        return {"status": "error", "message": result["error"]}

    return {
        "status": "generated",
        "cluster": result["cluster"],
        "algorithm": result["algorithm"],
        "public_key_path": result["public_key_path"],
        "fingerprint": result["fingerprint"],
        "public_key": result["public_key"],
        "provisioning_method": result["provisioning"],
        "instructions": result["instructions"],
    }


@app.tool
async def hpc_test_ssh_connectivity(request: SSHConnectivityTestRequest) -> Dict[str, Any]:
    """Test SSH connectivity to an HPC cluster using the configured key.

    Attempts to connect and run a simple command. Returns success/failure
    status without exposing any key material.
    """
    result = test_connectivity(request.cluster_name)
    return result


@app.tool
async def hpc_get_provisioning_instructions(request: ProvisioningInstructionsRequest) -> Dict[str, Any]:
    """Get instructions for provisioning SSH key on a remote cluster.

    If a public key exists, returns the public key content and step-by-step
    instructions for the user to add it to their authorized_keys file on
    the cluster login node.

    The user must manually SSH into the cluster and append the public key
    to ~/.ssh/authorized_keys. The MCP tools then use the private key
    locally to connect via Fabric.
    """
    try:
        configs = get_cluster_key_configs()
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    if request.cluster_name not in configs:
        return {"status": "error", "message": f"Unknown cluster: {request.cluster_name}"}

    cfg = configs[request.cluster_name]

    if not cfg.public_key_path.exists():
        return {
            "status": "no_key",
            "cluster": request.cluster_name,
            "message": f"No public key at {cfg.public_key_path}. Generate one first with hpc_generate_ssh_key.",
        }

    pub_content = cfg.public_key_path.read_text().strip()

    instructions = (
        f"Add this public key to authorized_keys on {cfg.display_name}:\n"
        f"\n"
        f"1. SSH into {cfg.host} with your existing credentials:\n"
        f"   ssh {cfg.username}@{cfg.host}\n"
        f"\n"
        f"2. Append the public key:\n"
        f"   echo '{pub_content}' >> ~/.ssh/authorized_keys\n"
        f"\n"
        f"3. Ensure correct permissions:\n"
        f"   chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys\n"
        f"\n"
        f"4. Verify from this machine:\n"
        f"   ssh -i {cfg.private_key_path} {cfg.username}@{cfg.host} hostname"
    )

    return {
        "status": "ready",
        "cluster": request.cluster_name,
        "host": cfg.host,
        "username": cfg.username,
        "public_key": pub_content,
        "instructions": instructions,
    }
