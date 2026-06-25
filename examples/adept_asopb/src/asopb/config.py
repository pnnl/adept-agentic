"""
ASOPB Configuration

Pydantic Settings for the evaluation framework.  Configuration can come from
environment variables (ASOPB_ prefix), a config file, or direct construction.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """LiteLLM configuration for LLM-assisted evaluation."""
    model: str = os.getenv("ASOPB_LLM_MODEL", "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    fallback_model: Optional[str] = os.getenv("ASOPB_LLM_FALLBACK_MODEL", "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0")
    api_base: Optional[str] = None
    temperature: float = 0.1          # Low temperature for consistent scoring
    max_tokens: int = 4096
    rate_limit_rpm: int = 30          # Requests per minute
    timeout_seconds: int = 120
    cache_enabled: bool = True        # Cache LLM responses keyed on (file_hash, skill, model)
    cache_dir: Optional[Path] = None


class LangfuseConfig(BaseModel):
    """Langfuse observability configuration for LLM evaluation telemetry."""
    enabled: bool = os.getenv("ASOPB_LANGFUSE_ENABLED", "false").lower() == "true"
    public_key: Optional[str] = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key: Optional[str] = os.getenv("LANGFUSE_SECRET_KEY")
    host: Optional[str] = os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000")
    project_name: str = os.getenv("ASOPB_LANGFUSE_PROJECT", "asopb-evaluator")
    debug: bool = os.getenv("LANGFUSE_DEBUG", "false").lower() == "true"


class AnalyzerConfig(BaseModel):
    """Configuration for external analysis tools."""
    enabled: list[str] = Field(
        default_factory=lambda: [
            "gitxray", "semgrep", "bandit", "pip_audit", "dockerfile", "tls"
        ]
    )
    disabled: list[str] = Field(default_factory=list)
    timeout_seconds: int = 300        # Per-analyzer timeout
    semgrep_rules: Optional[str] = None  # Custom Semgrep ruleset path
    bandit_config: Optional[str] = None  # Custom Bandit config path


class ScannerConfig(BaseModel):
    """Configuration for scanner selection."""
    enabled: list[str] = Field(default_factory=list)
    disabled: list[str] = Field(default_factory=list)

    def effective_scanners(self, available: list[str]) -> list[str]:
        """Return filtered scanner list based on enabled/disabled config."""
        if self.enabled:
            pool = [s for s in self.enabled if s in available]
        else:
            pool = available
        return [s for s in pool if s not in self.disabled]


class ScoringConfig(BaseModel):
    """Scoring engine configuration."""
    domain_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "D1": 1.5,   # Foundation Model Integrity
            "D2": 1.0,   # Orchestration Security
            "D3": 1.0,   # Tool and MCP Security
            "D4": 1.0,   # Identity and Authentication
            "D5": 1.0,   # Federation and Trust
            "D6": 1.0,   # Observability and Audit
            "D7": 1.5,   # IT/OT Convergence
            "D8": 1.0,   # Ecosystem and Supply Chain
        }
    )
    # Custom controls YAML file (supplements built-in controls)
    custom_controls_path: Optional[Path] = None
    # Domains to evaluate (None = all applicable)
    domains_to_evaluate: Optional[list[str]] = None
    # Stage hint for applicability determination
    stage_hint: Optional[str] = None  # "S1", "S2", "S3", "S4"
    # Scoring mode: "composite" (T1+T2+T3 average) or "pipeline" (penalty-based)
    scoring_mode: str = "composite"


class EvidenceStoreConfig(BaseModel):
    """Configuration for the SQLite evidence store."""
    enabled: bool = True
    db_path: Optional[Path] = Path("/output/asopb_evidence.db")
    auto_commit: bool = True


class RedTeamConfig(BaseModel):
    """Configuration for red-team report ingestion and simulator plugins."""
    report_paths: list[Path] = Field(default_factory=list)    # Pre-existing RT report JSON files
    promptfoo_output_paths: list[Path] = Field(default_factory=list)  # Promptfoo eval JSON outputs
    simulator_plugins: list[str] = Field(default_factory=list)  # Plugin module paths
    simulator_timeout_seconds: int = 600


class EvalConfig(BaseModel):
    """Top-level evaluation configuration.

    Usage:
        config = EvalConfig(llm=LLMConfig(model="gpt-4o"))
        evaluator = Evaluator(config=config)
    """
    # Sub-configs
    llm: LLMConfig = Field(default_factory=LLMConfig)
    langfuse: LangfuseConfig = Field(default_factory=LangfuseConfig)
    analyzers: AnalyzerConfig = Field(default_factory=AnalyzerConfig)
    scanners: ScannerConfig = Field(default_factory=ScannerConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    evidence_store: EvidenceStoreConfig = Field(default_factory=EvidenceStoreConfig)
    red_team: RedTeamConfig = Field(default_factory=RedTeamConfig)

    # Global settings
    skip_llm: bool = False            # Run without LLM (deterministic-only)
    verbose: bool = False
    max_concurrency: int = 8          # Max concurrent scanner/analyzer tasks
    output_dir: Optional[Path] = None # Where to write reports and evidence bundles

    # Token budget ceiling for T2 LLM grading (0 = no limit)
    token_budget: int = int(os.getenv("ASOPB_TOKEN_BUDGET", "0"))
    token_budget_auto_confirm: bool = False  # Skip human gate (CI mode)

    # Framework metadata override (auto-detected if not provided)
    framework_name: Optional[str] = None
    framework_version: Optional[str] = None

    @classmethod
    def from_yaml(cls, path: Path) -> "EvalConfig":
        """Load configuration from a YAML file."""
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def effective_analyzers(self) -> list[str]:
        """Return the list of analyzers to run (enabled minus disabled)."""
        return [a for a in self.analyzers.enabled if a not in self.analyzers.disabled]
