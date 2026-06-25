"""
Domain Evaluator Base Class

Domain evaluators are Layer 3 of the pipeline.  Each evaluator:
1. Consumes scan results and analyzer results relevant to its domain
2. Loads its LLM skill markdown for evaluation guidance
3. Uses deterministic rules for T2 floor scoring
4. Optionally uses LLM for T1 qualitative design assessment
5. Ingests red-team results for T3 adversarial scoring
6. Produces a DomainResult with per-control scores
"""

from __future__ import annotations

import importlib.resources
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from asopb.config import EvalConfig
from asopb.llm.langfuse_integration import make_trace_metadata
from asopb.logging import get_logger

logger = get_logger(__name__)
from asopb.models import (
    Applicability,
    ControlDefinition,
    ControlEvidence,
    ControlScore,
    ControlStatus,
    DomainResult,
    EvidenceSource,
    EvidenceTier,
    RedTeamReport,
    ScanResult,
    Severity,
)


class DomainEvaluator(ABC):
    """Abstract base for ASOPB domain evaluators (D1–D8).

    Subclasses define their controls, required scanners/analyzers,
    and implement the scoring logic.
    """

    domain_id: str = ""          # "D1" through "D8"
    domain_name: str = ""
    weight: float = 1.0
    skill_file: str = ""         # Filename in skills/ directory

    def __init__(self, config: EvalConfig, llm_client: Any = None):
        self.config = config
        self.llm_client = llm_client
        self._controls: list[ControlDefinition] = []
        self._skill_content: Optional[str] = None

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def define_controls(self) -> list[ControlDefinition]:
        """Return the control definitions for this domain.

        Built-in controls are defined here.  User-provided custom controls
        from YAML are merged in by the registry.
        """
        ...

    @abstractmethod
    def required_scanners(self) -> list[str]:
        """Scanner names that must run before this domain evaluates."""
        ...

    @abstractmethod
    def required_analyzers(self) -> list[str]:
        """Analyzer names needed (optional — graceful degradation)."""
        ...

    @abstractmethod
    async def score_controls(
        self,
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
    ) -> list[ControlScore]:
        """Score all controls using scan + analyzer evidence.

        This is where the deterministic floor is calculated.
        """
        ...

    # ------------------------------------------------------------------
    # Evaluation pipeline
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
        red_team_reports: Optional[list[RedTeamReport]] = None,
    ) -> DomainResult:
        """Full domain evaluation: deterministic + LLM + red-team."""

        # Check applicability
        applicability = self.check_applicability(scan_results)
        if applicability == Applicability.NOT_APPLICABLE:
            return DomainResult(
                domain_id=self.domain_id,
                domain_name=self.domain_name,
                applicability=Applicability.NOT_APPLICABLE,
                weight=self.weight,
            )

        # Phase 1: Deterministic scoring (sets floor)
        control_scores = await self.score_controls(scan_results, analyzer_results)

        # Phase 2a: LLM-assisted T1 assessment (raises above floor, never lowers)
        if self.llm_client and not self.config.skip_llm:
            control_scores = await self._llm_enhance_scores(
                control_scores, scan_results, analyzer_results
            )

        # Phase 2b: LLM-assisted T2 assessment (implementation quality grading)
        if self.llm_client and not self.config.skip_llm:
            control_scores = await self._llm_assess_t2(
                control_scores, scan_results, analyzer_results
            )

        # Phase 3: Red-team T3 scoring
        if red_team_reports:
            control_scores = self._apply_red_team_scores(
                control_scores, red_team_reports
            )

        # Generate summary
        summary = await self._generate_summary(control_scores) if self.llm_client else ""

        return DomainResult(
            domain_id=self.domain_id,
            domain_name=self.domain_name,
            applicability=applicability,
            weight=self.weight,
            controls=control_scores,
            summary=summary,
        )

    def check_applicability(self, scan_results: dict[str, ScanResult]) -> Applicability:
        """Determine if this domain is applicable to the target system.

        Override in subclasses for domain-specific logic (e.g., D5 is N/A
        if no federation patterns are detected, D7 is N/A if no OT interface).
        Default: always applicable.
        """
        return Applicability.APPLICABLE

    # ------------------------------------------------------------------
    # LLM integration
    # ------------------------------------------------------------------

    async def _llm_enhance_scores(
        self,
        control_scores: list[ControlScore],
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
    ) -> list[ControlScore]:
        """Use LLM with domain skill to enhance T1 design assessment.

        The LLM can raise T1 scores above the deterministic floor but
        cannot lower T2 scores below it.
        """
        skill = self._load_skill()
        if not skill or not self.llm_client:
            return control_scores

        # Build context from findings
        context = self._build_llm_context(scan_results, analyzer_results)

        for score in control_scores:
            control_def = self._get_control_def(score.control_id)
            if not control_def:
                continue

            prompt = (
                f"Evaluate control {score.control_id}: {control_def.name}\n"
                f"Description: {control_def.description}\n\n"
                f"T1 criteria: {control_def.t1_criteria}\n"
                f"Current T1 floor: {score.t1_floor}\n"
                f"Current T2 floor: {score.t2_floor}\n\n"
                f"Evidence found:\n"
            )
            for ev in score.evidence:
                prompt += f"  - [{ev.tier.value}] {ev.description}\n"

            prompt += (
                f"\nBased on the codebase evidence, provide a T1 (design) score "
                f"from 0-10. The score must be >= {score.t1_floor} (deterministic floor). "
                f"Respond with ONLY a JSON object: "
                f'{{"t1_score": <number>, "rationale": "<brief explanation>"}}'
            )

            try:
                logger.info(
                    f"  [{self.domain_id}] T1 grading {score.control_id} "
                    f"(floor={score.t1_floor:.1f})..."
                )
                response = await self.llm_client.complete(
                    system=skill,
                    user=f"Context:\n{context[:4000]}\n\n{prompt}",
                    metadata=make_trace_metadata(
                        domain_id=self.domain_id,
                        control_id=score.control_id,
                        tier="T1",
                        phase="design_assessment",
                    ),
                )
                import json
                result = json.loads(response)
                new_t1 = float(result.get("t1_score", score.t1_floor))
                # Enforce floor
                score.t1_score = max(new_t1, score.t1_floor)
                usage = self.llm_client.get_token_usage()
                logger.info(
                    f"  [{self.domain_id}] T1 {score.control_id}: "
                    f"{score.t1_floor:.1f} -> {score.t1_score:.1f} "
                    f"(tokens: {usage['total_tokens']})"
                )
                if result.get("rationale"):
                    score.evidence.append(ControlEvidence(
                        tier=EvidenceTier.T1_DESIGN,
                        source=EvidenceSource.LLM,
                        source_tool=f"llm:{self.domain_id}",
                        description=result["rationale"],
                        confidence=0.7,
                    ))
            except Exception as e:
                logger.warning(
                    f"  [{self.domain_id}] T1 {score.control_id} LLM failed: {e}"
                )

        return control_scores

    async def _llm_assess_t2(
        self,
        control_scores: list[ControlScore],
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
    ) -> list[ControlScore]:
        """Use LLM to grade implementation quality (T2) for controls.

        For controls where T1 > 0 (evidence exists) but T2 == t2_floor
        (no analyzer produced a higher score), ask the LLM to evaluate
        whether the implementation meets the control's T2 criteria.
        """
        skill = self._load_skill()
        if not skill:
            logger.debug(f"[{self.domain_id}] T2 skipped: no skill file loaded")
            return control_scores
        if not self.llm_client:
            logger.debug(f"[{self.domain_id}] T2 skipped: no LLM client")
            return control_scores

        context = self._build_llm_context(scan_results, analyzer_results)
        assessed = 0

        for score in control_scores:
            if score.t1_score == 0:
                logger.debug(f"  [{self.domain_id}] T2 skip {score.control_id}: t1=0")
                continue
            if score.t2_score > score.t2_floor:
                logger.debug(
                    f"  [{self.domain_id}] T2 skip {score.control_id}: "
                    f"t2={score.t2_score:.1f} > floor={score.t2_floor:.1f}"
                )
                continue

            control_def = self._get_control_def(score.control_id)
            if not control_def or not control_def.t2_criteria:
                logger.debug(
                    f"  [{self.domain_id}] T2 skip {score.control_id}: no t2_criteria"
                )
                continue
            assessed += 1

            criteria_text = "\n".join(f"  - {c}" for c in control_def.t2_criteria)
            evidence_text = "\n".join(
                f"  - [{ev.tier.value}] {ev.description}"
                for ev in score.evidence[:10]
            )

            prompt = (
                f"Evaluate the IMPLEMENTATION QUALITY of control "
                f"{score.control_id}: {control_def.name}\n\n"
                f"Description: {control_def.description}\n\n"
                f"T2 Implementation Criteria:\n{criteria_text}\n\n"
                f"Current evidence from code analysis:\n"
                f"{evidence_text or '  (no direct evidence)'}\n\n"
                f"T1 design score: {score.t1_score}/10 (the control IS designed in)\n\n"
                f"Based on the codebase evidence and context, score the "
                f"IMPLEMENTATION quality from 0-10:\n"
                f"  0 = No implementation found\n"
                f"  3 = Partial implementation, missing key criteria\n"
                f"  5 = Basic implementation present\n"
                f"  7 = Solid implementation meeting most criteria\n"
                f"  9 = Comprehensive implementation with all criteria met\n"
                f" 10 = Exemplary implementation exceeding requirements\n\n"
                f"Respond with ONLY a JSON object: "
                f'{{"t2_score": <number>, "rationale": "<brief explanation>"}}'
            )

            try:
                logger.info(
                    f"  [{self.domain_id}] T2 grading {score.control_id} "
                    f"(floor={score.t2_floor:.1f}, t1={score.t1_score:.1f})..."
                )
                response = await self.llm_client.complete(
                    system=skill,
                    user=f"Context:\n{context[:4000]}\n\n{prompt}",
                    metadata=make_trace_metadata(
                        domain_id=self.domain_id,
                        control_id=score.control_id,
                        tier="T2",
                        phase="implementation_grading",
                    ),
                )
                import json
                result = json.loads(response)
                new_t2 = float(result.get("t2_score", score.t2_floor))
                new_t2 = min(max(new_t2, 0.0), 10.0)
                score.t2_score = max(new_t2, score.t2_floor)
                usage = self.llm_client.get_token_usage()
                logger.info(
                    f"  [{self.domain_id}] T2 {score.control_id}: "
                    f"{score.t2_floor:.1f} -> {score.t2_score:.1f} "
                    f"(tokens: {usage['total_tokens']})"
                )
                if result.get("rationale"):
                    score.evidence.append(ControlEvidence(
                        tier=EvidenceTier.T2_IMPLEMENTATION,
                        source=EvidenceSource.LLM,
                        source_tool=f"llm:{self.domain_id}:t2",
                        description=result["rationale"],
                        confidence=0.7,
                    ))
            except Exception as e:
                logger.warning(
                    f"  [{self.domain_id}] T2 {score.control_id} LLM failed: {e}"
                )

        if assessed > 0:
            usage = self.llm_client.get_token_usage()
            logger.info(
                f"  [{self.domain_id}] T2 complete: {assessed} controls graded "
                f"(cumulative tokens: {usage['total_tokens']})"
            )
        else:
            logger.info(f"  [{self.domain_id}] T2: no eligible controls for LLM grading")
        return control_scores

    def _apply_red_team_scores(
        self,
        control_scores: list[ControlScore],
        red_team_reports: list[RedTeamReport],
    ) -> list[ControlScore]:
        """Apply T3 scores from red-team reports."""
        # Build lookup: control_id -> list of relevant scenarios
        for rt_report in red_team_reports:
            for scenario in rt_report.scenarios:
                if scenario.target_domain != self.domain_id:
                    continue
                for control_id in scenario.target_controls:
                    for score in control_scores:
                        if score.control_id == control_id:
                            score.t3_score = max(
                                score.t3_score,
                                scenario.t3_score_contribution,
                            )
                            score.evidence.extend(scenario.evidence)
                            break
        return control_scores

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _load_skill(self) -> Optional[str]:
        """Load the LLM skill markdown file for this domain."""
        if self._skill_content is not None:
            return self._skill_content

        if not self.skill_file:
            logger.warning(f"[{self.domain_id}] No skill_file configured — LLM scoring disabled")
            return None

        skill_path = Path(__file__).parent.parent / "skills" / self.skill_file
        try:
            if skill_path.is_file():
                self._skill_content = skill_path.read_text()
                logger.info(
                    f"[{self.domain_id}] Loaded skill: {self.skill_file} "
                    f"({len(self._skill_content)} chars)"
                )
                return self._skill_content
            else:
                logger.warning(
                    f"[{self.domain_id}] Skill file not found: {skill_path}"
                )
        except Exception as e:
            logger.error(f"[{self.domain_id}] Failed to load skill {skill_path}: {e}")

        return None

    def _get_control_def(self, control_id: str) -> Optional[ControlDefinition]:
        """Look up a control definition by ID."""
        if not self._controls:
            self._controls = self.define_controls()
        for c in self._controls:
            if c.control_id == control_id:
                return c
        return None

    def _build_llm_context(
        self,
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
    ) -> str:
        """Build a context string from scan/analyzer findings for LLM.

        Includes findings from required scanners first, then supplements
        with ALL available scan findings to ensure the LLM always has
        evidence to evaluate — even if the domain's primary scanner
        doesn't exist in the registry.
        """
        lines = [f"=== Domain: {self.domain_id} - {self.domain_name} ===\n"]
        included_scanners: set[str] = set()

        # Primary: include findings from this domain's required scanners
        for scanner_name in self.required_scanners():
            if scanner_name in scan_results:
                result = scan_results[scanner_name]
                lines.append(f"--- Scanner: {scanner_name} ({result.finding_count} findings) ---")
                for f in result.findings[:20]:
                    lines.append(f"  [{f.severity.value}] {f.category}: {f.message}")
                    if f.file_path:
                        lines.append(f"    File: {f.file_path}:{f.line_number or ''}")
                lines.append("")
                included_scanners.add(scanner_name)
            else:
                logger.debug(
                    f"[{self.domain_id}] Required scanner '{scanner_name}' "
                    f"not in scan_results — will supplement from other scanners"
                )

        # Supplemental: include findings from ALL other scanners to give
        # the LLM cross-domain evidence (capped per scanner to control tokens)
        supplemental_scanners = sorted(
            set(scan_results.keys()) - included_scanners
        )
        if supplemental_scanners:
            lines.append("--- Supplemental Evidence (other scanners) ---")
            for scanner_name in supplemental_scanners:
                result = scan_results[scanner_name]
                if result.finding_count == 0:
                    continue
                lines.append(f"  [{scanner_name}] ({result.finding_count} findings):")
                for f in result.findings[:10]:
                    lines.append(f"    [{f.severity.value}] {f.category}: {f.message}")
                    if f.file_path:
                        lines.append(f"      File: {f.file_path}:{f.line_number or ''}")
            lines.append("")

        for analyzer_name in self.required_analyzers():
            if analyzer_name in analyzer_results:
                result = analyzer_results[analyzer_name]
                lines.append(f"--- Analyzer: {analyzer_name} ({result.finding_count} findings) ---")
                for f in result.findings[:15]:
                    lines.append(f"  [{f.severity.value}] {f.category}: {f.message}")
                lines.append("")

        return "\n".join(lines)

    async def _generate_summary(self, control_scores: list[ControlScore]) -> str:
        """Generate an LLM narrative summary of domain findings."""
        if not self.llm_client:
            return ""

        scores_text = "\n".join(
            f"  {c.control_id} ({c.control_name}): T1={c.t1_score}, T2={c.t2_score}, T3={c.t3_score}"
            for c in control_scores
        )
        gaps_text = "\n".join(
            f"  {c.control_id}: {', '.join(c.gaps)}"
            for c in control_scores if c.gaps
        )

        try:
            response = await self.llm_client.complete(
                system="You are a security assessment report writer. Be concise and precise.",
                user=(
                    f"Write a 2-3 sentence summary of {self.domain_id} ({self.domain_name}) findings:\n"
                    f"Scores:\n{scores_text}\n"
                    f"Gaps:\n{gaps_text or '  None'}\n"
                    f"Respond with ONLY the summary text."
                ),
                metadata=make_trace_metadata(
                    domain_id=self.domain_id,
                    tier="summary",
                    phase="report_generation",
                ),
            )
            return response.strip()
        except Exception:
            return ""

    def _make_control_score(
        self,
        control_id: str,
        control_name: str,
        *,
        t1: float = 0,
        t2: float = 0,
        t3: float = 0,
        status: ControlStatus = ControlStatus.NOT_REVIEWED,
        evidence: Optional[list[ControlEvidence]] = None,
        gaps: Optional[list[str]] = None,
    ) -> ControlScore:
        """Helper to construct a ControlScore with floor enforcement."""
        return ControlScore(
            control_id=control_id,
            control_name=control_name,
            status=status,
            t1_score=t1,
            t2_score=t2,
            t3_score=t3,
            t1_floor=t1,
            t2_floor=t2,
            evidence=evidence or [],
            gaps=gaps or [],
        )
