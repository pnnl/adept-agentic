# Slurm HPC Stack -- Operator Onboarding

**Stack**: `examples/slurm_hpc`
**Last updated**: 2026-06-12

---

## 1. Quick Start

```bash
cd examples/slurm_hpc

# Build and start all services (local Slurm backend + MCP server + proxy)
make setup

# Verify health
make health

# Run tests
make test-unit          # 117 unit tests (no services needed)
make test-integration   # 29 integration tests (requires running stack)
make test-e2e           # 12 E2E tests (requires running stack + Docker socket)
```

---

## 2. SSH Key Pair Management

The stack connects to remote HPC clusters via SSH. Key pairs are stored in a host-mounted volume at `examples/slurm_hpc/ssh_keys/` which persists across container restarts.

### 2.1 Key Naming Convention

```
ssh_keys/
  slurm.id_ed25519.<cluster_fqdn>       # Private key (mode 600)
  slurm.id_ed25519.<cluster_fqdn>.pub   # Public key
  known_hosts                            # (optional) Shared known_hosts
```

Example:
```
ssh_keys/
  slurm.id_ed25519.cluster-a.example.org
  slurm.id_ed25519.cluster-a.example.org.pub
  slurm.id_ed25519.cluster-b.example.org
  slurm.id_ed25519.cluster-b.example.org.pub
```

### 2.2 Volume Mount Architecture

| Container | Mount | Mode | Purpose |
|-----------|-------|------|---------|
| `slurm_mcp_server` | `./ssh_keys:/app/.ssh` | `rw` | Key generation + SSH transport |
| Test runner | `./ssh_keys:/app/.ssh` | `ro` | Integration test access |

### 2.3 Generating Keys

Operators with existing HPC allocations:

```bash
# Generate Ed25519 key pair for cluster-a
ssh-keygen -t ed25519 -f ssh_keys/slurm.id_ed25519.cluster-a.example.org -N "" -C "adept-mcp@cluster-a"

# Generate Ed25519 key pair for cluster-b
ssh-keygen -t ed25519 -f ssh_keys/slurm.id_ed25519.cluster-b.example.org -N "" -C "adept-mcp@cluster-b"

# Set correct permissions (private key must be 600)
chmod 600 ssh_keys/slurm.id_ed25519.*
```

Then provision the public key on the remote cluster:
```bash
# Copy public key to cluster-a
ssh-copy-id -i ssh_keys/slurm.id_ed25519.cluster-a.example.org.pub youruser@cluster-a.example.org

# Copy public key to cluster-b
ssh-copy-id -i ssh_keys/slurm.id_ed25519.cluster-b.example.org.pub youruser@cluster-b.example.org
```

### 2.4 Connecting Your Own Clusters

You can use the stack for local Slurm jobs (Docker backend) without remote SSH keys. To connect to your own Slurm cluster:

1. Edit `slurm_mcp_server/slurm_mcp/clusters.yaml` -- add your cluster entry
2. Generate a key pair following the naming convention:
   ```bash
   ssh-keygen -t ed25519 -f ssh_keys/slurm.id_ed25519.<your-cluster-fqdn> -N "" -C "adept-mcp@<cluster>"
   chmod 600 ssh_keys/slurm.id_ed25519.<your-cluster-fqdn>
   ```
3. Provision the public key on your cluster's `~/.ssh/authorized_keys`
4. Create a cluster config subpackage (copy from an existing cluster config, change prefix)

### 2.5 Using the MCP Tool for Key Generation

The agent can generate keys via the `hpc_generate_ssh_key` MCP tool:

```
User: Generate an SSH key pair for cluster-a
Agent: [calls hpc_generate_ssh_key("cluster-a")]
       Key pair generated. Public key:
       ssh-ed25519 AAAA... adept-mcp@cluster-a

       Please append this to ~/.ssh/authorized_keys on cluster-a.example.org
```

### 2.6 Key Lifecycle

| Operation | Method | Notes |
|-----------|--------|-------|
| Generate | `ssh-keygen -t ed25519` or MCP tool | Creates in `ssh_keys/` |
| Provision | Manual `ssh-copy-id` | User appends pubkey on remote |
| Rotate | Delete old + generate new | Update remote authorized_keys |
| Revoke | Remove from remote authorized_keys | Then delete local key |
| Check status | MCP tool `hpc_check_ssh_key_status` | Reports existence + permissions |

### 2.7 Algorithm Policy

The stack uses **Ed25519 exclusively**. Ed25519 keys are:
- Smaller (256-bit vs 4096-bit RSA)
- Faster (signing and verification)
- Fully supported by paramiko/Fabric without OpenSSH-format issues
- Required by `clusters.yaml` policy: `preferred_algorithm: ed25519`

RSA keys are NOT supported -- paramiko has compatibility issues with OpenSSH-format RSA keys (`-----BEGIN OPENSSH PRIVATE KEY-----`).

### 2.8 SSH Authentication Methods

Different clusters may enforce different authentication policies:

| Cluster | Auth Method | Requirements |
|---------|-------------|--------------|
| Key-only clusters | **Key-only** | Ed25519 key in `ssh_keys/` + pubkey in remote `authorized_keys` |
| 2FA clusters | **Key + Password (2FA)** | Ed25519 key + password via env var |

**Key-only clusters**:
- No additional configuration needed beyond the key pair
- Tests run automatically when keys are provisioned

**2FA clusters**:
- The cluster accepts the SSH key but then requires a password (keyboard-interactive)
- Provide your password via environment variable:
  ```bash
  # In your .env file (gitignored, never committed):
  CLUSTER_PASSWORD=your-password

  # Or export in your shell session:
  export CLUSTER_PASSWORD=your-password
  ```
