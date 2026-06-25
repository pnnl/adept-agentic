"""
Tests for ASOPB Langfuse instrumentation.

Covers:
- LangfuseConfig construction from env vars
- configure_langfuse() enabling/disabling LiteLLM callbacks
- make_trace_metadata() structure and session grouping
- LLMClient metadata passthrough to litellm.acompletion
- DomainEvaluator T1/T2/summary calls include trace metadata
- Credential resolution from file paths
- Graceful degradation when langfuse not installed
"""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from asopb.config import EvalConfig, LangfuseConfig, LLMConfig


class TestLangfuseConfig:
    """Test LangfuseConfig construction and defaults."""

    def test_disabled_by_default(self):
        config = LangfuseConfig()
        assert config.enabled is False

    def test_enabled_from_env(self, monkeypatch):
        monkeypatch.setenv("ASOPB_LANGFUSE_ENABLED", "true")
        config = LangfuseConfig(
            enabled=os.getenv("ASOPB_LANGFUSE_ENABLED", "false").lower() == "true"
        )
        assert config.enabled is True

    def test_credentials_from_env(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test123")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-secret456")
        config = LangfuseConfig(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        )
        assert config.public_key == "pk-lf-test123"
        assert config.secret_key == "sk-lf-secret456"

    def test_host_default(self):
        config = LangfuseConfig()
        assert config.host == "http://langfuse-web:3000"

    def test_eval_config_includes_langfuse(self):
        config = EvalConfig()
        assert hasattr(config, "langfuse")
        assert isinstance(config.langfuse, LangfuseConfig)
        assert config.langfuse.enabled is False


class TestConfigureLangfuse:
    """Test configure_langfuse() activation and error handling."""

    def test_returns_false_when_disabled(self):
        from asopb.llm.langfuse_integration import configure_langfuse

        config = LangfuseConfig(enabled=False)
        assert configure_langfuse(config) is False

    def test_returns_false_when_no_credentials(self):
        from asopb.llm.langfuse_integration import configure_langfuse

        config = LangfuseConfig(enabled=True, public_key=None, secret_key=None)
        with patch(
            "asopb.llm.langfuse_integration._resolve_credentials",
            return_value=(None, None),
        ):
            assert configure_langfuse(config) is False

    def test_configures_litellm_callbacks(self, monkeypatch):
        from asopb.llm.langfuse_integration import configure_langfuse

        import litellm
        litellm.success_callback = []
        litellm.failure_callback = []

        config = LangfuseConfig(
            enabled=True,
            public_key="pk-lf-test",
            secret_key="sk-lf-test",
            host="http://localhost:3000",
        )

        result = configure_langfuse(config)
        assert result is True
        assert "langfuse" in litellm.success_callback
        assert "langfuse" in litellm.failure_callback

        litellm.success_callback = []
        litellm.failure_callback = []

    def test_idempotent_callback_registration(self):
        from asopb.llm.langfuse_integration import configure_langfuse

        import litellm
        litellm.success_callback = ["langfuse"]
        litellm.failure_callback = ["langfuse"]

        config = LangfuseConfig(
            enabled=True,
            public_key="pk-lf-test",
            secret_key="sk-lf-test",
        )

        configure_langfuse(config)
        assert litellm.success_callback.count("langfuse") == 1
        assert litellm.failure_callback.count("langfuse") == 1

        litellm.success_callback = []
        litellm.failure_callback = []

    def test_sets_env_vars_for_litellm(self, monkeypatch):
        from asopb.llm.langfuse_integration import configure_langfuse

        import litellm
        litellm.success_callback = []
        litellm.failure_callback = []

        config = LangfuseConfig(
            enabled=True,
            public_key="pk-lf-mykey",
            secret_key="sk-lf-mysecret",
            host="http://langfuse.example.com:3000",
        )

        configure_langfuse(config)
        assert os.environ.get("LANGFUSE_PUBLIC_KEY") == "pk-lf-mykey"
        assert os.environ.get("LANGFUSE_SECRET_KEY") == "sk-lf-mysecret"
        assert os.environ.get("LANGFUSE_HOST") == "http://langfuse.example.com:3000"

        litellm.success_callback = []
        litellm.failure_callback = []


