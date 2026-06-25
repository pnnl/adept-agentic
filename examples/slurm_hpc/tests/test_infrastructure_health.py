"""
Infrastructure health tests for Slurm HPC MCP Server.

Validates tool visibility in ADEPT core Redis. Slurm HPC does not run
its own Redis instance, so Redis isolation tests are not applicable.

Requirements:
    - ADEPT core stack running (redis, orchestration_service)
    - Slurm HPC tools registered (make register-tools)

Run:
    make test-infrastructure-health
    pytest tests/test_infrastructure_health.py -v
"""

import json
import os

import pytest

STACK_NAME = "slurm_hpc"

EXPECTED_TOOLS = [
    # Local Docker Slurm tools (6)
    "slurm_hpc_submit_job",
    "slurm_hpc_get_job_details",
    "slurm_hpc_cancel_job",
    "slurm_hpc_ping",
    "slurm_hpc_list_jobs",
    "slurm_hpc_cluster_summary",
    # Deception cluster tools (6)
    "slurm_hpc_deception_ping",
    "slurm_hpc_deception_submit_job",
    "slurm_hpc_deception_get_job_details",
    "slurm_hpc_deception_cancel_job",
    "slurm_hpc_deception_list_jobs",
    "slurm_hpc_deception_get_cluster_summary",
    # Tahoma cluster tools (6)
    "slurm_hpc_tahoma_ping",
    "slurm_hpc_tahoma_submit_job",
    "slurm_hpc_tahoma_get_job_details",
    "slurm_hpc_tahoma_cancel_job",
    "slurm_hpc_tahoma_list_jobs",
    "slurm_hpc_tahoma_get_cluster_summary",
    # SSH key management tools (5)
    "slurm_hpc_hpc_list_clusters",
    "slurm_hpc_hpc_check_ssh_key",
    "slurm_hpc_hpc_generate_ssh_key",
    "slurm_hpc_hpc_test_ssh_connectivity",
    "slurm_hpc_hpc_get_provisioning_instructions",
]

ADEPT_REDIS_HOST = os.getenv("ADEPT_REDIS_HOST", "redis")
ADEPT_REDIS_PORT = int(os.getenv("ADEPT_REDIS_PORT", "6379"))


@pytest.fixture(scope="module")
def adept_redis():
    try:
        import redis
        client = redis.Redis(host=ADEPT_REDIS_HOST, port=ADEPT_REDIS_PORT, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception as e:
        pytest.skip(f"ADEPT core Redis not reachable: {e}")


class TestToolVisibility:

    def test_all_expected_tools_in_adept_redis(self, adept_redis):
        missing = [t for t in EXPECTED_TOOLS if not adept_redis.get(f"external_tool:{t}")]
        assert not missing, f"Tools not in ADEPT Redis: {missing}. Run 'make register-tools'"

    def test_tools_use_mcp_protocol(self, adept_redis):
        wrong = []
        for t in EXPECTED_TOOLS:
            val = adept_redis.get(f"external_tool:{t}")
            if val and json.loads(val).get("invocation", {}).get("protocol") != "mcp":
                wrong.append(t)
        assert not wrong, f"Tools with wrong protocol: {wrong}"

    def test_tools_point_to_slurm_mcp_url(self, adept_redis):
        wrong = []
        for t in EXPECTED_TOOLS:
            val = adept_redis.get(f"external_tool:{t}")
            if val:
                url = json.loads(val).get("invocation", {}).get("connection", {}).get("url", "")
                if "slurm" not in url and "hpc" not in url:
                    wrong.append(f"{t}: {url}")
        assert not wrong, f"Tools with wrong URL: {wrong}"

    def test_tools_have_global_acl(self, adept_redis):
        restricted = [t for t in EXPECTED_TOOLS
                      if adept_redis.get(f"external_tool:{t}")
                      and not json.loads(adept_redis.get(f"external_tool:{t}")).get("acl", {}).get("global")]
        assert not restricted, f"Tools without global ACL: {restricted}"
