"""
ASOPB Main Evaluator Orchestrator

Coordinates the full evaluation pipeline:
1. Framework version detection from git
2. Concurrent scanner execution
3. Concurrent analyzer execution
4. Red-team report ingestion
5. Simulator plugin execution
6. Per-domain evaluation
7. ASPI calculation
8. Report generation and export
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from asopb.aivss import (
    AgentProfileBuilder,
    AIVSSCalculator,
)
from asopb.config import EvalConfig
from asopb.domains.registry import DomainRegistry
from asopb.logging import get_logger, timed
from asopb.models import (
    Applicability,
    DomainResult,
    EvaluationReport,
    FrameworkVersion,
    RedTeamReport,
    ScanResult,
)
from asopb.redteam import PromptfooIngester

logger = get_logger(__name__)


class ASPICalculator:
    """Calculate Agentic Security Posture Index from domain results."""

    @staticmethod
    def calculate(domains: dict[str, DomainResult]) -> float:
        """Calculate weighted ASPI across all applicable domains."""
        numerator = 0.0
        denominator = 0.0

        for domain in domains.values():
            if domain.applicability == Applicability.NOT_APPLICABLE:
                continue
            score = domain.domain_score
            if score is None:
                continue
            numerator += domain.weight * score
            denominator += domain.weight

        if denominator == 0:
            return 0.0
        return round(numerator / denominator, 1)


class FrameworkVersionDetector:
    """Auto-detect framework version from git metadata."""

    @staticmethod
    def detect(repo_path: str | Path) -> FrameworkVersion:
        """Detect framework version from git commit, branch, tag, and remote."""
        repo_path = Path(repo_path)

        # Try to read git metadata
        git_commit = None
        git_branch = None
        git_tag = None
        source_url = None

        try:
            git_dir = repo_path / ".git"
            if git_dir.exists():
                # Get current commit
                result = subprocess.run(
                    ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    git_commit = result.stdout.strip()

                # Get current branch
                result = subprocess.run(
                    ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    git_branch = result.stdout.strip()

                # Get current tag (if on one)
                result = subprocess.run(
                    ["git", "-C", str(repo_path), "describe", "--tags", "--exact-match"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    git_tag = result.stdout.strip()

                # Get remote URL
                result = subprocess.run(
                    ["git", "-C", str(repo_path), "config", "--get", "remote.origin.url"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    source_url = result.stdout.strip()
        except Exception as e:
            logger.warning(f"Failed to detect git metadata: {e}")

        # Infer framework name from directory
        framework_name = repo_path.name or "unknown-framework"

        # Build version object
        return FrameworkVersion(
            name=framework_name,
            git_commit=git_commit,
            git_branch=git_branch,
            git_tag=git_tag,
            source_url=source_url,
            snapshot_date=datetime.now(timezone.utc),
        )


class Evaluator:
    """Main ASOPB evaluation orchestrator."""

    def __init__(self, config: EvalConfig | None = None):
        """Initialize evaluator with configuration.

        Args:
            config: EvalConfig instance. If None, uses defaults.
        """
        self.config = config or EvalConfig()
        self.llm_client: Optional[Any] = None
        self._scanners: dict[str, Any] = {}
        self._analyzers: dict[str, Any] = {}
        self._registry: Optional[DomainRegistry] = None

        # Configure logging level based on verbosity
        import os
        if self.config.verbose:
            os.environ.setdefault("ASOPB_LOG_LEVEL", "DEBUG")
        else:
            os.environ.setdefault("ASOPB_LOG_LEVEL", "INFO")

    def estimate_t2_token_budget(self) -> dict[str, Any]:
        """Estimate token budget for T2 LLM grading before execution.

        Calculates expected token consumption based on:
        - Number of domains to evaluate
        - Controls per domain eligible for T2 grading
        - Skill file sizes (system prompts)
        - Context cap (4000 chars per call)

        Returns:
            Dict with keys: estimated_calls, estimated_input_tokens,
            estimated_output_tokens, estimated_total_tokens, per_domain breakdown,
            exceeds_budget (bool), budget_limit.
        """
        registry = DomainRegistry(self.config, llm_client=None)
        domains_to_eval = self.config.scoring.domains_to_evaluate or [
            "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"
        ]

        per_domain = {}
        total_calls = 0
        total_input = 0
        total_output = 0

        for domain_id in domains_to_eval:
            evaluator = registry.get_evaluator(domain_id)
            if not evaluator:
                continue

            controls = evaluator.define_controls()
            eligible = len([c for c in controls if c.t2_criteria])

            skill_path = (
                Path(__file__).parent / "skills" / evaluator.skill_file
                if evaluator.skill_file else None
            )
            skill_tokens = 0
            if skill_path and skill_path.is_file():
                skill_tokens = len(skill_path.read_text()) // 4

            context_tokens = 1000  # context[:4000] / 4
            prompt_tokens = 250   # control def + criteria
            input_per_call = skill_tokens + context_tokens + prompt_tokens
            output_per_call = 200  # JSON response

            domain_calls = eligible
            domain_input = domain_calls * input_per_call
            domain_output = domain_calls * output_per_call

            per_domain[domain_id] = {
                "controls_total": len(controls),
                "controls_t2_eligible": eligible,
                "skill_tokens": skill_tokens,
                "input_per_call": input_per_call,
                "calls": domain_calls,
                "input_tokens": domain_input,
                "output_tokens": domain_output,
            }

            total_calls += domain_calls
            total_input += domain_input
            total_output += domain_output

        total = total_input + total_output
        budget = self.config.token_budget

        return {
            "estimated_calls": total_calls,
            "estimated_input_tokens": total_input,
            "estimated_output_tokens": total_output,
            "estimated_total_tokens": total,
            "per_domain": per_domain,
            "budget_limit": budget,
            "exceeds_budget": budget > 0 and total > budget,
        }

    @timed
    async def evaluate(self, repo_path: str | Path) -> EvaluationReport:
        """Full evaluation pipeline.

        Args:
            repo_path: Path to the repository to evaluate.

        Returns:
            Complete EvaluationReport with all scores and evidence.
        """
        repo_path = Path(repo_path)
        start_time = time.time()
        report_warnings: list[str] = []

        # 1. Detect framework version
        logger.info("Detecting framework version...")
        framework = FrameworkVersion(name="unknown")
        if not self.config.framework_name or not self.config.framework_version:
            framework = FrameworkVersionDetector.detect(repo_path)
            if self.config.framework_name:
                framework.name = self.config.framework_name
            if self.config.framework_version:
                framework.version = self.config.framework_version

        # 2. Initialize LLM client if needed
        if not self.config.skip_llm:
            self.llm_client = self._initialize_llm_client()

        # 3. Run scanners concurrently
        logger.info("Running scanners...")
        scan_results = await self.quick_scan(str(repo_path))

        # 4. Run analyzers concurrently
        logger.info("Running analyzers...")
        analyzer_results = await self._run_analyzers(str(repo_path))

        # 5. Load red-team reports
        logger.info("Loading red-team reports...")
        red_team_reports = self._load_red_team_reports()

        # 6. Run simulator plugins if configured
        logger.info("Running simulator plugins...")
        simulator_reports = await self._run_simulators(str(repo_path))
        red_team_reports.extend(simulator_reports)

        # 7. Evaluate each domain
        logger.info("Evaluating domains...")
        domains = await self._evaluate_all_domains(
            scan_results, analyzer_results, red_team_reports
        )

        # 7b. AIVSS scoring (auto-derive agent profile, score all findings)
        logger.info("Running AIVSS scoring...")
        agent_profile = AgentProfileBuilder.from_scan_results(
            scan_results, analyzer_results, framework_name=framework.name,
        )
        aivss_calculator = AIVSSCalculator(agent_profile)
        aivss_report = aivss_calculator.score_all_findings(analyzer_results)

        # 8. Build report
        duration = time.time() - start_time
        report = EvaluationReport(
            framework=framework,
            timestamp=datetime.now(timezone.utc),
            config_snapshot=self.config.model_dump(),
            scan_results=scan_results,
            analyzer_results=analyzer_results,
            red_team_reports=red_team_reports,
            domains=domains,
            aivss_summary={
                "agent_profile": agent_profile.model_dump(),
                "max_aivss": aivss_report.max_aivss,
                "mean_aivss": aivss_report.mean_aivss,
                "critical_count": aivss_report.critical_count,
                "high_count": aivss_report.high_count,
                "scored_findings": len(aivss_report.scores),
                "domain_impact": {
                    k: len(v) for k, v in aivss_report.domain_impact_summary().items()
                },
            } if aivss_report.scores else None,
            evaluation_duration_seconds=duration,
            llm_calls_made=getattr(self.llm_client, "call_count", 0) if self.llm_client else 0,
            llm_tokens_used=getattr(self.llm_client, "token_count", 0) if self.llm_client else 0,
            warnings=report_warnings,
        )

        # 9. Save to evidence store if configured
        if self.config.evidence_store.enabled:
            await self._save_to_evidence_store(report)

        # 10. Export evidence bundle if output_dir configured
        if self.config.output_dir:
            bundle_path = report.to_evidence_bundle(self.config.output_dir)
            logger.info(f"Evidence bundle exported to {bundle_path}")

        logger.info(f"Evaluation complete. ASPI: {report.aspi}")
        return report

    async def evaluate_domain(self, repo_path: str, domain_id: str) -> DomainResult:
        """Evaluate a single domain.

        Args:
            repo_path: Path to repository.
            domain_id: Domain ID (e.g., "D1", "D2").

        Returns:
            DomainResult for the specified domain.
        """
        repo_path = Path(repo_path)

        # Get scan results
        scan_results = await self.quick_scan(str(repo_path))
        analyzer_results = await self._run_analyzers(str(repo_path))
        red_team_reports = self._load_red_team_reports()

        # Get evaluator for domain
        evaluator = self._get_domain_evaluator(domain_id)
        if not evaluator:
            raise ValueError(f"No evaluator found for domain {domain_id}")

        return await evaluator.evaluate(scan_results, analyzer_results, red_team_reports)

    @timed
    async def quick_scan(self, repo_path: str) -> dict[str, ScanResult]:
        """Quick scan with scanners only (no LLM, no red-team).

        Args:
            repo_path: Path to repository.

        Returns:
            Dict of scanner_name -> ScanResult.
        """
        repo_path = Path(repo_path)
        results = {}

        scanner_names = self._discover_scanners()
        logger.info(f"quick_scan: {len(scanner_names)} scanners: {scanner_names}")

        if self.config.verbose and RICH_AVAILABLE:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
            ) as progress:
                task = progress.add_task("Running scanners...", total=len(scanner_names))
                for scanner_name in scanner_names:
                    result = await self._run_scanner(scanner_name, str(repo_path))
                    results[scanner_name] = result
                    progress.update(task, advance=1)
        else:
            for scanner_name in scanner_names:
                result = await self._run_scanner(scanner_name, str(repo_path))
                results[scanner_name] = result

        total_findings = sum(r.finding_count for r in results.values())
        logger.info(f"quick_scan: {len(results)} scanners, {total_findings} total findings")
        for name, res in results.items():
            status = "OK" if res.success else "FAILED"
            logger.info(f"  [{status}] {name}: {res.finding_count} findings")

        return results

    # ========================================================================
    # Private methods
    # ========================================================================

    def _initialize_llm_client(self) -> Optional[Any]:
        """Initialize LLM client (liteLLM or compatible)."""
        try:
            import litellm
            litellm.drop_params = True

            from asopb.llm.langfuse_integration import configure_langfuse, reset_session_id
            if self.config.langfuse.enabled:
                reset_session_id()
                configure_langfuse(self.config.langfuse)

            return LiteLLMClient(self.config.llm)
        except ImportError:
            logger.warning("litellm not installed; LLM features disabled")
            return None

    @timed
    async def _run_scanner(self, scanner_name: str, repo_path: str) -> ScanResult:
        """Run a single scanner and return results."""
        from asopb.scanner import get_scanner

        scanner_cls = get_scanner(scanner_name)
        if scanner_cls is None:
            logger.warning(f"Scanner '{scanner_name}' not found in registry")
            return ScanResult(tool_name=scanner_name, success=False, findings=[])

        logger.debug(f"Resolved '{scanner_name}' → {scanner_cls.__name__}")
        try:
            scanner = scanner_cls(Path(repo_path))
            result = await scanner.scan()
        except Exception as e:
            logger.error(f"Scanner '{scanner_name}': {type(e).__name__}: {e}")
            return ScanResult(tool_name=scanner_name, success=False, findings=[])

        logger.info(f"Scanner '{scanner_name}': {result.finding_count} findings")
        return result

    @timed
    def _discover_scanners(self) -> list[str]:
        """Discover available scanners from the registry, filtered by config."""
        from asopb.scanner import get_registry

        all_names = get_registry().list_names()
        names = self.config.scanners.effective_scanners(all_names)
        if len(names) < len(all_names):
            logger.info(f"Registry scanners: {all_names} (filtered to: {names})")
        else:
            logger.info(f"Registry scanners: {names}")
        return names

    @timed
    async def _run_analyzers(self, repo_path: str) -> dict[str, ScanResult]:
        """Run configured analyzers via AnalyzerRegistry."""
        from asopb.analyzers import (
            AnalyzerRegistry,
            BanditAnalyzer,
            DockerfileAnalyzer,
            GitXRayAnalyzer,
            PipAuditAnalyzer,
            SemgrepAnalyzer,
            TLSAnalyzer,
        )

        registry = AnalyzerRegistry()
        for cls in (GitXRayAnalyzer, SemgrepAnalyzer, BanditAnalyzer,
                    PipAuditAnalyzer, DockerfileAnalyzer, TLSAnalyzer):
            registry.register(cls)

        enabled = set(self.config.effective_analyzers())
        timeout = self.config.analyzers.timeout_seconds
        path = Path(repo_path)

        available = registry.discover_available(path, timeout=timeout)
        active = [a for a in available if a.name in enabled]
        skipped = [a.name for a in available if a.name not in enabled]

        if skipped:
            logger.info(f"Analyzers skipped (disabled): {skipped}")
        logger.info(f"Analyzers active: {[a.name for a in active]} (available: {len(available)}/{len(registry._analyzers)})")

        results = {}
        for analyzer in active:
            try:
                result = await asyncio.wait_for(analyzer.analyze(), timeout=timeout)
                results[analyzer.name] = result
                logger.info(f"Analyzer '{analyzer.name}': {result.finding_count} findings")
            except asyncio.TimeoutError:
                logger.warning(f"Analyzer '{analyzer.name}' timed out after {timeout}s")
                results[analyzer.name] = ScanResult(
                    tool_name=analyzer.name, success=False, error_message="Timeout",
                )
            except Exception as e:
                logger.warning(f"Analyzer '{analyzer.name}' failed: {type(e).__name__}: {e}")
                results[analyzer.name] = ScanResult(
                    tool_name=analyzer.name, success=False, error_message=str(e),
                )

        return results

    def _load_red_team_reports(self) -> list[RedTeamReport]:
        """Load red-team reports from configured paths and promptfoo outputs."""
        reports = []

        # Load pre-formatted RedTeamReport JSON files
        for report_path in self.config.red_team.report_paths:
            report_path = Path(report_path)
            if not report_path.exists():
                logger.warning(f"Red-team report not found: {report_path}")
                continue

            try:
                data = json.loads(report_path.read_text())
                report = RedTeamReport(**data)
                reports.append(report)
                logger.debug(f"Loaded red-team report: {report.report_id}")
            except Exception as e:
                logger.warning(f"Failed to load red-team report {report_path}: {e}")

        # Ingest promptfoo eval JSON outputs via PromptfooIngester
        for pf_path in self.config.red_team.promptfoo_output_paths:
            pf_path = Path(pf_path)
            if not pf_path.exists():
                logger.warning(f"Promptfoo output not found: {pf_path}")
                continue

            try:
                ingester = PromptfooIngester(
                    name=f"promptfoo-{pf_path.stem}",
                    provider_label=pf_path.stem,
                )
                report = ingester.ingest(pf_path)
                reports.append(report)
                logger.info(
                    "Ingested promptfoo report %s: %d scenarios (%d bypasses)",
                    pf_path.name,
                    len(report.scenarios),
                    sum(1 for s in report.scenarios if "bypass" in s.outcome),
                )
            except Exception as e:
                logger.warning(f"Failed to ingest promptfoo output {pf_path}: {e}")

        return reports

    async def _run_simulators(self, repo_path: str) -> list[RedTeamReport]:
        """Run simulator plugins and return generated reports."""
        reports = []

        for plugin_path in self.config.red_team.simulator_plugins:
            try:
                # Dynamically import plugin
                import importlib.util
                spec = importlib.util.spec_from_file_location("simulator", plugin_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # Call plugin's main function
                    if hasattr(module, "run"):
                        timeout = self.config.red_team.simulator_timeout_seconds
                        result = await asyncio.wait_for(
                            module.run(repo_path), timeout=timeout
                        )
                        if isinstance(result, RedTeamReport):
                            reports.append(result)
                        elif isinstance(result, list):
                            reports.extend(result)
            except Exception as e:
                logger.warning(f"Simulator plugin failed: {plugin_path}: {e}")

        return reports

    @timed
    async def _evaluate_all_domains(
        self,
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
        red_team_reports: list[RedTeamReport],
    ) -> dict[str, DomainResult]:
        """Evaluate all applicable domains."""
        if self._registry is None:
            self._registry = DomainRegistry(self.config, self.llm_client)

        domains = {}
        domain_ids = self.config.scoring.domains_to_evaluate or [
            "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"
        ]

        scan_finding_counts = {k: v.finding_count for k, v in scan_results.items()}
        logger.info(
            f"Input: scan_results={scan_finding_counts}, "
            f"analyzers={len(analyzer_results)}, red_team={len(red_team_reports)}"
        )

        for domain_id in domain_ids:
            dt0 = time.perf_counter()
            evaluator = self._registry.get_evaluator(domain_id)
            if not evaluator:
                logger.warning(f"No evaluator for {domain_id}")
                continue
            try:
                result = await evaluator.evaluate(
                    scan_results, analyzer_results, red_team_reports
                )
                domains[domain_id] = result
                logger.info(
                    f"  {domain_id} ({evaluator.__class__.__name__}): "
                    f"score={result.domain_score:.1f}, "
                    f"controls={len(result.controls)}, "
                    f"{time.perf_counter() - dt0:.3f}s"
                )
            except Exception as e:
                logger.warning(
                    f"  {domain_id} FAILED ({time.perf_counter() - dt0:.3f}s): "
                    f"{type(e).__name__}: {e}"
                )

        logger.info(f"Scored {len(domains)}/{len(domain_ids)} domains")
        return domains

    def _get_domain_evaluator(self, domain_id: str) -> Optional[Any]:
        """Get or instantiate a domain evaluator via the registry."""
        if self._registry is None:
            self._registry = DomainRegistry(self.config, self.llm_client)
        return self._registry.get_evaluator(domain_id)

    async def _save_to_evidence_store(self, report: EvaluationReport) -> None:
        """Save report to evidence store (SQLite)."""
        try:
            from asopb.evidence_store import EvidenceStore

            db_path = self.config.evidence_store.db_path
            store = EvidenceStore(db_path)
            store.save_evaluation(report)
            logger.info(f"Report saved to evidence store: {db_path}")
        except ImportError:
            logger.warning("Evidence store not available (asopb.evidence_store not found)")
        except Exception as e:
            logger.warning(f"Failed to save to evidence store: {e}")


class LiteLLMClient:
    """Wrapper around liteLLM for standardized LLM access."""

    def __init__(self, config):
        self.config = config
        self.call_count = 0
        self.token_count = 0

    async def complete(self, system: str, user: str, metadata: dict = None, **kwargs) -> str:
        """Get LLM completion."""
        try:
            import litellm

            call_kwargs = {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            }
            if metadata:
                call_kwargs["metadata"] = metadata
            call_kwargs.update(kwargs)

            response = await asyncio.to_thread(
                litellm.completion,
                **call_kwargs,
            )

            self.call_count += 1
            if hasattr(response, "usage"):
                self.token_count += response.usage.total_tokens

            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM completion failed: {e}")
            raise

    def get_token_usage(self) -> dict[str, int]:
        """Return cumulative token usage."""
        return {"total_tokens": self.token_count, "call_count": self.call_count}