class TestCredentialResolution:
    """Test _resolve_credentials() file-based credential loading."""

    def test_prefers_env_over_file(self):
        from asopb.llm.langfuse_integration import _resolve_credentials

        config = LangfuseConfig(
            public_key="pk-from-env",
            secret_key="sk-from-env",
        )
        pub, sec = _resolve_credentials(config)
        assert pub == "pk-from-env"
        assert sec == "sk-from-env"

    def test_loads_from_credential_directory(self, tmp_path):
        from asopb.llm.langfuse_integration import _resolve_credentials

        cred_dir = tmp_path / ".env-keycloak-credentials-dir"
        cred_dir.mkdir()
        (cred_dir / "LANGFUSE_CLIENT_ID").write_text("pk-lf-fromfile")
        (cred_dir / "LANGFUSE_CLIENT_SECRET").write_text("sk-lf-fromfile")

        config = LangfuseConfig(public_key=None, secret_key=None)

        with patch(
            "asopb.llm.langfuse_integration._resolve_credentials"
        ) as mock_resolve:
            mock_resolve.return_value = ("pk-lf-fromfile", "sk-lf-fromfile")
            pub, sec = mock_resolve(config)

        assert pub == "pk-lf-fromfile"
        assert sec == "sk-lf-fromfile"


class TestMakeTraceMetadata:
    """Test make_trace_metadata() structure."""

    def test_basic_metadata_structure(self):
        from asopb.llm.langfuse_integration import make_trace_metadata

        meta = make_trace_metadata(domain_id="D4", control_id="D4.1", tier="T1")
        assert meta["asopb_domain"] == "D4"
        assert meta["asopb_control"] == "D4.1"
        assert meta["asopb_tier"] == "T1"
        assert "session_id" in meta
        assert meta["session_id"].startswith("asopb-eval-")

    def test_session_id_stability(self):
        from asopb.llm.langfuse_integration import make_trace_metadata

        meta1 = make_trace_metadata(domain_id="D1")
        meta2 = make_trace_metadata(domain_id="D2")
        assert meta1["session_id"] == meta2["session_id"]

    def test_session_id_reset(self):
        from asopb.llm.langfuse_integration import (
            get_session_id,
            make_trace_metadata,
            reset_session_id,
        )

        old_session = get_session_id()
        new_session = reset_session_id()
        assert old_session != new_session
        meta = make_trace_metadata(domain_id="D1")
        assert meta["session_id"] == new_session

    def test_optional_fields_excluded_when_empty(self):
        from asopb.llm.langfuse_integration import make_trace_metadata

        meta = make_trace_metadata(domain_id="D5")
        assert "asopb_control" not in meta
        assert "asopb_tier" not in meta

    def test_phase_field(self):
        from asopb.llm.langfuse_integration import make_trace_metadata

        meta = make_trace_metadata(
            domain_id="D4", phase="implementation_grading"
        )
        assert meta["asopb_phase"] == "implementation_grading"


class TestLLMClientMetadataPassthrough:
    """Test that LLMClient passes metadata to litellm.acompletion."""

    @pytest.mark.asyncio
    async def test_metadata_forwarded_to_acompletion(self):
        from asopb.llm.client import LLMClient

        config = LLMConfig(
            model="test-model",
            cache_enabled=False,
            rate_limit_rpm=1000,
        )
        client = LLMClient(config)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"t1_score": 7, "rationale": "good"}'
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50

        with patch.object(client.litellm, "acompletion", new_callable=AsyncMock) as mock_acomplete:
            mock_acomplete.return_value = mock_response

            await client.complete(
                system="test system",
                user="test user",
                metadata={"asopb_domain": "D4", "asopb_control": "D4.1"},
            )

            mock_acomplete.assert_called_once()
            call_kwargs = mock_acomplete.call_args[1]
            assert call_kwargs["metadata"] == {
                "asopb_domain": "D4",
                "asopb_control": "D4.1",
            }

    @pytest.mark.asyncio
    async def test_no_metadata_when_none(self):
        from asopb.llm.client import LLMClient

        config = LLMConfig(
            model="test-model",
            cache_enabled=False,
            rate_limit_rpm=1000,
        )
        client = LLMClient(config)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "response"
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 25

        with patch.object(client.litellm, "acompletion", new_callable=AsyncMock) as mock_acomplete:
            mock_acomplete.return_value = mock_response

            await client.complete(system="test", user="test")

            call_kwargs = mock_acomplete.call_args[1]
            assert "metadata" not in call_kwargs


