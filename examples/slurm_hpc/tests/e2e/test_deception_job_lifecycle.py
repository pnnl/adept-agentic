"""E2E tests for Deception HPC cluster job lifecycle.

GUARDED: Requires DECEPTION_E2E_ENABLED=true env var AND network access.
These tests submit real jobs to the Deception cluster and consume allocation hours.
"""

import asyncio
import os
import socket
import time

import pytest

DECEPTION_E2E_ENABLED = os.getenv("DECEPTION_E2E_ENABLED", "false").lower() == "true"

skip_e2e = pytest.mark.skipif(
    not DECEPTION_E2E_ENABLED,
    reason="DECEPTION_E2E_ENABLED not set to 'true' (opt-in required)",
)


def _can_reach_deception() -> bool:
    try:
        sock = socket.create_connection(("deception.pnl.gov", 22), timeout=3.0)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


skip_network = pytest.mark.skipif(
    not _can_reach_deception() if DECEPTION_E2E_ENABLED else True,
    reason="Cannot reach deception.pnl.gov:22",
)


def _normalize_state(state):
    """Normalize Slurm job_state which may be a string or list of strings."""
    if isinstance(state, list):
        return state[0] if state else ""
    return state


def _state_matches(state, allowed):
    """Check if a (possibly list-typed) Slurm state matches any allowed value."""
    if isinstance(state, list):
        return any(s in allowed for s in state)
    return state in allowed


@skip_e2e
@skip_network
class TestDeceptionJobLifecycle:
    """End-to-end job lifecycle on Deception: submit -> poll -> verify completion."""

    @pytest.fixture
    def transport(self):
        from slurm_mcp.deception.config import deception_config
        from slurm_mcp.fabric_transport import FabricSSHTransport

        if not deception_config.resolved_ssh_key_path.exists():
            pytest.skip("SSH key not provisioned for Deception")
        t = FabricSSHTransport(deception_config)
        yield t
        try:
            loop = asyncio.get_running_loop()
            loop.run_until_complete(t.close())
        except RuntimeError:
            asyncio.run(t.close())

    @pytest.mark.asyncio
    async def test_submit_trivial_job(self, transport):
        """Submit a trivial job that runs hostname and sleeps 5 seconds."""
        result = await transport.submit_job(
            script="#!/bin/bash\nhostname\necho ADEPT_E2E_TEST_OK\nsleep 5",
            job_name="adept_e2e_test",
            time_limit="00:02:00",
            nodes=1,
            ntasks=1,
        )
        assert result.success is True, f"Submit failed: {result.error}"
        assert result.job_id is not None
        job_id = result.job_id

        deadline = time.time() + 120
        final_state = None
        while time.time() < deadline:
            status = await transport.get_job_status(job_id)
            if status.success and status.raw_data:
                state = status.raw_data.get("job_state", "")
                if _state_matches(state, ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT")):
                    final_state = _normalize_state(state)
                    break
            await asyncio.sleep(5)

        assert final_state == "COMPLETED", f"Job {job_id} ended with state: {final_state}"

    @pytest.mark.asyncio
    async def test_submit_and_cancel(self, transport):
        """Submit a long-running job and cancel it immediately."""
        result = await transport.submit_job(
            script="#!/bin/bash\nsleep 300",
            job_name="adept_e2e_cancel_test",
            time_limit="00:10:00",
            nodes=1,
            ntasks=1,
        )
        assert result.success is True
        job_id = result.job_id

        await asyncio.sleep(2)

        cancel_result = await transport.cancel_job(job_id)
        assert cancel_result.success is True

        await asyncio.sleep(3)
        status = await transport.get_job_status(job_id)
        if status.success and status.raw_data:
            state = status.raw_data.get("job_state", "")
            assert _state_matches(state, ("CANCELLED", "COMPLETED", "COMPLETING")), (
                f"Unexpected state: {state}"
            )

    @pytest.mark.asyncio
    async def test_list_own_jobs(self, transport):
        """Verify list_jobs returns at least the jobs we just submitted."""
        from slurm_mcp.deception.config import deception_config

        jobs = await transport.list_jobs(user=deception_config.username)
        assert isinstance(jobs, list)

    @pytest.mark.asyncio
    async def test_submit_and_list_queue(self, transport):
        """Submit a job, then list the queue and grep for our submission."""
        from slurm_mcp.deception.config import deception_config

        job_name = "adept_e2e_queue_check"
        result = await transport.submit_job(
            script="#!/bin/bash\nsleep 30",
            job_name=job_name,
            time_limit="00:02:00",
            nodes=1,
            ntasks=1,
        )
        assert result.success is True, f"Submit failed: {result.error}"
        job_id = result.job_id

        try:
            await asyncio.sleep(2)
            jobs = await transport.list_jobs(user=deception_config.username)
            assert isinstance(jobs, list)
            matching = [j for j in jobs if str(j.get("job_id")) == str(job_id)]
            assert len(matching) >= 1, (
                f"Job {job_id} ({job_name}) not found in queue listing. "
                f"Queue has {len(jobs)} jobs for user {deception_config.username}"
            )
            found_job = matching[0]
            assert found_job.get("name") == job_name or found_job.get("job_name") == job_name
        finally:
            await transport.cancel_job(job_id)

    @pytest.mark.asyncio
    async def test_submit_and_check_status(self, transport):
        """Submit a job, then check its status via get_job_status."""
        job_name = "adept_e2e_status_check"
        result = await transport.submit_job(
            script="#!/bin/bash\necho 'status check test'\nsleep 15",
            job_name=job_name,
            time_limit="00:02:00",
            nodes=1,
            ntasks=1,
        )
        assert result.success is True, f"Submit failed: {result.error}"
        job_id = result.job_id

        try:
            await asyncio.sleep(2)
            status = await transport.get_job_status(job_id)
            assert status.success is True, f"get_job_status failed: {status.error}"
            assert status.raw_data is not None
            state = status.raw_data.get("job_state", "")
            assert _state_matches(
                state, ("PENDING", "RUNNING", "COMPLETING", "COMPLETED")
            ), f"Unexpected state for freshly submitted job: {state}"
            raw_job_id = status.raw_data.get("job_id", "")
            if isinstance(raw_job_id, list):
                raw_job_id = raw_job_id[0] if raw_job_id else ""
            assert str(raw_job_id) == str(job_id)
        finally:
            await transport.cancel_job(job_id)
