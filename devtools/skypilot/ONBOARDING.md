# SkyPilot DevTools Onboarding

**Container**: `adept-skypilot:latest`
**Build**: `docker build -t adept-skypilot:latest devtools/skypilot/`
**Makefile prefix**: `make sky-*`

---

## Container Contents

| Tool | Version | Purpose |
|------|---------|---------|
| SkyPilot | 0.12.0 | Cloud VM provisioning + lifecycle (stop/start/down) |
| AWS CLI v2 | Latest | IAM bootstrap, EC2 dry-run, direct AWS API operations |
| AWS CDK (Python) | >=2.100.0 | Infrastructure-as-code EC2 deployment |
| Node.js | 20.x | CDK CLI runtime dependency |
| boto3 | >=1.26.0 | AWS SDK for Python (CDK + custom scripts) |
| Ansible | >=2.16 | OS-level VM preparation and configuration |
| ansible.posix | >=1.5 | POSIX module collection |
| community.general | >=8.0 | General-purpose module collection |
| amazon.aws | >=7.0 | AWS module collection |
| yamllint, jsonschema | Latest | Task YAML validation |

---

## State Isolation (Multi-Context)

All deployment state lives in `devtools/skypilot/contexts/<DEPLOY_CONTEXT>/` (gitignored), **never** in `$HOME/.sky`. Each deployment target (account + provider + environment) gets its own context directory.

| Setting | Value | Why |
|---------|-------|-----|
| Container `HOME` | `/app/state` | SkyPilot writes to `$HOME/.sky/` -- redirected to container path |
| State mount | `contexts/<ctx>/.sky/` -> `/app/state/.sky/` | Per-context SkyPilot state |
| Config mount | `contexts/<ctx>/config.yaml` -> `/app/state/.sky/config.yaml` | Per-context VPC/subnet config |
| SSH keys | `contexts/<ctx>/.ssh/` (RW mount) | Keys retrieved from SSM, written into mount |
| Logs | `contexts/<ctx>/logs/` | Per-context deployment logs |
| Cleanup | `make sky-clean-state DEPLOY_CONTEXT=...` | Uses `sudo rm -rf` (root-owned files) |

### Context Management

```bash
# List available contexts
make sky-list-contexts

# Create a new context
make sky-init-context DEPLOY_CONTEXT=aws-123456789012-staging

# Use a specific context
make cdk-deploy DEPLOY_CONTEXT=aws-<your-account-id>-dev
```

See [SKILLS.md](SKILLS.md) for full deployment workflow patterns.

---

## End-to-End Dev EC2 Deployment

### Prerequisites

1. AWS credentials sourced (e.g., `aws configure`, environment variables, or a credential-sourcing script)
2. Docker running on control host -- needed for CDK and Ansible containerized targets
3. `adept-skypilot:latest` container built (`make sky-build`)
4. CDK bootstrapped in target account (`make cdk-bootstrap` -- one-time)

### Step-by-Step

All commands run from the **project root** directory. CDK and Ansible targets are containerized (run inside `adept-skypilot:latest`). The `ec2-*` targets are host-local SSH wrappers defined in `devtools/Makefile.internal` (included into the root Makefile via `-include`); invoke them from the project root, not from `devtools/skypilot/`.

```bash
# 1. Build the devtools container
make sky-build

# 2. Bootstrap CDK (first time per account only)
make cdk-bootstrap

# 3. Validate stack before deploy
make cdk-synth

# 4. Deploy EC2 instance (background, auto-approve)
make cdk-deploy-bg
# Monitor: tail -f devtools/skypilot/contexts/<DEPLOY_CONTEXT>/logs/cdk_deploy_*.log

# 5. Retrieve SSH key from SSM Parameter Store
make cdk-retrieve-key
# Key saved to: devtools/skypilot/contexts/<DEPLOY_CONTEXT>/.ssh/

# 6. Fix SSH key ownership (Docker container writes as root)
sudo chown $(whoami) devtools/skypilot/contexts/<DEPLOY_CONTEXT>/.ssh/*.pem

# 7. Test SSH connectivity (host-local, no container)
make ec2-ping EC2_HOST=<private-ip>

# 8. Check instance status (unified: stack/instance/IP/SSM)
make cdk-instance-status

# 9. (Optional) If your organization instruments instances post-creation
#    (e.g., security agents, compliance hooks), wait for those to complete
#    before proceeding. Running Ansible concurrently with post-creation
#    hooks can cause package conflicts and non-deterministic failures.

# 10. Run Ansible OS preparation (tarball mode, background)
make ansible-prepare-vm-bg \
  ANSIBLE_TARGET_HOST=<private-ip> \
  ANSIBLE_SSH_KEY=ADE-dev-<user>-<account>-key.pem
# Monitor: tail -f devtools/skypilot/contexts/<DEPLOY_CONTEXT>/logs/ansible_prepare_*.log

# 11. Sync codebase to EC2 via rsync (incremental, honors .gitignore)
#     Note: ec2-sync only copies files, it does NOT install packages.
#     Ansible must have created the workspace directory first.
make ec2-sync EC2_HOST=<private-ip>

# 12. SSH to instance (host-local)
make ec2-ssh EC2_HOST=<private-ip>

# 13. On EC2: launch ADEPT stack
cd /data/workspace/adept-agentic
./scripts/quick-start-adept-and-subsystems.sh

# 14. On EC2: verify stack health
docker ps --format '{{.Names}}\t{{.Status}}' | sort
curl -s http://localhost:8083/health   # Agent Gateway

# 15. From control host: check Docker stats on EC2
make ec2-stats EC2_HOST=<private-ip>
```

