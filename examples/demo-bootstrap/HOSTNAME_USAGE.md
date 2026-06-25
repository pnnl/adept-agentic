# Understanding HOSTNAME in Generated Scripts

**Critical Concept**: The bootstrap container generates **template scripts** with shell variables. You must understand how `HOSTNAME` works to use the artifacts correctly.

---

## How HOSTNAME Works

### 1. What You Pass to Bootstrap Container

When you run the bootstrap container, you provide the actual hostname:

```bash
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap deploy \
  --hostname vm1.api.agentic.local \    # <-- YOUR actual hostname
  --peer-hostname vm2.api.agentic.local \
  --vm1-ip 192.168.1.100 \
  --vm2-ip 192.168.1.101 \
  --email admin@example.com
```

### 2. What Gets Generated (Shell Scripts)

The generated scripts use shell variables:

**File**: `output/scripts/apply-certificates.sh`
```bash
#!/bin/bash
HOSTNAME="vm1.api.agentic.local"    # <-- Set from your input
ADEPT_ROOT="${1:-$(pwd)}"
SOURCE_DIR="$(dirname "$0")/../certs"
DEST_DIR="${ADEPT_ROOT}/deployment/local/docker-compose/certs"

# Copy certificates (uses ${HOSTNAME} variable)
cp "${SOURCE_DIR}/${HOSTNAME}.crt" "${DEST_DIR}/${HOSTNAME}.crt"
cp "${SOURCE_DIR}/${HOSTNAME}.key" "${DEST_DIR}/${HOSTNAME}.key"
```

**Key Point**: `${HOSTNAME}` is a **shell variable** that gets expanded when you **run** the script on the VM, not when you generate it.

### 3. What You Copy to VMs

You copy the entire artifact directory:

```bash
scp -r examples/demo-bootstrap/output/ user@vm1:/tmp/adept-artifacts
```

This includes:
- Scripts with `HOSTNAME="vm1.api.agentic.local"` hardcoded
- Certificate files named `vm1.api.agentic.local.crt`
- Config files with the hostname

### 4. What Happens on the VM

When you run the script on the VM:

```bash
cd /tmp/adept-artifacts
./scripts/apply-certificates.sh /path/to/adept
```

The shell expands `${HOSTNAME}`:
1. Sets `HOSTNAME="vm1.api.agentic.local"`
2. Expands `${HOSTNAME}.crt` → `vm1.api.agentic.local.crt`
3. Copies `vm1.api.agentic.local.crt` to ADEPT directory

---

## Example Workflow

### Scenario: Two VMs with Different Hostnames

**Your Infrastructure**:
- VM1: `prod-gateway-east.example.com` (IP: 10.0.1.100)
- VM2: `prod-gateway-west.example.com` (IP: 10.0.2.200)

### Step 1: Generate VM1 Artifacts

```bash
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap deploy \
  --hostname prod-gateway-east.example.com \       # <-- YOUR VM1 hostname
  --peer-hostname prod-gateway-west.example.com \  # <-- YOUR VM2 hostname
  --vm1-ip 10.0.1.100 \
  --vm2-ip 10.0.2.200 \
  --email admin@example.com
```

**Generated**: `output/scripts/apply-certificates.sh` with:
```bash
HOSTNAME="prod-gateway-east.example.com"
cp "${SOURCE_DIR}/${HOSTNAME}.crt" "${DEST_DIR}/${HOSTNAME}.crt"
```

### Step 2: Generate VM2 Artifacts

```bash
# Move VM1 artifacts aside
mv examples/demo-bootstrap/output examples/demo-bootstrap/output-vm1

# Generate VM2 artifacts
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap deploy \
  --hostname prod-gateway-west.example.com \       # <-- YOUR VM2 hostname
  --peer-hostname prod-gateway-east.example.com \  # <-- YOUR VM1 hostname
  --vm1-ip 10.0.1.100 \
  --vm2-ip 10.0.2.200 \
  --email admin@example.com

# Move VM2 artifacts
mv examples/demo-bootstrap/output examples/demo-bootstrap/output-vm2
```

**Generated**: `output/scripts/apply-certificates.sh` with:
```bash
HOSTNAME="prod-gateway-west.example.com"  # <-- Different!
cp "${SOURCE_DIR}/${HOSTNAME}.crt" "${DEST_DIR}/${HOSTNAME}.crt"
```

### Step 3: Apply on VM1

```bash
scp -r output-vm1/ user@prod-gateway-east.example.com:/tmp/artifacts
ssh user@prod-gateway-east.example.com

cd /tmp/artifacts
./scripts/apply-certificates.sh /opt/adept
```

**What Happens**:
- Shell reads `HOSTNAME="prod-gateway-east.example.com"`
- Expands `${HOSTNAME}.crt` → `prod-gateway-east.example.com.crt`
- Copies correct certificate for THIS VM

---

## Common Mistakes

### ❌ Mistake 1: Using Same Artifacts for Both VMs

**Problem**: You generate artifacts once and try to use them on both VMs.