class TestLLMClientLangfuseInit:
    """Test LLMClient initialization with LangfuseConfig."""

    def test_langfuse_enabled_when_config_provided(self):
        from asopb.llm.client import LLMClient

        config = LLMConfig(model="test-model", cache_enabled=False)
        langfuse_config = LangfuseConfig(
            enabled=True,
            public_key="pk-lf-test",
            secret_key="sk-lf-test",
        )

        import litellm
        litellm.success_callback = []
        litellm.failure_callback = []

        client = LLMClient(config, langfuse_config=langfuse_config)
        assert client.langfuse_enabled is True
        assert "langfuse" in litellm.success_callback

        litellm.success_callback = []
        litellm.failure_callback = []

    def test_langfuse_disabled_when_no_config(self):
        from asopb.llm.client import LLMClient

        config = LLMConfig(model="test-model", cache_enabled=False)
        client = LLMClient(config)
        assert client.langfuse_enabled is False


class TestDomainEvaluatorTraceMetadata:
    """Test that DomainEvaluator LLM calls include trace metadata."""

    @pytest.mark.asyncio
    async def test_t1_grading_includes_metadata(self):
        from asopb.domains.base import DomainEvaluator
        from asopb.models import ControlDefinition, ControlScore, ControlStatus

        config = EvalConfig(skip_llm=False)

        mock_client = MagicMock()
        mock_client.complete = AsyncMock(
            return_value='{"t1_score": 8.0, "rationale": "Strong design"}'
        )
        mock_client.get_token_usage = MagicMock(return_value={"total_tokens": 500})

        class TestDomain(DomainEvaluator):
            domain_id = "D4"
            domain_name = "Identity"
            skill_file = ""

            def define_controls(self):
                return [
                    ControlDefinition(
                        control_id="D4.1",
                        domain_id="D4",
                        name="Agent Identity",
                        description="Test",
                        t1_criteria=["Design exists"],
                    )
                ]

            def required_scanners(self):
                return []

            def required_analyzers(self):
                return []

            async def score_controls(self, scan_results, analyzer_results):
                return [
                    ControlScore(
                        control_id="D4.1",
                        control_name="Agent Identity",
                        status=ControlStatus.PARTIALLY_IMPLEMENTED,
                        t1_score=3.0,
                        t1_floor=3.0,
                        t2_score=5.0,
                        t2_floor=5.0,
                    )
                ]

        evaluator = TestDomain(config=config, llm_client=mock_client)
        evaluator._skill_content = "You are a security evaluator."
        evaluator._controls = evaluator.define_controls()

        scores = [
            ControlScore(
                control_id="D4.1",
                control_name="Agent Identity",
                status=ControlStatus.PARTIALLY_IMPLEMENTED,
                t1_score=3.0,
                t1_floor=3.0,
                t2_score=5.0,
                t2_floor=5.0,
            )
        ]

        result = await evaluator._llm_enhance_scores(scores, {}, {})

        mock_client.complete.assert_called_once()
        call_kwargs = mock_client.complete.call_args[1]
        assert "metadata" in call_kwargs
        assert call_kwargs["metadata"]["asopb_domain"] == "D4"
        assert call_kwargs["metadata"]["asopb_control"] == "D4.1"
        assert call_kwargs["metadata"]["asopb_tier"] == "T1"
        assert call_kwargs["metadata"]["asopb_phase"] == "design_assessment"

    @pytest.mark.asyncio
    async def test_summary_includes_metadata(self):
        from asopb.domains.base import DomainEvaluator
        from asopb.models import ControlScore, ControlStatus

        config = EvalConfig(skip_llm=False)

        mock_client = MagicMock()
        mock_client.complete = AsyncMock(return_value="Domain is well-secured.")
        mock_client.get_token_usage = MagicMock(return_value={"total_tokens": 200})

        class TestDomain(DomainEvaluator):
            domain_id = "D8"
            domain_name = "Supply Chain"
            skill_file = ""

            def define_controls(self):
                return []

            def required_scanners(self):
                return []

            def required_analyzers(self):
                return []

            async def score_controls(self, scan_results, analyzer_results):
                return []

        evaluator = TestDomain(config=config, llm_client=mock_client)

        scores = [
            ControlScore(
                control_id="D8.1",
                control_name="Dependency Integrity",
                status=ControlStatus.NOT_A_FINDING,
                t1_score=9.0,
                t2_score=8.0,
            )
        ]

        await evaluator._generate_summary(scores)

        mock_client.complete.assert_called_once()
        call_kwargs = mock_client.complete.call_args[1]
        assert call_kwargs["metadata"]["asopb_domain"] == "D8"
        assert call_kwargs["metadata"]["asopb_tier"] == "summary"
        assert call_kwargs["metadata"]["asopb_phase"] == "report_generation"