### Key Timings

| Phase | Duration | Notes |
|-------|----------|-------|
| CDK deploy | ~3 min | EC2 + IAM + SG + CloudWatch alarm |
| Ansible OS prep | ~5-10 min | Docker, Python, workspace, tarball transfer |
| Codebase rsync | ~5 sec initial, <1 sec incremental | Honors `.gitignore`, `--delete` flag |
| Docker image builds | ~30-60 min | First time on fresh EC2 (no cache) |
| ADEPT stack start | ~5 min | 26 containers, all services healthy |
| **Total** | ~45-80 min | End-to-end from `cdk-deploy` to health check |

### Known Issues and Workarounds

| Issue | Workaround |
|-------|-----------|
| EC2 cannot clone from GitHub | Use tarball mode (default): `ANSIBLE_SOURCE_TARBALL=true` |
| Auto-stop timer too short | Use 480 min (8h): `make cdk-schedule-stop CDK_STOP_MINUTES=480` |
| `.env` RAGFLOW_OIDC_SCOPE unquoted | Fixed in `.env.example` -- multi-word values must be quoted |
| Keycloak admin-cli public client (fresh install) | `bootstrap_keycloak.py` handles automatically |
| Credential check wrong path | Fixed in `start-chapter-resources.sh` |
| SSH key owned by root | `sudo chown $(whoami)` on the `.pem` file (Docker container writes as root) |
| Azure LLM 403 on fresh EC2 | Configure `AZURE_API_BASE`, `AZURE_API_KEY`, `AZURE_API_VERSION` in `.env` before `make start` |

### Day-to-Day Operations (Host-Local ec2-* Targets)

After the initial deploy + Ansible setup, use these targets for ongoing development. They use SSH directly from the control host (no Docker container needed). These targets are defined in `devtools/Makefile.internal` and included into the root Makefile via `-include` -- always invoke them from the **project root**, not from `devtools/skypilot/`.

```bash
# Check if EC2 is reachable
make ec2-ping EC2_HOST=<private-ip>

# Sync your latest local changes to EC2 (incremental)
make ec2-sync EC2_HOST=<private-ip>

# Preview what would sync (dry-run)
make ec2-sync-dry EC2_HOST=<private-ip>

# Open interactive SSH session
make ec2-ssh EC2_HOST=<private-ip>

# Run a command on EC2
make ec2-exec EC2_HOST=<private-ip> EC2_CMD="docker ps | wc -l"

# View Docker container stats
make ec2-stats EC2_HOST=<private-ip>

# Force-recreate a service (reloads .env changes)
make ec2-recreate-service EC2_HOST=<private-ip> EC2_SERVICE=orchestration_service

# Run the validation suite on EC2
make ec2-validate EC2_HOST=<private-ip>
```

The `EC2_WORKSPACE` defaults to `/data/workspace/adept-agentic-{DEPLOY_CONTEXT}` (e.g., `/data/workspace/adept-agentic-aws-123456789012-dev`). This uses context-based naming: one VM = one deployment = one context. Redeployments overwrite in place (idempotent). Override with `EC2_WORKSPACE=/custom/path` if needed.

### Teardown

```bash
# Destroy CDK stack (EC2, SG, IAM, key pair, CloudWatch alarm)
make cdk-destroy

# Verify no orphaned resources remain
make cdk-instance-status
# Expected: "Stack does not exist"
```

---

## AWS Account Setup

Before deploying, configure your AWS account context:

| Resource | Value | Notes |
|----------|-------|-------|
| User | Your IAM user | Needs `AdministratorAccess` or equivalent |
| VPC | Your target VPC | Private subnets, no IGW required |
| IAM Profile | `skypilot-v1` | Created by `make sky-bootstrap-iam` |

### Subnet Configuration

Ensure your VPC has at least one private subnet authorized for EC2 workloads. If your organization uses Service Control Policies (SCPs), only subnets explicitly allowed by those policies can be used.

