"""
Unit Tests: Certificate Generation Script
==========================================

Tests for scripts/generate-ca-and-certs.sh.
Validates CA and server certificate generation, permissions,
idempotency, and SAN entries.

Prerequisites:
    - openssl CLI available
    - bash available

Usage:
    pytest tests/unit/test_generate_certs.py -v
"""

import os
import shutil
import subprocess
import tempfile

import pytest

# Path to the generate script (relative to project root)
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
GENERATE_SCRIPT = os.path.join(SCRIPT_DIR, "generate-ca-and-certs.sh")


@pytest.fixture
def cert_workdir():
    """Create a temporary working directory that mimics the project layout."""
    tmpdir = tempfile.mkdtemp(prefix="slurm_cert_test_")
    # Create scripts/ directory and copy the generate script
    scripts_dir = os.path.join(tmpdir, "scripts")
    os.makedirs(scripts_dir)
    shutil.copy2(GENERATE_SCRIPT, scripts_dir)
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


def _has_openssl():
    """Check if openssl is available."""
    try:
        subprocess.run(
            ["openssl", "version"],
            capture_output=True,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _has_bash():
    """Check if bash is available."""
    try:
        subprocess.run(
            ["bash", "--version"],
            capture_output=True,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_generate(workdir, env_overrides=None):
    """Run the generate-ca-and-certs.sh script in the given workdir."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    script_path = os.path.join(workdir, "scripts", "generate-ca-and-certs.sh")
    result = subprocess.run(
        ["bash", script_path],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result


@pytest.mark.skipif(not _has_openssl(), reason="openssl not available")
@pytest.mark.skipif(not _has_bash(), reason="bash not available")
class TestCertificateGeneration:
    """Validate generate-ca-and-certs.sh produces correct certificates."""

    def test_requires_slurm_host_ip(self, cert_workdir):
        """Script fails with clear error when SLURM_HOST_IP is not set."""
        result = _run_generate(cert_workdir, {"SLURM_HOST_IP": ""})
        assert result.returncode != 0
        assert "SLURM_HOST_IP is required" in result.stderr or "SLURM_HOST_IP is required" in result.stdout

    def test_generates_four_files(self, cert_workdir):
        """Script generates ca.key, ca.crt, slurm.key, slurm.crt."""
        result = _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        certs_dir = os.path.join(cert_workdir, "certs")
        assert os.path.isfile(os.path.join(certs_dir, "ca.key")), "Missing ca.key"
        assert os.path.isfile(os.path.join(certs_dir, "ca.crt")), "Missing ca.crt"
        assert os.path.isfile(os.path.join(certs_dir, "slurm.key")), "Missing slurm.key"
        assert os.path.isfile(os.path.join(certs_dir, "slurm.crt")), "Missing slurm.crt"

    def test_no_intermediate_files(self, cert_workdir):
        """Script cleans up intermediate files (CSR, ext, srl)."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        certs_dir = os.path.join(cert_workdir, "certs")
        assert not os.path.exists(os.path.join(certs_dir, "slurm.csr"))
        assert not os.path.exists(os.path.join(certs_dir, "slurm.ext"))
        assert not os.path.exists(os.path.join(certs_dir, "ca.srl"))

    def test_key_permissions_restrictive(self, cert_workdir):
        """Private keys have 600 permissions."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        certs_dir = os.path.join(cert_workdir, "certs")
        ca_key_mode = oct(os.stat(os.path.join(certs_dir, "ca.key")).st_mode)[-3:]
        slurm_key_mode = oct(os.stat(os.path.join(certs_dir, "slurm.key")).st_mode)[-3:]
        assert ca_key_mode == "600", f"ca.key permissions: {ca_key_mode}"
        assert slurm_key_mode == "600", f"slurm.key permissions: {slurm_key_mode}"

    def test_cert_permissions_readable(self, cert_workdir):
        """Certificates have 644 permissions."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        certs_dir = os.path.join(cert_workdir, "certs")
        ca_crt_mode = oct(os.stat(os.path.join(certs_dir, "ca.crt")).st_mode)[-3:]
        slurm_crt_mode = oct(os.stat(os.path.join(certs_dir, "slurm.crt")).st_mode)[-3:]
        assert ca_crt_mode == "644", f"ca.crt permissions: {ca_crt_mode}"
        assert slurm_crt_mode == "644", f"slurm.crt permissions: {slurm_crt_mode}"

    def test_ca_cert_is_valid_x509(self, cert_workdir):
        """CA certificate is a valid X.509 certificate."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        ca_crt = os.path.join(cert_workdir, "certs", "ca.crt")
        result = subprocess.run(
            ["openssl", "x509", "-in", ca_crt, "-noout", "-subject"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "Slurm HPC CA" in result.stdout

    def test_ca_cert_is_ca(self, cert_workdir):
        """CA certificate has CA:TRUE basic constraint."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        ca_crt = os.path.join(cert_workdir, "certs", "ca.crt")
        result = subprocess.run(
            ["openssl", "x509", "-in", ca_crt, "-noout", "-text"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "CA:TRUE" in result.stdout

    def test_server_cert_signed_by_ca(self, cert_workdir):
        """Server certificate is signed by the CA."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        certs_dir = os.path.join(cert_workdir, "certs")
        result = subprocess.run(
            [
                "openssl", "verify",
                "-CAfile", os.path.join(certs_dir, "ca.crt"),
                os.path.join(certs_dir, "slurm.crt"),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_server_cert_cn(self, cert_workdir):
        """Server certificate CN is slurm_nginx_proxy."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        slurm_crt = os.path.join(cert_workdir, "certs", "slurm.crt")
        result = subprocess.run(
            ["openssl", "x509", "-in", slurm_crt, "-noout", "-subject"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "slurm_nginx_proxy" in result.stdout

    def test_server_cert_san_contains_host_ip(self, cert_workdir):
        """Server certificate SAN contains the specified host IP."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        slurm_crt = os.path.join(cert_workdir, "certs", "slurm.crt")
        result = subprocess.run(
            ["openssl", "x509", "-in", slurm_crt, "-noout", "-text"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "IP Address:10.0.0.1" in result.stdout

    def test_server_cert_san_contains_container_hostname(self, cert_workdir):
        """Server certificate SAN contains DNS:slurm_nginx_proxy."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        slurm_crt = os.path.join(cert_workdir, "certs", "slurm.crt")
        result = subprocess.run(
            ["openssl", "x509", "-in", slurm_crt, "-noout", "-text"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "DNS:slurm_nginx_proxy" in result.stdout

    def test_server_cert_san_contains_localhost(self, cert_workdir):
        """Server certificate SAN contains DNS:localhost and IP:127.0.0.1."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        slurm_crt = os.path.join(cert_workdir, "certs", "slurm.crt")
        result = subprocess.run(
            ["openssl", "x509", "-in", slurm_crt, "-noout", "-text"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "DNS:localhost" in result.stdout
        assert "IP Address:127.0.0.1" in result.stdout

    def test_server_cert_not_ca(self, cert_workdir):
        """Server certificate has CA:FALSE basic constraint."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        slurm_crt = os.path.join(cert_workdir, "certs", "slurm.crt")
        result = subprocess.run(
            ["openssl", "x509", "-in", slurm_crt, "-noout", "-text"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "CA:FALSE" in result.stdout


@pytest.mark.skipif(not _has_openssl(), reason="openssl not available")
@pytest.mark.skipif(not _has_bash(), reason="bash not available")
class TestCertificateIdempotency:
    """Validate the idempotency behavior of generate-ca-and-certs.sh."""

    def test_skip_if_certs_valid(self, cert_workdir):
        """Second run skips generation when certs are still valid."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})

        # Get modification time of slurm.crt after first generation
        certs_dir = os.path.join(cert_workdir, "certs")
        first_mtime = os.stat(os.path.join(certs_dir, "slurm.crt")).st_mtime

        # Second run should skip
        result = _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        assert result.returncode == 0
        assert "Certs exist and are valid" in result.stdout

        # File should not be modified
        second_mtime = os.stat(os.path.join(certs_dir, "slurm.crt")).st_mtime
        assert first_mtime == second_mtime

    def test_preserves_ca_on_server_cert_regeneration(self, cert_workdir):
        """Deleting only server cert regenerates it using existing CA."""
        _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        certs_dir = os.path.join(cert_workdir, "certs")

        # Record CA fingerprint
        ca_result = subprocess.run(
            ["openssl", "x509", "-in", os.path.join(certs_dir, "ca.crt"), "-noout", "-fingerprint"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        ca_fingerprint = ca_result.stdout.strip()

        # Delete server cert + key to trigger regeneration
        os.remove(os.path.join(certs_dir, "slurm.crt"))
        os.remove(os.path.join(certs_dir, "slurm.key"))

        # Regenerate
        result = _run_generate(cert_workdir, {"SLURM_HOST_IP": "10.0.0.1"})
        assert result.returncode == 0

        # CA should be unchanged
        ca_result2 = subprocess.run(
            ["openssl", "x509", "-in", os.path.join(certs_dir, "ca.crt"), "-noout", "-fingerprint"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert ca_result2.stdout.strip() == ca_fingerprint

        # Server cert should exist and be valid
        assert os.path.isfile(os.path.join(certs_dir, "slurm.crt"))
        verify_result = subprocess.run(
            ["openssl", "verify", "-CAfile", os.path.join(certs_dir, "ca.crt"),
             os.path.join(certs_dir, "slurm.crt")],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "OK" in verify_result.stdout


@pytest.mark.skipif(not _has_openssl(), reason="openssl not available")
@pytest.mark.skipif(not _has_bash(), reason="bash not available")
class TestExtraSANEntries:
    """Validate extra DNS and IP SAN entries."""

    def test_extra_dns_entry(self, cert_workdir):
        """SLURM_EXTRA_DNS adds DNS SAN entries."""
        _run_generate(cert_workdir, {
            "SLURM_HOST_IP": "10.0.0.1",
            "SLURM_EXTRA_DNS": "slurm.lab.example.com",
        })
        slurm_crt = os.path.join(cert_workdir, "certs", "slurm.crt")
        result = subprocess.run(
            ["openssl", "x509", "-in", slurm_crt, "-noout", "-text"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "DNS:slurm.lab.example.com" in result.stdout

    def test_extra_ip_entry(self, cert_workdir):
        """SLURM_EXTRA_IPS adds IP SAN entries."""
        _run_generate(cert_workdir, {
            "SLURM_HOST_IP": "10.0.0.1",
            "SLURM_EXTRA_IPS": "192.168.1.100",
        })
        slurm_crt = os.path.join(cert_workdir, "certs", "slurm.crt")
        result = subprocess.run(
            ["openssl", "x509", "-in", slurm_crt, "-noout", "-text"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "IP Address:192.168.1.100" in result.stdout

    def test_multiple_extra_entries(self, cert_workdir):
        """Multiple comma-separated extras are all included."""
        _run_generate(cert_workdir, {
            "SLURM_HOST_IP": "10.0.0.1",
            "SLURM_EXTRA_DNS": "a.example.com,b.example.com",
            "SLURM_EXTRA_IPS": "192.168.1.1,192.168.1.2",
        })
        slurm_crt = os.path.join(cert_workdir, "certs", "slurm.crt")
        result = subprocess.run(
            ["openssl", "x509", "-in", slurm_crt, "-noout", "-text"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert "DNS:a.example.com" in result.stdout
        assert "DNS:b.example.com" in result.stdout
        assert "IP Address:192.168.1.1" in result.stdout
        assert "IP Address:192.168.1.2" in result.stdout