**Why It Fails**: The `HOSTNAME` variable is hardcoded to one value. VM2 will try to copy `vm1.api.agentic.local.crt` which doesn't exist on VM2.

**Solution**: Generate separate artifacts for each VM with its specific hostname.

### ❌ Mistake 2: Not Understanding ${HOSTNAME} Expansion

**Problem**: You see `${HOSTNAME}.crt` in the script and think it's broken.

**Why It's Correct**: This is shell variable syntax. When the script runs, bash expands `${HOSTNAME}` to the actual value.

**Test It**:
```bash
# On VM1 with artifacts applied
HOSTNAME="vm1.api.agentic.local"
echo "${HOSTNAME}.crt"
# Output: vm1.api.agentic.local.crt
```

### ❌ Mistake 3: Forgetting to Replace Example Values

**Problem**: You copy-paste commands with `vm1.api.agentic.local` without changing them.

**Why It Fails**: The bootstrap creates artifacts for `vm1.api.agentic.local`, but your actual VM has a different hostname.

**Solution**: Always replace example values with YOUR actual infrastructure details.

---

## Testing HOSTNAME Expansion

### Verify Generated Script

```bash
# After generating artifacts
cat examples/demo-bootstrap/output/scripts/apply-certificates.sh

# Look for:
# HOSTNAME="your-actual-hostname"
# ${HOSTNAME}.crt
# ${HOSTNAME}.key
```

### Test Shell Expansion Locally

```bash
# Simulate what the script does
HOSTNAME="vm1.api.agentic.local"
echo "Certificate: ${HOSTNAME}.crt"
echo "Key: ${HOSTNAME}.key"

# Output:
# Certificate: vm1.api.agentic.local.crt
# Key: vm1.api.agentic.local.key
```

### Verify on Target VM

```bash
# On VM1 after copying artifacts
cd /tmp/adept-artifacts

# Check the HOSTNAME value
grep 'HOSTNAME=' scripts/apply-certificates.sh
# Should show: HOSTNAME="vm1.api.agentic.local"

# Check certificate files exist
ls -la certs/vm1.api.agentic.local.*
# Should show: vm1.api.agentic.local.crt, vm1.api.agentic.local.key
```

---

## Quick Reference

### Bootstrap Invocation Pattern

```bash
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap deploy \
  --hostname YOUR_VM_HOSTNAME \           # <-- REPLACE
  --peer-hostname YOUR_PEER_HOSTNAME \    # <-- REPLACE
  --vm1-ip YOUR_VM1_IP \                  # <-- REPLACE
  --vm2-ip YOUR_VM2_IP \                  # <-- REPLACE
  --email YOUR_EMAIL                      # <-- REPLACE
```

### What Each Parameter Controls

| Parameter | What It Does | Example |
|-----------|--------------|---------|
| `--hostname` | Sets `HOSTNAME` variable in generated scripts | `vm1.api.agentic.local` |
| `--peer-hostname` | Used in A2A registration artifacts | `vm2.api.agentic.local` |
| `--vm1-ip` | IP address for /etc/hosts entry | `192.168.1.100` |
| `--vm2-ip` | IP address for /etc/hosts entry | `192.168.1.101` |
| `--email` | Let's Encrypt notification email | `admin@example.com` |

### Generated Artifact Naming

| Input | Generated Artifact | Location |
|-------|-------------------|----------|
| `--hostname vm1.example.com` | `HOSTNAME="vm1.example.com"` | All shell scripts |
| `--hostname vm1.example.com` | `vm1.example.com.crt` | `output/certs/` |
| `--hostname vm1.example.com` | `vm1.example.com.key` | `output/certs/` |
| `--peer-hostname vm2.example.com` | `register-vm2-gateway.sh` | `output/a2a/` |

---

## Troubleshooting

### "Certificate file not found"

**Error**:
```
cp: cannot stat 'certs/vm1.api.agentic.local.crt': No such file or directory
```

**Cause**: The `HOSTNAME` variable in the script doesn't match your actual certificate filename.

**Solution**:
1. Check what hostname you passed to bootstrap: `grep HOSTNAME= scripts/apply-certificates.sh`
2. Check what certificate files exist: `ls -la certs/`
3. Regenerate artifacts with correct `--hostname` value

### "Script uses wrong hostname"

**Error**: Script tries to copy `vm1.api.agentic.local.crt` but your VM is `prod-east.example.com`

**Cause**: You used example values instead of your actual hostname when generating artifacts.

**Solution**: Regenerate artifacts with YOUR actual hostname:
```bash
docker compose -f examples/demo-bootstrap/docker-compose.bootstrap.yaml \
  --profile bootstrap run --rm demo_bootstrap deploy \
  --hostname prod-east.example.com \    # <-- Your actual hostname
  ...
```

### "Can I change HOSTNAME after generation?"

**No** - Don't manually edit generated scripts. Regenerate with correct values instead.

**Why**: The bootstrap ensures all artifacts are consistent. Manual edits break this consistency.

---

**Last Updated**: 2026-02-09
**Key Takeaway**: `--hostname` you pass → `HOSTNAME` in scripts → `${HOSTNAME}` expands when script runs on VM