Update `devtools/skypilot/contexts/<DEPLOY_CONTEXT>/config.yaml` with your VPC and subnet details.

### AMI Selection

| AMI | Name | Notes |
|-----|------|-------|
| Ubuntu 22.04 LTS | Latest HVM, SSD, amd64 | Recommended base image |

Select an AMI appropriate for your region and organization's image policies.

---

## Commands: What Worked

### 1. Container build

```bash
make sky-build
# Builds adept-skypilot:latest with SkyPilot, CDK, Ansible, AWS CLI
# Cached layers -- fast after first build (~30s)
```

### 2. IAM bootstrap

```bash
make sky-bootstrap-iam
```

Creates `skypilot-v1` instance profile + IAM role with:
- `AmazonEC2FullAccess` (managed policy)
- `AmazonS3FullAccess` (managed policy)
- `SkyPilotPassRolePolicy` (inline: `iam:PassRole` for `skypilot-v1`)

Idempotent -- safe to run multiple times.

### 3. IAM policy simulator

```bash
make sky-simulate-iam
```

Runs `iam simulate-principal-policy` for three action groups (IAM, EC2, S3).

**Limitation**: `simulate-principal-policy` does NOT evaluate AWS Organizations SCPs or resource-level conditions. It only evaluates IAM policies attached to the principal. Use `make sky-dry-run` as the authoritative test.

### 4. EC2 dry-run

```bash
make sky-dry-run
```

Runs `ec2 run-instances --dry-run` with your configured AMI + subnet.

This is the authoritative SCP compliance test. The dry-run hits the real EC2 API path including all org SCPs, unlike the policy simulator.

### 5. Offline validation

```bash
make sky-validate-offline
```

Validates task YAML syntax, schema compliance, and CDK/SkyPilot config parity.

No AWS credentials needed.

### 6. State cleanup

```bash
make sky-clean-state
```

Uses `sudo rm -rf` because SkyPilot container creates root-owned files in the `.sky/` directory.

---

## Commands: Known Limitations

### SkyPilot subnet auto-selection

SkyPilot 0.12.0 has **no `subnet_ids` config field**. When `vpc_name` is set, it discovers ALL subnets in the VPC and picks based on AZ. If your VPC has subnets blocked by SCPs, SkyPilot may hit those first.

**Valid config fields** (SkyPilot 0.12.0 `aws:` section):
```
prioritize_reservations, specific_reservations, disk_encrypted,
ssh_user, security_group_name, vpc_name, vpc_names, use_ssm,
post_provision_runcmd, capabilities, labels, use_internal_ips,
ssh_proxy_command, remote_identity
```

No subnet pinning is possible. SkyPilot does have a retry loop that cycles through subnets, but in restricted environments CDK is more reliable.

---

## CDK vs SkyPilot: Decision Framework

| Factor | CDK | SkyPilot |
|--------|-----|----------|
| Subnet selection | Explicit (hard-coded subnet ID) | Auto-discover (all VPC subnets) |
| AMI | Explicit (hard-coded) | Configurable via `image_id` |
| IAM role | Created per stack | Shared `skypilot-v1` |
| Security group | Created per stack | SkyPilot-managed |
| SSH access | Direct (key from Parameter Store) | SSM or ssh_proxy_command |
| Lifecycle | Manual (`cdk deploy`, `cdk destroy`) | Managed (`sky stop/start/down`) |
| SCP compatibility | Full (targets specific resources) | Partial (auto-discovery conflicts with SCPs) |
| Restricted VPC fit | Excellent (designed for restricted VPCs) | Poor (assumes open infrastructure) |

**Recommendation**: Use CDK for provisioning (it works with restricted VPCs), SkyPilot for lifecycle management of existing instances, and Ansible for OS-level configuration.

---

## SkyPilot Logging Configuration

SkyPilot 0.12.0 has opaque logging by default. The container sets these environment variables:

```dockerfile
ENV SKYPILOT_DEBUG=1
ENV SKY_LOG_LEVEL=DEBUG
```

Internal logs are written to `devtools/skypilot/.sky/api_server/request_logs/` (root-owned inside the container). To read them after a deploy attempt:

```bash
# List log files
sudo ls -la devtools/skypilot/.sky/api_server/request_logs/

# Read a specific request log
sudo cat devtools/skypilot/.sky/api_server/request_logs/*.log
```

---

## Makefile Targets Reference

### CDK (Infrastructure Provisioning)

