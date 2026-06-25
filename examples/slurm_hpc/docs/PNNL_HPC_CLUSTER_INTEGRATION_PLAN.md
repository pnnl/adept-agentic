# HPC Cluster Integration Plan

**Date**: 2026-06-10
**Status**: Complete (all tests passing)
**Branch**: feature-platform-optimizations-FY26Q4-phase1

---

## 1. Overview

Add MCP tools to the existing `slurm_hpc` stack for production Slurm clusters:

| Cluster | Transport | Auth |
|---------|-----------|------|
| **Cluster A** | SSH only | Key-based passwordless |
| **Cluster B** | SSH + REST API (slurmrestd) | Key-based SSH / JWT REST |

The implementation uses a shared `SlurmTransport` ABC with a single `FabricSSHTransport` concrete class (Fabric library) that works for any cluster. SSH keys are managed via a YAML-based lifecycle configuration (`clusters.yaml`) -- key material is never exposed to the reasoning model.

**Key Principles**:
1. Augment -- not replace -- existing local Docker Slurm tools
2. SSH keys managed via YAML config; private key never in LLM responses
3. User must manually provision public key on remote cluster authorized_keys
4. Verbose Pydantic models + docstrings for effective MCP tool introspection

---

## 2. Architecture

### 2.1 Package Structure (Refactored)

```
slurm_mcp_server/slurm_mcp/
  # Shared modules (used by both clusters)
  transport.py              # SlurmTransport ABC + JobResult/ClusterInfo dataclasses
  fabric_transport.py       # FabricSSHTransport -- concrete impl (Fabric library)
  slurm_parsers.py          # Shared parsers: sbatch, squeue --json, sinfo, sacct, scancel
  clusters.yaml             # YAML-based cluster + SSH key lifecycle configuration
  ssh_keys.py               # SSH key lifecycle management (generate, check, test connectivity)
  ssh_key_models.py         # Pydantic models for SSH key tool inputs/outputs
  ssh_key_tools.py          # MCP tools for key lifecycle (5 tools)
  
  # Cluster-specific subpackages (config, tools, models only)
  <cluster_a>/
    __init__.py
    config.py               # ClusterAConfig (pydantic-settings, prefix)
    models.py               # ClusterAJobSpec, ClusterAJobSubmissionRequest
    tools.py                # 6 cluster_a_* MCP tools
    ssh_client.py           # Re-export of FabricSSHTransport (backward compat)
  
  <cluster_b>/
    __init__.py
    config.py               # ClusterBConfig (pydantic-settings, prefix)
    models.py               # ClusterBJobSpec, ClusterBJobSubmissionRequest
    tools.py                # 6 cluster_b_* MCP tools
    rest_transport.py       # ClusterBRESTTransport (httpx + JWT auth)
  
  # Session-scoped workspace management
  session_workspace.py      # WorkspaceManager -- per-user, per-session dirs under /data/
  
  # Existing (unchanged)
  app.py                    # FastMCP instance, registers all tools
  tools.py                  # Original local Docker Slurm tools (6 tools)
  client.py                 # SlurmClient for local REST
  config.py                 # SlurmConfig for local cluster
  models.py                 # Original local Slurm models
```

### 2.2 Transport Abstraction

```python
class SlurmTransport(ABC):
    """Abstract transport -- concrete: FabricSSHTransport, (future) RESTTransport."""
    
    async def submit_job(script, job_name, **kwargs) -> JobResult
    async def get_job_status(job_id) -> JobResult
    async def cancel_job(job_id) -> JobResult
    async def list_jobs(user?, state?) -> List[Dict]
    async def get_cluster_info() -> ClusterInfo
    async def ping() -> bool
    async def close() -> None
```

`FabricSSHTransport` accepts any config object satisfying the `SSHConfig` protocol (host, ssh_port, username, ssh_timeout, resolved_ssh_key_path).

### 2.3 SSH Key Security Model

