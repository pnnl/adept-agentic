"""SSH key lifecycle management for HPC cluster access.

Handles key generation, status checking, and connectivity verification.
Key material (private keys) is NEVER returned in tool responses — only
metadata (path existence, fingerprint prefix, age, connectivity status).
"""

import logging
import os
import stat
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_CLUSTERS_YAML = Path(__file__).parent / "clusters.yaml"


@dataclass
class KeyStatus:
    """Status of an SSH key pair (no key material exposed)."""

    cluster: str
    private_key_exists: bool
    public_key_exists: bool
    private_key_path: str
    public_key_path: str
    algorithm: str
    fingerprint_prefix: str = ""
    created_at: Optional[str] = None
    age_days: Optional[int] = None
    rotation_due: bool = False
    permissions_ok: bool = False
    connectivity_tested: bool = False
    connectivity_ok: bool = False
    errors: List[str] = field(default_factory=list)


@dataclass
class ClusterKeyConfig:
    """Parsed cluster SSH key configuration from YAML."""

    cluster_name: str
    display_name: str
    host: str
    ssh_port: int
    username: str
    private_key_path: Path
    public_key_path: Path
    algorithm: str
    comment: str
    provisioning: str
    transport_modes: List[str]
    working_directory: str


def load_clusters_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load clusters.yaml configuration."""
    path = config_path or _CLUSTERS_YAML
    if not path.exists():
        raise FileNotFoundError(f"Cluster config not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def get_cluster_key_configs(
    config_path: Optional[Path] = None,
    username_override: Optional[str] = None,
) -> Dict[str, ClusterKeyConfig]:
    """Parse cluster configs into structured objects.

    The {username} placeholder in key paths is resolved using either
    username_override or the cluster's configured username.
    """
    raw = load_clusters_config(config_path)
    clusters = raw.get("clusters", {})
    result = {}
    for name, cfg in clusters.items():
        ssh_key = cfg.get("ssh_key", {})
        username = username_override or cfg.get("username", "")
        priv_path = ssh_key["private_key_path"].format(username=username)
        pub_path = ssh_key["public_key_path"].format(username=username)
        result[name] = ClusterKeyConfig(
            cluster_name=name,
            display_name=cfg.get("display_name", name),
            host=cfg["host"],
            ssh_port=cfg.get("ssh_port", 22),
            username=username,
            private_key_path=Path(priv_path).expanduser(),
            public_key_path=Path(pub_path).expanduser(),
            algorithm=ssh_key.get("algorithm", "ed25519"),
            comment=ssh_key.get("comment", "adept-mcp"),
            provisioning=ssh_key.get("provisioning", "manual_authorized_keys"),
            transport_modes=cfg.get("transport_modes", ["ssh"]),
            working_directory=cfg.get("working_directory", f"/scratch/{username}"),
        )
    return result


def get_key_policy(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the key policy section from clusters.yaml."""
    raw = load_clusters_config(config_path)
    return raw.get("key_policy", {})


