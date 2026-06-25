"""Unit tests for SSH key lifecycle management (mocked filesystem/subprocess)."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slurm_mcp.ssh_keys import (
    ClusterKeyConfig,
    KeyStatus,
    check_key_status,
    generate_key_pair,
    get_cluster_key_configs,
    get_key_policy,
    load_clusters_config,
    test_connectivity as ssh_test_connectivity,
)

SAMPLE_CLUSTERS_YAML = {
    "clusters": {
        "deception": {
            "display_name": "Deception",
            "host": "deception.pnl.gov",
            "ssh_port": 22,
            "username": "rigo160",
            "transport_modes": ["ssh"],
            "working_directory": "/scratch/rigo160",
            "ssh_key": {
                "private_key_path": "~/.ssh/adept_deception_ed25519",
                "public_key_path": "~/.ssh/adept_deception_ed25519.pub",
                "algorithm": "ed25519",
                "comment": "adept-deception",
                "provisioning": "manual_authorized_keys",
            },
        },
        "tahoma": {
            "display_name": "Tahoma",
            "host": "tahoma.pnl.gov",
            "ssh_port": 22,
            "username": "rigo160",
            "transport_modes": ["ssh", "rest"],
            "working_directory": "/scratch/rigo160",
            "ssh_key": {
                "private_key_path": "~/.ssh/adept_tahoma_ed25519",
                "public_key_path": "~/.ssh/adept_tahoma_ed25519.pub",
                "algorithm": "ed25519",
                "comment": "adept-tahoma",
                "provisioning": "manual_authorized_keys",
            },
        },
    },
    "key_policy": {
        "preferred_algorithm": "ed25519",
        "rotation_reminder_days": 365,
        "strict_host_key_checking": True,
        "known_hosts_path": "~/.ssh/known_hosts",
        "min_rsa_bits": 4096,
    },
}


@pytest.fixture
def mock_yaml_config(tmp_path):
    """Write a clusters.yaml to a temp dir and return the path."""
    import yaml

    config_path = tmp_path / "clusters.yaml"
    config_path.write_text(yaml.dump(SAMPLE_CLUSTERS_YAML))
    return config_path


class TestLoadClustersConfig:
    """Tests for load_clusters_config()."""

    def test_loads_valid_yaml(self, mock_yaml_config):
        data = load_clusters_config(mock_yaml_config)
        assert "clusters" in data
        assert "deception" in data["clusters"]
        assert "tahoma" in data["clusters"]

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_clusters_config(tmp_path / "nonexistent.yaml")


class TestGetClusterKeyConfigs:
    """Tests for get_cluster_key_configs()."""

    def test_parses_both_clusters(self, mock_yaml_config):
        configs = get_cluster_key_configs(mock_yaml_config)
        assert "deception" in configs
        assert "tahoma" in configs

    def test_deception_config_fields(self, mock_yaml_config):
        configs = get_cluster_key_configs(mock_yaml_config)
        d = configs["deception"]
        assert isinstance(d, ClusterKeyConfig)
        assert d.cluster_name == "deception"
        assert d.display_name == "Deception"
        assert d.host == "deception.pnl.gov"
        assert d.ssh_port == 22
        assert d.username == "rigo160"
        assert d.algorithm == "ed25519"
        assert d.provisioning == "manual_authorized_keys"
        assert d.transport_modes == ["ssh"]

    def test_tahoma_has_rest_transport(self, mock_yaml_config):
        configs = get_cluster_key_configs(mock_yaml_config)
        t = configs["tahoma"]
        assert "rest" in t.transport_modes

    def test_paths_are_expanded(self, mock_yaml_config):
        configs = get_cluster_key_configs(mock_yaml_config)
        d = configs["deception"]
        assert "~" not in str(d.private_key_path)


class TestGetKeyPolicy:
    """Tests for get_key_policy()."""

    def test_returns_policy(self, mock_yaml_config):
        policy = get_key_policy(mock_yaml_config)
        assert policy["preferred_algorithm"] == "ed25519"
        assert policy["rotation_reminder_days"] == 365
        assert policy["strict_host_key_checking"] is True
        assert policy["min_rsa_bits"] == 4096


class TestCheckKeyStatus:
    """Tests for check_key_status()."""

    def test_unknown_cluster(self, mock_yaml_config):
        status = check_key_status("nonexistent", mock_yaml_config)
        assert status.private_key_exists is False
        assert "Unknown cluster" in status.errors[0]

    def test_key_not_generated_yet(self, mock_yaml_config):
        status = check_key_status("deception", mock_yaml_config)
        assert status.private_key_exists is False
        assert "does not exist" in status.errors[0]

    def test_key_exists_with_correct_permissions(self, mock_yaml_config, tmp_path):
        """Create a fake key file and check status reports correctly."""
        import os
        import stat
        import time

        import yaml

        # Override key path to tmp_path
        config_data = SAMPLE_CLUSTERS_YAML.copy()
        key_path = tmp_path / "test_key"
        pub_path = tmp_path / "test_key.pub"
        config_data["clusters"]["deception"]["ssh_key"]["private_key_path"] = str(key_path)
        config_data["clusters"]["deception"]["ssh_key"]["public_key_path"] = str(pub_path)

        yaml_path = tmp_path / "clusters.yaml"
        yaml_path.write_text(yaml.dump(config_data))

        # Create fake key files
        key_path.write_text("FAKE PRIVATE KEY")
        pub_path.write_text("ssh-ed25519 AAAAC3Nz... adept-deception")
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600

        with patch("slurm_mcp.ssh_keys.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(
                returncode=0,
                stdout="256 SHA256:ABC123DEF456GHI789JKL comment (ED25519)\n",
            )
            status = check_key_status("deception", yaml_path)

        assert status.private_key_exists is True
        assert status.public_key_exists is True
        assert status.permissions_ok is True
        assert status.age_days is not None
        assert status.fingerprint_prefix.startswith("SHA256:")
        assert status.errors == []

    def test_bad_permissions_reported(self, mock_yaml_config, tmp_path):
        """Key with 0644 should report permissions_ok = False."""
        import os
        import yaml

        config_data = SAMPLE_CLUSTERS_YAML.copy()
        key_path = tmp_path / "test_key"
        pub_path = tmp_path / "test_key.pub"
        config_data["clusters"]["deception"]["ssh_key"]["private_key_path"] = str(key_path)
        config_data["clusters"]["deception"]["ssh_key"]["public_key_path"] = str(pub_path)

        yaml_path = tmp_path / "clusters.yaml"
        yaml_path.write_text(yaml.dump(config_data))

        key_path.write_text("FAKE PRIVATE KEY")
        pub_path.write_text("ssh-ed25519 AAAAC3Nz...")
        os.chmod(key_path, 0o644)  # Intentionally wrong

        status = check_key_status("deception", yaml_path)
        assert status.permissions_ok is False
        assert any("0644" in e or "0o644" in e for e in status.errors)


class TestGenerateKeyPair:
    """Tests for generate_key_pair()."""

    def test_unknown_cluster(self, mock_yaml_config):
        result = generate_key_pair("nonexistent", mock_yaml_config)
        assert result["success"] is False
        assert "Unknown cluster" in result["error"]

    def test_refuses_overwrite_without_flag(self, mock_yaml_config, tmp_path):
        import yaml

        config_data = SAMPLE_CLUSTERS_YAML.copy()
        key_path = tmp_path / "existing_key"
        config_data["clusters"]["deception"]["ssh_key"]["private_key_path"] = str(key_path)
        config_data["clusters"]["deception"]["ssh_key"]["public_key_path"] = str(key_path) + ".pub"
        yaml_path = tmp_path / "clusters.yaml"
        yaml_path.write_text(yaml.dump(config_data))
        key_path.write_text("EXISTING KEY")

        result = generate_key_pair("deception", yaml_path, overwrite=False)
        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_successful_generation(self, mock_yaml_config, tmp_path):
        import yaml

        config_data = SAMPLE_CLUSTERS_YAML.copy()
        key_path = tmp_path / "new_key"
        pub_path = tmp_path / "new_key.pub"
        config_data["clusters"]["deception"]["ssh_key"]["private_key_path"] = str(key_path)
        config_data["clusters"]["deception"]["ssh_key"]["public_key_path"] = str(pub_path)
        yaml_path = tmp_path / "clusters.yaml"
        yaml_path.write_text(yaml.dump(config_data))

        with patch("slurm_mcp.ssh_keys.subprocess.run") as mock_sp:
            call_count = {"n": 0}

            def subprocess_side_effect(*args, **kwargs):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    # ssh-keygen: simulate creating key files
                    key_path.write_text("GENERATED KEY")
                    pub_path.write_text("ssh-ed25519 AAAAC3Nz... adept-deception")
                    return MagicMock(returncode=0, stdout="", stderr="")
                else:
                    # ssh-keygen -l: fingerprint check
                    return MagicMock(returncode=0, stdout="256 SHA256:ABC... (ED25519)\n")

            mock_sp.side_effect = subprocess_side_effect

            result = generate_key_pair("deception", yaml_path)

        assert result["success"] is True
        assert result["cluster"] == "deception"
        assert result["algorithm"] == "ed25519"
        assert "public_key" in result
        assert "instructions" in result
        assert "authorized_keys" in result["instructions"]

    def test_keygen_failure(self, mock_yaml_config, tmp_path):
        import yaml

        config_data = SAMPLE_CLUSTERS_YAML.copy()
        key_path = tmp_path / "fail_key"
        config_data["clusters"]["deception"]["ssh_key"]["private_key_path"] = str(key_path)
        config_data["clusters"]["deception"]["ssh_key"]["public_key_path"] = str(key_path) + ".pub"
        yaml_path = tmp_path / "clusters.yaml"
        yaml_path.write_text(yaml.dump(config_data))

        with patch("slurm_mcp.ssh_keys.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(
                returncode=1, stdout="", stderr="Permission denied"
            )
            result = generate_key_pair("deception", yaml_path)

        assert result["success"] is False
        assert "Permission denied" in result["error"]


class TestTestConnectivity:
    """Tests for test_connectivity()."""

    def test_unknown_cluster(self, mock_yaml_config):
        result = ssh_test_connectivity("nonexistent", mock_yaml_config)
        assert result["success"] is False
        assert "Unknown cluster" in result["error"]

    def test_no_key_file(self, mock_yaml_config):
        result = ssh_test_connectivity("deception", mock_yaml_config)
        assert result["success"] is False
        assert "No private key" in result["error"]

    def test_successful_connectivity(self, mock_yaml_config, tmp_path):
        import yaml

        config_data = SAMPLE_CLUSTERS_YAML.copy()
        key_path = tmp_path / "conn_key"
        config_data["clusters"]["deception"]["ssh_key"]["private_key_path"] = str(key_path)
        config_data["clusters"]["deception"]["ssh_key"]["public_key_path"] = str(key_path) + ".pub"
        yaml_path = tmp_path / "clusters.yaml"
        yaml_path.write_text(yaml.dump(config_data))
        key_path.write_text("FAKE KEY")

        with patch("slurm_mcp.ssh_keys.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(
                returncode=0,
                stdout="ADEPT_CONNECTIVITY_OK\n",
                stderr="",
            )
            result = ssh_test_connectivity("deception", yaml_path)

        assert result["success"] is True
        assert result["cluster"] == "deception"
        assert result["host"] == "deception.pnl.gov"
        assert "Connected" in result["message"]

    def test_connection_refused(self, mock_yaml_config, tmp_path):
        import yaml

        config_data = SAMPLE_CLUSTERS_YAML.copy()
        key_path = tmp_path / "conn_key"
        config_data["clusters"]["deception"]["ssh_key"]["private_key_path"] = str(key_path)
        config_data["clusters"]["deception"]["ssh_key"]["public_key_path"] = str(key_path) + ".pub"
        yaml_path = tmp_path / "clusters.yaml"
        yaml_path.write_text(yaml.dump(config_data))
        key_path.write_text("FAKE KEY")

        with patch("slurm_mcp.ssh_keys.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(
                returncode=255,
                stdout="",
                stderr="ssh: connect to host deception.pnl.gov port 22: Connection refused",
            )
            result = ssh_test_connectivity("deception", yaml_path)

        assert result["success"] is False
        assert "Connection refused" in result["message"]

    def test_connection_timeout(self, mock_yaml_config, tmp_path):
        import yaml

        config_data = SAMPLE_CLUSTERS_YAML.copy()
        key_path = tmp_path / "conn_key"
        config_data["clusters"]["deception"]["ssh_key"]["private_key_path"] = str(key_path)
        config_data["clusters"]["deception"]["ssh_key"]["public_key_path"] = str(key_path) + ".pub"
        yaml_path = tmp_path / "clusters.yaml"
        yaml_path.write_text(yaml.dump(config_data))
        key_path.write_text("FAKE KEY")

        with patch("slurm_mcp.ssh_keys.subprocess.run") as mock_sp:
            mock_sp.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=15)
            result = ssh_test_connectivity("deception", yaml_path)

        assert result["success"] is False
        assert "timed out" in result["error"]