```
+-------------------------------------------+
| clusters.yaml                             |
|   private_key_path: ~/.ssh/adept_*        |
|   provisioning: manual_authorized_keys    |
+-------------------------------------------+
         |                      |
         v                      v
+-----------------+    +-------------------+
| ssh_keys.py     |    | fabric_transport  |
| (lifecycle mgr) |    | (job execution)   |
| - generate      |    | - reads key file  |
| - check status  |    | - never returns   |
| - test connect  |    |   key material    |
+-----------------+    +-------------------+
         |
         v
+-------------------+
| ssh_key_tools.py  |
| (MCP tools)       |
| - returns PUBLIC  |
|   key only        |
| - fingerprint     |
|   prefix only     |
| - NEVER private   |
|   key content     |
+-------------------+
```

**Flow for new user setup**:
1. Agent calls `hpc_generate_ssh_key(cluster_name="<cluster>")` -> generates ed25519 key pair locally
2. Agent returns PUBLIC key + instructions to user
3. User manually SSHs into the cluster and adds public key to `~/.ssh/authorized_keys`
4. Agent calls `hpc_test_ssh_connectivity(cluster_name="<cluster>")` -> confirms access works
5. Agent can now use `<cluster>_submit_job`, `<cluster>_list_jobs`, etc.

---

## 3. MCP Tool Introspection Design

### 3.1 Docstring Standard (Critical for LLM Discovery)

Every tool MUST have a docstring that follows this structure for effective MCP `tools/list` introspection:

```python
@app.tool
async def cluster_operation(
    param: Annotated[str, Field(description="Verbose parameter description")]
) -> Dict[str, Any]:
    """One-line summary of what this tool does.

    Multi-paragraph explanation including:
    - What the tool does mechanically
    - Prerequisites (what must be true before calling)
    - How it relates to other tools in the workflow

    Args:
        param: Detailed explanation of the parameter

    Returns:
        dict: Description of return fields

    Example:
        >>> cluster_operation(param="value")
        {"status": "success", "field": "value"}
    """
```

### 3.2 Pydantic Model Standard

All complex tool inputs use Pydantic BaseModel with verbose Field descriptions:

```python
class ClusterJobSpec(BaseModel):
    """Resource specification for a batch job."""

    job_name: str = Field(..., description="Job name for tracking in squeue/sacct output")
    partition: Optional[str] = Field(None, description="Target partition (queue) to submit to")
    nodes: int = Field(1, ge=1, description="Number of compute nodes requested")
    memory: Optional[str] = Field(None, description="Memory per node (e.g., '16G', '4096M')")
    time_limit: str = Field("01:00:00", description="Wall time limit in HH:MM:SS format")
```

### 3.3 Security Constraint on Return Values

Tools MUST NEVER return:
- Private key file contents
- Private key paths in a way that suggests the LLM should read them
- SSH connection credentials beyond username@host

Tools MAY return:
- Public key content (safe to share, needed for user provisioning)
- Fingerprint prefix (first 19 chars of SHA256 hash)
- Key age, permissions status, algorithm
- Connectivity test results (success/fail + error message)

---

## 4. Tool Inventory

### 4.1 Per-Cluster Tools (6 tools each, `<cluster>_*` prefix)

| Tool | Input | Transport | Description |
|------|-------|-----------|-------------|
| `<cluster>_ping` | (none) | SSH | Test connectivity + Slurm scheduler responsiveness |
| `<cluster>_submit_job` | `ClusterJobSubmissionRequest` | SSH (sbatch) | Submit batch job script |
| `<cluster>_get_job_details` | `job_id: str` | SSH (squeue/sacct) | Job status + detailed metadata |
| `<cluster>_cancel_job` | `job_id: str` | SSH (scancel) | Cancel running/pending job |
| `<cluster>_list_jobs` | `ClusterJobListFilters?` | SSH (squeue --json) | List queue with optional filters |
| `<cluster>_get_cluster_summary` | (none) | SSH (sinfo + squeue) | Full cluster overview |