def check_key_status(cluster_name: str, config_path: Optional[Path] = None) -> KeyStatus:
    """Check the status of an SSH key pair for a cluster.

    Returns metadata only — NEVER key material.
    """
    configs = get_cluster_key_configs(config_path)
    if cluster_name not in configs:
        return KeyStatus(
            cluster=cluster_name,
            private_key_exists=False,
            public_key_exists=False,
            private_key_path="",
            public_key_path="",
            algorithm="unknown",
            errors=[f"Unknown cluster: {cluster_name}"],
        )

    cfg = configs[cluster_name]
    policy = get_key_policy(config_path)

    priv_exists = cfg.private_key_path.exists()
    pub_exists = cfg.public_key_path.exists()

    status = KeyStatus(
        cluster=cluster_name,
        private_key_exists=priv_exists,
        public_key_exists=pub_exists,
        private_key_path=str(cfg.private_key_path),
        public_key_path=str(cfg.public_key_path),
        algorithm=cfg.algorithm,
    )

    if not priv_exists:
        status.errors.append("Private key file does not exist")
        return status

    # Check permissions (should be 0600)
    perms = oct(cfg.private_key_path.stat().st_mode & 0o777)
    status.permissions_ok = perms == "0o600"
    if not status.permissions_ok:
        status.errors.append(f"Private key permissions are {perms}, should be 0600")

    # Check age
    mtime = cfg.private_key_path.stat().st_mtime
    created = datetime.fromtimestamp(mtime, tz=timezone.utc)
    status.created_at = created.isoformat()
    age = (datetime.now(tz=timezone.utc) - created).days
    status.age_days = age
    rotation_days = policy.get("rotation_reminder_days", 365)
    status.rotation_due = age > rotation_days

    # Get fingerprint prefix (first 12 chars of SHA256 fingerprint)
    if pub_exists:
        try:
            result = subprocess.run(
                ["ssh-keygen", "-lf", str(cfg.public_key_path)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Output: "256 SHA256:abcdef... comment (ED25519)"
                parts = result.stdout.strip().split()
                if len(parts) >= 2:
                    fp = parts[1]
                    # Show only first 12 chars after "SHA256:"
                    if fp.startswith("SHA256:"):
                        status.fingerprint_prefix = fp[:19] + "..."
                    else:
                        status.fingerprint_prefix = fp[:12] + "..."
        except Exception:
            pass

    return status


def generate_key_pair(
    cluster_name: str, config_path: Optional[Path] = None, overwrite: bool = False
) -> Dict[str, Any]:
    """Generate an SSH key pair for a cluster.

    Returns metadata about the generated key (path, fingerprint prefix)
    but NEVER the private key material itself.
    """
    configs = get_cluster_key_configs(config_path)
    if cluster_name not in configs:
        return {"success": False, "error": f"Unknown cluster: {cluster_name}"}

    cfg = configs[cluster_name]

    if cfg.private_key_path.exists() and not overwrite:
        return {
            "success": False,
            "error": f"Key already exists at {cfg.private_key_path}. Use overwrite=True to replace.",
        }

    # Ensure parent directory exists
    cfg.private_key_path.parent.mkdir(parents=True, exist_ok=True)

    # Build ssh-keygen command
    algo_args = []
    if cfg.algorithm == "ed25519":
        algo_args = ["-t", "ed25519"]
    elif cfg.algorithm == "ecdsa":
        algo_args = ["-t", "ecdsa", "-b", "521"]
    elif cfg.algorithm == "rsa":
        policy = get_key_policy(config_path)
        bits = str(policy.get("min_rsa_bits", 4096))
        algo_args = ["-t", "rsa", "-b", bits]
    else:
        return {"success": False, "error": f"Unsupported algorithm: {cfg.algorithm}"}

    cmd = [
        "ssh-keygen",
        *algo_args,
        "-f",
        str(cfg.private_key_path),
        "-N",
        "",  # No passphrase (agent manages lifecycle)
        "-C",
        cfg.comment,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return {"success": False, "error": result.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "ssh-keygen timed out"}

    # Set proper permissions
    os.chmod(cfg.private_key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600

    # Get public key content for the user to copy
    pub_content = cfg.public_key_path.read_text().strip() if cfg.public_key_path.exists() else ""

    # Get fingerprint
    fp_result = subprocess.run(
        ["ssh-keygen", "-lf", str(cfg.public_key_path)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    fingerprint = fp_result.stdout.strip() if fp_result.returncode == 0 else ""

    return {
        "success": True,
        "cluster": cluster_name,
        "private_key_path": str(cfg.private_key_path),
        "public_key_path": str(cfg.public_key_path),
        "algorithm": cfg.algorithm,
        "fingerprint": fingerprint,
        "public_key": pub_content,
        "provisioning": cfg.provisioning,
        "instructions": _provisioning_instructions(cfg, pub_content),
    }


def test_connectivity(cluster_name: str, config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Test SSH connectivity to a cluster using the configured key.

    Does NOT expose key material. Returns connection status only.
    """
    configs = get_cluster_key_configs(config_path)
    if cluster_name not in configs:
        return {"success": False, "error": f"Unknown cluster: {cluster_name}"}

    cfg = configs[cluster_name]

    if not cfg.private_key_path.exists():
        return {
            "success": False,
            "error": f"No private key at {cfg.private_key_path}. Run key generation first.",
        }

    policy = get_key_policy(config_path)
    strict = policy.get("strict_host_key_checking", True)
    known_hosts = Path(policy.get("known_hosts_path", "~/.ssh/known_hosts")).expanduser()

    ssh_opts = [
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", f"StrictHostKeyChecking={'yes' if strict else 'accept-new'}",
        "-i", str(cfg.private_key_path),
        "-p", str(cfg.ssh_port),
    ]
    if known_hosts.exists():
        ssh_opts.extend(["-o", f"UserKnownHostsFile={known_hosts}"])

    cmd = ["ssh", *ssh_opts, f"{cfg.username}@{cfg.host}", "echo ADEPT_CONNECTIVITY_OK"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        connected = result.returncode == 0 and "ADEPT_CONNECTIVITY_OK" in result.stdout
        return {
            "success": connected,
            "cluster": cluster_name,
            "host": cfg.host,
            "username": cfg.username,
            "message": "Connected successfully" if connected else result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "cluster": cluster_name,
            "host": cfg.host,
            "error": "SSH connection timed out (10s)",
        }


def _provisioning_instructions(cfg: ClusterKeyConfig, pub_key: str) -> str:
    """Generate user instructions for provisioning the key on the remote cluster."""
    if cfg.provisioning == "manual_authorized_keys":
        return (
            f"To complete setup, add this public key to your authorized_keys on {cfg.display_name}:\n"
            f"\n"
            f"1. SSH into {cfg.host} with your existing credentials:\n"
            f"   ssh {cfg.username}@{cfg.host}\n"
            f"\n"
            f"2. Append the public key:\n"
            f"   echo '{pub_key}' >> ~/.ssh/authorized_keys\n"
            f"\n"
            f"3. Ensure correct permissions:\n"
            f"   chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys\n"
            f"\n"
            f"4. Test connectivity from this machine:\n"
            f"   ssh -i {cfg.private_key_path} {cfg.username}@{cfg.host} hostname"
        )
    return "Unknown provisioning method."