| Target | What It Does | AWS Creds Needed |
|--------|-------------|------------------|
| `cdk-bootstrap` | One-time CDK setup per AWS account | Yes |
| `cdk-synth` | Generate CloudFormation template (dry-run) | Yes |
| `cdk-diff` | Show diff between deployed and local stack | Yes |
| `cdk-deploy` | Deploy EC2 (interactive, shows diff) | Yes |
| `cdk-deploy-bg` | Deploy EC2 (background, auto-approve) | Yes |
| `cdk-destroy` | Tear down CDK stack | Yes |
| `cdk-get-connection-info` | Show instance IP, SSH command | Yes |
| `cdk-retrieve-key` | Download SSH key from SSM -> `contexts/<ctx>/.ssh/` | Yes |
| `cdk-check-ssm` | Verify SSM connectivity to instance | Yes |
| `cdk-schedule-stop` | Schedule auto-stop (default: 120 min) | Yes |
| `cdk-cancel-stop` | Cancel scheduled auto-stop | Yes |
| `cdk-instance-status` | Unified status: stack/instance/IP/SSM | Yes |

### Ansible (OS Configuration)

| Target | What It Does | AWS Creds Needed |
|--------|-------------|------------------|
| `ansible-prepare-vm` | Configure VM (Docker, Python, ADEPT workspace) | No (SSH only) |
| `ansible-prepare-vm-bg` | Same, background with timestamped log | No (SSH only) |

### Host-Local EC2 Management (SSH-based, no container)

**Source**: `devtools/Makefile.internal` (included into root Makefile via `-include`). Invoke from the **project root**, not from `devtools/skypilot/`.

| Target | What It Does | AWS Creds Needed |
|--------|-------------|------------------|
| `ec2-ping` | Check SSH connectivity + uptime + container count | No (SSH key) |
| `ec2-sync` | Rsync codebase to EC2 (incremental, honors `.gitignore`) | No (SSH key) |
| `ec2-sync-dry` | Rsync dry-run (show what would transfer) | No (SSH key) |
| `ec2-ssh` | Open interactive SSH session | No (SSH key) |
| `ec2-exec` | Run a command on EC2 via SSH | No (SSH key) |
| `ec2-stats` | Docker container stats from EC2 | No (SSH key) |
| `ec2-recreate-service` | Force-recreate a Docker service on EC2 | No (SSH key) |
| `ec2-validate` | Run `make validate` on EC2 | No (SSH key) |

All ec2-* targets require `EC2_HOST=<private-ip>`. SSH key is auto-discovered from `devtools/skypilot/contexts/<DEPLOY_CONTEXT>/.ssh/*.pem`.

### SkyPilot (Lifecycle + Validation)

| Target | What It Does | AWS Creds Needed |
|--------|-------------|------------------|
| `sky-build` | Build the devtools container | No |
| `sky-bootstrap-iam` | Create skypilot-v1 instance profile + role | Yes |
| `sky-simulate-iam` | IAM policy simulator (3 action groups) | Yes |
| `sky-dry-run` | Real EC2 dry-run (SCP compliance test) | Yes |
| `sky-validate-syntax` | YAML lint all task files | No |
| `sky-validate-schema` | JSON schema validation of task YAMLs | No |
| `sky-validate-parity` | Check CDK/SkyPilot config parity | No |
| `sky-validate-offline` | Run all offline validations | No |
| `sky-status` | Show SkyPilot cluster status | Yes |
| `sky-down` | Tear down SkyPilot cluster | Yes |
| `sky-clean-state` | Wipe local SkyPilot state (sudo) | No |
| `sky-list-contexts` | Show available deployment contexts | No |
| `sky-init-context` | Scaffold a new context directory | No |

All targets that need AWS credentials source from your AWS credential configuration.

---

## Troubleshooting

### "Permission denied" on `sky-clean-state`

SkyPilot container runs as root. Use `sudo rm -rf devtools/skypilot/.sky/` or the Makefile target which includes sudo.

### "Found unsupported field" in config.yaml

Check `devtools/skypilot/config.yaml` against valid fields listed above. SkyPilot 0.12.0 does not support `subnet_ids`.

### "explicit deny in service control policy"

If your organization uses SCPs that restrict which subnets can launch EC2 instances, use CDK (which targets specific subnets) instead of SkyPilot (which auto-discovers all subnets).

### IAM simulator shows "implicitDeny" but dry-run passes

Normal. The simulator doesn't evaluate SCPs or resource conditions. Use `make sky-dry-run` as the authoritative test.

### Stale cluster state after failed deploy

```bash
make sky-clean-state    # Wipes devtools/skypilot/.sky/
make sky-deploy-aws-bg  # Fresh deploy
```

---

## Log Files

All operations produce timestamped logs in `logs/`:

| Log Pattern | Source |
|-------------|--------|
| `sky_deploy_aws_*.log` | `make sky-deploy-aws-bg` output |
| `sky_bootstrap_iam_*.log` | `make sky-bootstrap-iam` output |
| `sky_container_rebuild_*.log` | Container rebuild output |

SkyPilot internal logs: `devtools/skypilot/.sky/api_server/request_logs/` (root-owned, use sudo to read).
