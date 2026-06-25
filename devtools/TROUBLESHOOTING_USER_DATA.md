# Troubleshooting EC2 User-Data Script Execution

## Quick Diagnostics (Run on EC2 Instance)

```bash
# 1. Check if cloud-init ran at all
sudo cloud-init status

# Expected outputs:
# - "status: done" = Cloud-init completed successfully
# - "status: running" = Still executing
# - "status: error" = Failed with errors
# - "status: disabled" = Cloud-init not enabled

# 2. Check cloud-init logs
sudo tail -100 /var/log/cloud-init.log
sudo tail -100 /var/log/cloud-init-output.log

# 3. Check our custom user-data log
sudo tail -100 /var/log/user-data.log
# If this file doesn't exist, user-data script never started

# 4. Check for errors in cloud-init
sudo journalctl -u cloud-init -n 100

# 5. Check if user-data was received by instance
sudo cat /var/lib/cloud/instance/user-data.txt | head -50
# Should show the bash script starting with "#!/bin/bash"

# 6. Force re-run cloud-init (if needed)
sudo cloud-init clean --logs
sudo cloud-init init
sudo cloud-init modules --mode config
sudo cloud-init modules --mode final
```

## Common Issues and Fixes

### Issue 1: Cloud-Init Not Enabled
**Symptom**: `cloud-init status` returns "disabled" or command not found

**Fix**:
```bash
# Install cloud-init
sudo apt-get update
sudo apt-get install -y cloud-init

# Enable and start
sudo systemctl enable cloud-init
sudo systemctl start cloud-init
```

### Issue 2: User-Data Script Has Errors
**Symptom**: `/var/log/cloud-init-output.log` shows bash errors

**Fix**: Check the script for syntax errors
```bash
sudo grep -i error /var/log/cloud-init-output.log
sudo grep -i failed /var/log/cloud-init-output.log
```

### Issue 3: No Internet Access
**Symptom**: Script fails at `apt-get update` or package installation

**Fix**: Check network connectivity
```bash
# Check internet access
ping -c 3 8.8.8.8
curl -I https://archive.ubuntu.com

# Check DNS
nslookup archive.ubuntu.com

# Check security group allows outbound traffic
aws ec2 describe-security-groups --group-ids <YOUR_SG_ID>
```

### Issue 4: Data Volume Not Attached
**Symptom**: Script hangs waiting for `/dev/nvme1n1` or `/dev/xvdf`

**Check**:
```bash
# List block devices
lsblk

# Check if data volume attached
ls -la /dev/nvme1n1  # For NVMe instances
ls -la /dev/xvdf     # For older instance types

# Check AWS console for volume attachment state
```

### Issue 5: AMI Doesn't Support Cloud-Init
**Symptom**: Cloud-init service not present

**Fix**: Use Ubuntu AMI (not minimal AMI)
- Ubuntu Server 22.04 LTS (ami-0c2ab3b8efb09f272)
- Verify AMI has cloud-init pre-installed

## Manual Bootstrap (If User-Data Failed)

If cloud-init failed completely, run the provisioning manually:

```bash
# 1. Become root
sudo su -

# 2. Update system
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

# 3. Format and mount data volume (if not done)
# Check if /data exists
mount | grep /data

# If not mounted:
DEVICE=/dev/nvme1n1  # or /dev/xvdf for older instances
mkfs -t ext4 $DEVICE
mkdir -p /data
mount $DEVICE /data
echo "$DEVICE /data ext4 defaults,nofail 0 2" >> /etc/fstab

# 4. Install Python 3.11
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update
apt-get install -y python3.11 python3.11-venv python3.11-dev
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# 5. Install Docker
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
sh /tmp/get-docker.sh
usermod -aG docker ubuntu
systemctl enable docker
systemctl start docker

# 6. Configure Docker permissions (for sandbox_mcp_server)
chmod 2777 /var/run/docker
chmod 777 /var/run/docker.sock
mkdir -p /var/lib/docker/containerd
chmod 2777 /var/lib/docker/containerd

# 7. Install UV package manager
curl -LsSf https://astral.sh/uv/install.sh | sh
echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> /home/ubuntu/.bashrc

# 8. Install AWS CLI v2
cd /tmp
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
apt-get install -y unzip
unzip awscliv2.zip
./aws/install

# 9. Install Node.js 18 (for CDK)
curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
apt-get install -y nodejs

# 10. Fix ownership
chown -R ubuntu:ubuntu /data
chown -R ubuntu:ubuntu /home/ubuntu

# 11. Exit root
exit

# 12. Continue with bootstrap script (as ubuntu user)
cd /data
# Follow bootstrap instructions from main deployment guide
```

## Verification After Fix

```bash
# Check all components installed
python3 --version        # Should be 3.11.x
docker --version         # Should be 20.10+
uv --version            # Should be latest
aws --version           # Should be 2.x
node --version          # Should be v18.x

# Check data volume mounted
df -h | grep /data      # Should show 500GB volume

# Check Docker working
docker ps               # Should list containers (or empty if none running)
docker run hello-world  # Should pull and run test container
```

## Prevention for Next Deployment

### Option 1: Use Custom AMI with Packer
Build AMI with all software pre-installed (saves 5-10 minutes on boot):

```bash
cd devtools/packer
./build-ami.sh 1.0.0
# Use resulting AMI ID in CDK deployment
```

### Option 2: Simplify User-Data Script
Split into two phases:
- Phase 1 (user-data): Minimal setup (mount volume, install cloud-init)
- Phase 2 (bootstrap script): Full provisioning via SSH

### Option 3: Use AWS Systems Manager Run Command
Instead of user-data, deploy with minimal AMI, then run provisioning via SSM:

```bash
aws ssm send-command \
  --instance-ids i-1234567890abcdef0 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["#!/bin/bash", "apt-get update", ...]'
```

## Getting Help

If issues persist:
1. Collect logs: `tar -czf debug-logs.tar.gz /var/log/cloud-*.log /var/log/user-data.log`
2. Share instance ID, AMI ID, and region
3. Share CDK deployment command used
4. Share security group rules (inbound/outbound)

## Related Documentation
- AWS Cloud-Init: https://cloudinit.readthedocs.io/
- EC2 User Data: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/user-data.html
- Troubleshooting: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-troubleshoot.html