### 4.2 SSH Key Lifecycle Tools (5 tools, `hpc_*` prefix)

| Tool | Input | Description |
|------|-------|-------------|
| `hpc_list_clusters` | (none) | List all configured clusters + key status |
| `hpc_check_ssh_key` | `SSHKeyCheckRequest` | Detailed key status for one cluster |
| `hpc_generate_ssh_key` | `SSHKeyGenerateRequest` | Generate key pair, return public key + instructions |
| `hpc_test_ssh_connectivity` | `SSHConnectivityTestRequest` | Test SSH login with configured key |
| `hpc_get_provisioning_instructions` | `ProvisioningInstructionsRequest` | Get public key + copy instructions |

---

## 5. Configuration

### 5.1 clusters.yaml (SSH Key Lifecycle)

```yaml
clusters:
  cluster-a:
    host: cluster-a.example.org
    transport_modes: [ssh]
    ssh_key:
      private_key_path: ~/.ssh/adept_cluster_a_ed25519
      algorithm: ed25519
      provisioning: manual_authorized_keys
  cluster-b:
    host: cluster-b.example.org
    transport_modes: [ssh, rest]
    ssh_key:
      private_key_path: ~/.ssh/adept_cluster_b_ed25519
      algorithm: ed25519
      provisioning: manual_authorized_keys

key_policy:
  preferred_algorithm: ed25519
  rotation_reminder_days: 365
  strict_host_key_checking: true
```

### 5.2 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `<CLUSTER>_HOST` | (from clusters.yaml) | Cluster hostname |
| `<CLUSTER>_USERNAME` | (operator's username) | SSH/Slurm username |
| `<CLUSTER>_SSH_KEY_PATH` | ~/.ssh/adept_<cluster>_ed25519 | Private key path |
| `<CLUSTER>_TRANSPORT_MODE` | ssh | Transport: ssh or auto |
| `<CLUSTER>_WORKING_DIRECTORY` | /scratch/<username> | Default sbatch --chdir |
| `<CLUSTER>_REST_API_URL` | (empty) | slurmrestd URL if available |

---

## 6. Dependencies

```
fabric>=3.2.0,<4.0.0    # SSH via Fabric (paramiko under the hood)
pyyaml>=6.0.0           # clusters.yaml parsing
```

Fabric was explicitly chosen over asyncssh because:
1. Simpler synchronous API (no event loop conflicts with FastMCP)
2. Built-in Connection pooling and reconnection
3. Proven at scale in infrastructure automation
4. The async context is already handled by FastMCP -- Fabric's sync `run()` is fine in async tools

---

## 7. Test Strategy

| Tier | Files | Guard | Scope |
|------|-------|-------|-------|
| Unit | `tests/unit/test_slurm_parsers.py`, `test_ssh_keys.py`, `test_fabric_transport.py` | None (offline) | Mock Fabric, validate parsing/schemas |
| Integration | `tests/integration/test_connectivity.py` | Socket probe :22 | Real SSH: ping, sinfo, squeue (read-only) |
| E2E | `tests/e2e/test_job_lifecycle.py` | `E2E_ENABLED=true` | Submit trivial job, poll, verify |

---

## 8. Security Considerations

1. **Key isolation**: Private keys live on the host filesystem, referenced by path in `clusters.yaml`. Never baked into Docker images.
2. **No key exfiltration**: SSH key tools return only public key content, fingerprint prefixes, and status metadata. Private key material is never serialized into tool responses.
3. **Manual provisioning**: User must manually add public key to `authorized_keys` on the cluster. The tool provides instructions but does not attempt remote key injection.
4. **Key rotation**: `clusters.yaml` policy tracks key age. Tools flag when `rotation_reminder_days` is exceeded.
5. **Transport security**: Fabric uses paramiko with strict host key checking by default.
