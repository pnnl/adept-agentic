"""Unit tests for perform_demo_v2.py — verdict extraction, mode selection, prompt building."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "demos"))

from perform_demo_v2 import _build_multi_agent_prompt, _extract_verdict


class TestExtractVerdict:
    """Validate FinalVerdict JSON extraction from agent output."""

    def test_extract_pass_verdict(self):
        output = (
            'Based on the analysis, the workflow completed.\n'
            '{"final_verdict": "PASS", "confidence": 0.95, "summary": "All steps completed", '
            '"job_ids": ["869838", "869839"], "optimal_value": 10.0}\n'
            'End of evaluation.'
        )
        verdict = _extract_verdict(output)
        assert verdict is not None
        assert verdict["final_verdict"] == "PASS"
        assert verdict["confidence"] == 0.95
        assert verdict["optimal_value"] == 10.0
        assert "869838" in verdict["job_ids"]

    def test_extract_fail_verdict(self):
        output = '{"final_verdict": "FAIL", "confidence": 0.8, "summary": "SIF not found", "job_ids": [], "optimal_value": null}'
        verdict = _extract_verdict(output)
        assert verdict is not None
        assert verdict["final_verdict"] == "FAIL"
        assert verdict["optimal_value"] is None

    def test_extract_partial_verdict(self):
        output = 'Step 1 passed.\n{"final_verdict": "PARTIAL", "confidence": 0.5, "summary": "FBA job still running", "job_ids": ["870001"]}'
        verdict = _extract_verdict(output)
        assert verdict is not None
        assert verdict["final_verdict"] == "PARTIAL"

    def test_no_verdict_returns_none(self):
        output = "The agent is working on step 2. Waiting for results."
        verdict = _extract_verdict(output)
        assert verdict is None

    def test_malformed_json_returns_none(self):
        output = '{"final_verdict": "PASS", confidence: broken}'
        verdict = _extract_verdict(output)
        assert verdict is None

    def test_verdict_embedded_in_markdown(self):
        output = (
            '```json\n'
            '{"final_verdict": "PASS", "confidence": 0.9, "summary": "OK", "job_ids": ["123456"], "optimal_value": 10.0}\n'
            '```\n'
        )
        verdict = _extract_verdict(output)
        assert verdict is not None
        assert verdict["final_verdict"] == "PASS"

    def test_verdict_with_step_verdicts_nearby(self):
        output = (
            '{"step": "file_staging", "passed": true, "evidence": "ok", "reasoning": "ok"}\n'
            '{"step": "sif_provisioning", "passed": true, "evidence": "ok", "reasoning": "ok"}\n'
            '{"final_verdict": "PASS", "confidence": 0.92, "summary": "All good", "job_ids": ["111111"]}\n'
        )
        verdict = _extract_verdict(output)
        assert verdict is not None
        assert verdict["final_verdict"] == "PASS"
        assert verdict["confidence"] == 0.92

    def test_verdict_synonym_success_normalized_to_pass(self):
        output = '{"final_verdict": "success", "steps": [{"step": "FBA", "verdict": "success"}]}'
        verdict = _extract_verdict(output)
        assert verdict is not None
        assert verdict["final_verdict"] == "PASS"

    def test_verdict_synonym_failure_normalized_to_fail(self):
        output = '{"final_verdict": "failure", "confidence": 0.8, "summary": "SIF missing"}'
        verdict = _extract_verdict(output)
        assert verdict is not None
        assert verdict["final_verdict"] == "FAIL"

    def test_verdict_synonym_incomplete_normalized_to_partial(self):
        output = '{"final_verdict": "incomplete", "summary": "Job still running"}'
        verdict = _extract_verdict(output)
        assert verdict is not None
        assert verdict["final_verdict"] == "PARTIAL"

    def test_verdict_nested_format_success(self):
        output = '{"step_verdicts": {"1": "success"}, "final_verdict": {"status": "success", "message": "All steps OK", "data": {"optimal_value": 10.0}}}'
        verdict = _extract_verdict(output)
        assert verdict is not None
        assert verdict["final_verdict"] == "PASS"
        assert verdict["optimal_value"] == 10.0
        assert "All steps OK" in verdict["summary"]

    def test_verdict_nested_format_failure(self):
        output = '{"final_verdict": {"status": "failure", "message": "SIF not found"}}'
        verdict = _extract_verdict(output)
        assert verdict is not None
        assert verdict["final_verdict"] == "FAIL"


class TestBuildMultiAgentPrompt:
    """Validate prompt construction for multi-agent sessions."""

    def test_contains_all_roles(self):
        prompt = _build_multi_agent_prompt("rigo160", "file-abc123", "simple_pathway.xml")
        assert "EXECUTOR:" in prompt
        assert "JUDGE:" in prompt
        assert "OBSERVER:" in prompt

    def test_contains_user(self):
        prompt = _build_multi_agent_prompt("testuser", "f-123", "model.xml")
        assert "testuser" in prompt

    def test_contains_model_name(self):
        prompt = _build_multi_agent_prompt("rigo160", "f-abc", "ecoli_core.xml")
        assert "ecoli_core.xml" in prompt

    def test_contains_file_id(self):
        prompt = _build_multi_agent_prompt("rigo160", "file-550e8400", "model.xml")
        assert "file-550e8400" in prompt

    def test_contains_unsquash(self):
        prompt = _build_multi_agent_prompt("rigo160", "f-1", "m.xml")
        assert "--unsquash" in prompt

    def test_contains_gurobi_license(self):
        prompt = _build_multi_agent_prompt("rigo160", "f-1", "m.xml")
        assert "gurobi.lic" in prompt

    def test_no_tilde_in_prompt(self):
        prompt = _build_multi_agent_prompt("rigo160", "f-1", "m.xml")
        assert "~/" not in prompt
        assert "~" not in prompt or prompt.count("~") == 0

    def test_no_scratch_in_prompt(self):
        prompt = _build_multi_agent_prompt("rigo160", "f-1", "m.xml")
        assert "/scratch/" not in prompt


class TestSchemaImports:
    """Validate Pydantic schema modules import and parse correctly."""

    def test_import_verdict_schemas(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "demos"))
        from schemas import FinalVerdict, StepVerdict

        assert FinalVerdict is not None
        assert StepVerdict is not None

    def test_final_verdict_validates(self):
        from schemas.verdict import FinalVerdict

        v = FinalVerdict(
            final_verdict="PASS",
            confidence=0.95,
            summary="All steps completed successfully",
            job_ids=["869838"],
            optimal_value=10.0,
        )
        assert v.final_verdict == "PASS"
        assert v.confidence == 0.95

    def test_final_verdict_rejects_invalid_confidence(self):
        from schemas.verdict import FinalVerdict

        with pytest.raises(Exception):
            FinalVerdict(
                final_verdict="PASS",
                confidence=1.5,
                summary="Invalid",
            )

    def test_step_verdict_validates(self):
        from schemas.verdict import StepVerdict

        sv = StepVerdict(
            step="file_staging",
            passed=True,
            evidence="workspace_upload_file returned success",
            reasoning="All 3 files uploaded",
        )
        assert sv.passed is True

    def test_observer_anomaly_validates(self):
        from schemas.verdict import ObserverAnomaly

        a = ObserverAnomaly(
            anomaly="retry_loop",
            detail="deception_submit_job called 4 times with same params",
            severity="warning",
        )
        assert a.severity == "warning"


class TestPersonaImports:
    """Validate persona modules import correctly."""

    def test_import_all_personas(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "demos"))
        from personas import EXECUTOR_PERSONA, JUDGE_PERSONA, OBSERVER_PERSONA

        assert EXECUTOR_PERSONA["name"] == "hpc_executor"
        assert JUDGE_PERSONA["name"] == "workflow_judge"
        assert OBSERVER_PERSONA["name"] == "execution_observer"

    def test_executor_has_coding_agent_purpose(self):
        from personas import EXECUTOR_PERSONA

        assert EXECUTOR_PERSONA["llm_purpose"] == "coding_agent"

    def test_judge_has_agent_main_purpose(self):
        from personas import JUDGE_PERSONA

        assert JUDGE_PERSONA["llm_purpose"] == "agent_main"

    def test_all_personas_have_system_prompt(self):
        from personas import EXECUTOR_PERSONA, JUDGE_PERSONA, OBSERVER_PERSONA

        for persona in [EXECUTOR_PERSONA, JUDGE_PERSONA, OBSERVER_PERSONA]:
            assert "system_prompt_template" in persona
            assert len(persona["system_prompt_template"]) > 100
            assert "{base_instruction}" in persona["system_prompt_template"]
