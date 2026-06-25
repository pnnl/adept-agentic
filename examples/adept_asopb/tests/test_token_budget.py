"""
Token Budget Gate Tests

Validates the T2 LLM token budget ceiling implementation:
- EvalConfig token_budget and token_budget_auto_confirm fields
- Evaluator.estimate_t2_token_budget() method structure and correctness
- CLI --token-budget and --token-budget-confirm flag parsing
- Budget exceeded detection logic
"""

import os
import tempfile

import pytest
from click.testing import CliRunner

from asopb.cli import cli
from asopb.config import EvalConfig
from asopb.evaluator import Evaluator


# ─── Config Tests ────────────────────────────────────────────────────────────


class TestTokenBudgetConfig:
    """Validate EvalConfig token budget fields."""

    def test_default_token_budget_is_zero(self):
        config = EvalConfig()
        assert config.token_budget == 0

    def test_default_auto_confirm_is_false(self):
        config = EvalConfig()
        assert config.token_budget_auto_confirm is False

    def test_custom_token_budget(self):
        config = EvalConfig(token_budget=200000)
        assert config.token_budget == 200000

    def test_custom_auto_confirm(self):
        config = EvalConfig(token_budget_auto_confirm=True)
        assert config.token_budget_auto_confirm is True

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("ASOPB_TOKEN_BUDGET", "150000")
        config = EvalConfig(token_budget=int(os.getenv("ASOPB_TOKEN_BUDGET", "0")))
        assert config.token_budget == 150000


# ─── Estimator Tests ─────────────────────────────────────────────────────────


class TestEstimateT2TokenBudget:
    """Validate Evaluator.estimate_t2_token_budget() method."""

    @pytest.fixture
    def evaluator_unlimited(self):
        config = EvalConfig(skip_llm=False, token_budget=0)
        return Evaluator(config=config)

    @pytest.fixture
    def evaluator_capped(self):
        config = EvalConfig(skip_llm=False, token_budget=1000)
        return Evaluator(config=config)

    def test_method_exists(self, evaluator_unlimited):
        assert hasattr(evaluator_unlimited, "estimate_t2_token_budget")
        assert callable(evaluator_unlimited.estimate_t2_token_budget)

    def test_returns_dict(self, evaluator_unlimited):
        result = evaluator_unlimited.estimate_t2_token_budget()
        assert isinstance(result, dict)

    def test_required_keys_present(self, evaluator_unlimited):
        result = evaluator_unlimited.estimate_t2_token_budget()
        required_keys = [
            "estimated_calls",
            "estimated_input_tokens",
            "estimated_output_tokens",
            "estimated_total_tokens",
            "per_domain",
            "budget_limit",
            "exceeds_budget",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_total_equals_input_plus_output(self, evaluator_unlimited):
        result = evaluator_unlimited.estimate_t2_token_budget()
        expected = result["estimated_input_tokens"] + result["estimated_output_tokens"]
        assert result["estimated_total_tokens"] == expected

    def test_calls_positive(self, evaluator_unlimited):
        result = evaluator_unlimited.estimate_t2_token_budget()
        assert result["estimated_calls"] > 0

    def test_tokens_positive(self, evaluator_unlimited):
        result = evaluator_unlimited.estimate_t2_token_budget()
        assert result["estimated_input_tokens"] > 0
        assert result["estimated_output_tokens"] > 0
        assert result["estimated_total_tokens"] > 0

    def test_budget_limit_zero_never_exceeds(self, evaluator_unlimited):
        result = evaluator_unlimited.estimate_t2_token_budget()
        assert result["budget_limit"] == 0
        assert result["exceeds_budget"] is False

    def test_budget_limit_low_triggers_exceeds(self, evaluator_capped):
        result = evaluator_capped.estimate_t2_token_budget()
        assert result["budget_limit"] == 1000
        assert result["exceeds_budget"] is True

    def test_budget_limit_high_does_not_exceed(self):
        config = EvalConfig(skip_llm=False, token_budget=10_000_000)
        evaluator = Evaluator(config=config)
        result = evaluator.estimate_t2_token_budget()
        assert result["exceeds_budget"] is False

    def test_per_domain_structure(self, evaluator_unlimited):
        result = evaluator_unlimited.estimate_t2_token_budget()
        per_domain = result["per_domain"]
        assert isinstance(per_domain, dict)
        assert len(per_domain) > 0

        for domain_id, info in per_domain.items():
            assert domain_id.startswith("D"), f"Domain ID should start with D: {domain_id}"
            assert "controls_total" in info
            assert "controls_t2_eligible" in info
            assert "input_tokens" in info
            assert "output_tokens" in info
            assert "calls" in info
            assert "skill_tokens" in info
            assert "input_per_call" in info

    def test_per_domain_calls_sum_to_total(self, evaluator_unlimited):
        result = evaluator_unlimited.estimate_t2_token_budget()
        domain_calls_sum = sum(info["calls"] for info in result["per_domain"].values())
        assert domain_calls_sum == result["estimated_calls"]

    def test_per_domain_tokens_sum_to_totals(self, evaluator_unlimited):
        result = evaluator_unlimited.estimate_t2_token_budget()
        input_sum = sum(info["input_tokens"] for info in result["per_domain"].values())
        output_sum = sum(info["output_tokens"] for info in result["per_domain"].values())
        assert input_sum == result["estimated_input_tokens"]
        assert output_sum == result["estimated_output_tokens"]

    def test_eligible_controls_less_than_or_equal_total(self, evaluator_unlimited):
        result = evaluator_unlimited.estimate_t2_token_budget()
        for domain_id, info in result["per_domain"].items():
            assert info["controls_t2_eligible"] <= info["controls_total"], (
                f"{domain_id}: eligible ({info['controls_t2_eligible']}) > "
                f"total ({info['controls_total']})"
            )

    def test_expected_domain_count(self, evaluator_unlimited):
        result = evaluator_unlimited.estimate_t2_token_budget()
        assert len(result["per_domain"]) == 8


# ─── CLI Flag Tests ──────────────────────────────────────────────────────────


class TestTokenBudgetCLI:
    """Validate --token-budget and --token-budget-confirm CLI flags."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_help_shows_token_budget_flag(self, runner):
        result = runner.invoke(cli, ["evaluate", "--help"])
        assert "--token-budget" in result.output

    def test_help_shows_token_budget_confirm_flag(self, runner):
        result = runner.invoke(cli, ["evaluate", "--help"])
        assert "--token-budget-confirm" in result.output

    def test_token_budget_accepts_integer(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                cli, ["evaluate", tmpdir, "--token-budget", "200000", "--skip-llm"]
            )
            assert result.exit_code == 0, f"Unexpected exit: {result.output[:300]}"

    def test_token_budget_zero_is_unlimited(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                cli, ["evaluate", tmpdir, "--token-budget", "0", "--skip-llm"]
            )
            assert result.exit_code == 0

    def test_token_budget_confirm_flag_accepted(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                cli,
                ["evaluate", tmpdir, "--token-budget", "200000", "--token-budget-confirm", "--skip-llm"],
            )
            assert result.exit_code == 0

    def test_skip_llm_bypasses_budget_display(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                cli, ["evaluate", tmpdir, "--skip-llm", "--token-budget", "100"]
            )
            assert "Token Budget" not in result.output