- The password is passed to the container via `docker-compose.yaml` environment section
- Integration tests skip 2FA cluster SSH tests when the password env var is not set
- The MCP tool `hpc_ping` will fail for 2FA clusters without the password configured

**Security notes for 2FA passwords**:
- NEVER store in git-tracked files (`.env` is gitignored)
- NEVER hardcode in `docker-compose.yaml` (use variable substitution)
- Rotated via normal organizational password policy
- Only needed for clusters that enforce keyboard-interactive auth

---

## 3. Cluster Configuration

### 3.1 Configuration Files

| File | Purpose |
|------|---------|
| `slurm_mcp_server/slurm_mcp/clusters.yaml` | Master cluster registry + key paths |
| `slurm_mcp_server/slurm_mcp/<cluster>/config.py` | Cluster connection settings (env var override) |

### 3.2 Environment Variable Overrides

All config fields can be overridden via environment variables with the cluster prefix:

```bash
# Override cluster-a username
export CLUSTER_A_USERNAME=myuser

# Override cluster-b SSH key path
export CLUSTER_B_SSH_KEY_PATH=/custom/path/to/key

# Override working directory
export CLUSTER_A_WORKING_DIRECTORY=/scratch/myuser
```

---

## 4. Network Architecture

### 4.1 Connectivity Matrix

| Service | Network | Remote cluster :22 |
|---------|---------|-------------------|
| slurm_mcp_server | adept_application_network | Reachable |
| sandbox_mcp_server | adept_sandbox_network | Blocked (by design) |
| Test runner | adept_application_network | Reachable |

### 4.2 Port Mappings

| Service | Container Port | Host Port | URL |
|---------|----------------|-----------|-----|
| MCP Server | 8002 | 8002 | http://localhost:8002 |
| Nginx Proxy (HTTP) | 80 | 9820 | http://localhost:9820 |
| Nginx Proxy (HTTPS) | 443 | 9821 | https://localhost:9821 |

---

## 5. Testing

### 5.1 Test Suites

| Suite | Target | Tests | Requirements |
|-------|--------|-------|--------------|
| Unit | `make test-unit` | 117 | None |
| Schema | `make test-schema` | 31 | None |
| Deployment | `make test-deployment` | 8 | Stack running |
| MCP Client | `make test-mcp-client` | 11 | Stack running |
| Integration | `make test-integration` | 29 | Stack + Docker socket + SSH keys |
| E2E | `make test-e2e` | 12 | Stack + Docker socket |
| TLS | `make test-tls` | 12 | Stack + certs in `certs/` |

### 5.2 Integration Test Skip Categories

| Category | Skip Condition | How to Enable |
|----------|---------------|---------------|
| HPC SSH (5 tests) | SSH key not at configured path | Place keys in `ssh_keys/` + provision pubkey on remote |
| Slurm backend (2 tests) | `SLURM_CLUSTER_RUNNING` not set | Automatic via Makefile target |
| TLS (9 tests) | No certs in `certs/` | Run `make generate-certs` |

### 5.3 Running All Tests

```bash
# Background with timestamped log
mkdir -p logs && nohup make test-integration > logs/test_integration_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Watch output
tail -f logs/test_integration_*.log
```

---

## 6. Troubleshooting

### Key Permission Errors

```
PermissionError: [Errno 13] Permission denied: '/app/.ssh/slurm.id_ed25519.cluster-a.example.org'
```

Fix: Ensure private keys are mode 600:
```bash
chmod 600 ssh_keys/slurm.id_ed25519.*
```

### SSH Authentication Failed

```
paramiko.ssh_exception.AuthenticationException: Authentication failed.
```

This means the key was read but not accepted by the remote host. Verify:
1. Public key is in `~/.ssh/authorized_keys` on the remote cluster
2. The username matches (check your `<CLUSTER>_USERNAME` env var)
3. Test manually: `ssh -i ssh_keys/slurm.id_ed25519.<fqdn> -o StrictHostKeyChecking=no <user>@<fqdn> hostname`

### SSH Connection Timeout

```
ssh: connect to host cluster-a.example.org port 22: Connection timed out
```

The container must be on `adept_application_network` which provides outbound NAT. Verify:
```bash
docker exec slurm_mcp_server python -c "import socket; socket.create_connection(('cluster-a.example.org', 22), timeout=5); print('OK')"
```

### Keys Not Found (test skips)

Integration tests skip with "SSH key not provisioned" when:
1. `ssh_keys/` directory is empty
2. Key filenames don't match the paths in `clusters.yaml`
3. Test container UID can't read the keys (ensure `--user $(id -u):$(id -g)` in Makefile)

---

## 7. E2E Credentials and Authentication

For cross-service E2E tests that authenticate against the full ADEPT stack (Keycloak, agent gateway, orchestration service), see **[CREDENTIALS_AND_AUTH.md](CREDENTIALS_AND_AUTH.md)**.

Quick setup:
```bash
cp config/e2e_credentials.json.example config/e2e_credentials.json
# Edit with your Keycloak username/password
```

---

## 8. Adding a New Cluster

1. Create subpackage: `slurm_mcp_server/slurm_mcp/<cluster_name>/`
2. Add `config.py` (copy from an existing cluster config, change prefix)
3. Add `models.py` and `tools.py`
4. Add entry in `clusters.yaml`
5. Generate SSH key pair in `ssh_keys/`
6. Register tools in `slurm_mcp_server/slurm_mcp/main.py`
7. Update this onboarding doc
