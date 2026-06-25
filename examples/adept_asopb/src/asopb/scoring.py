"""
ASOPB Scoring Engine

Implements the Agentic Security Posture Index (ASPI) calculation per Section 5.4,
domain profiling, T1/T2/T3 gap analysis, stage classification, and report comparison.

Supports two scoring modes:
- composite: ASPI = weighted_mean(domain_scores) where domain_score = avg(control_composites)
- pipeline: ASPI = max(0, 100 - SUM(weight * ln(1 + count))) per domain, penalty-based
"""

from __future__ import annotations

import math
from typing import Any

from asopb.models import (
    Applicability,
    DomainResult,
    EvaluationReport,
    Severity,
)


class ASPICalculator:
    """Scoring engine for the ASOPB framework.

    Calculates ASPI (Agentic Security Posture Index) as a weighted mean per
    Section 5.4, derives domain profiles, infers deployment stages, and
    compares evaluations for delta analysis.
    """

    @staticmethod
    def calculate_aspi(domains: dict[str, DomainResult]) -> float:
        """Calculate ASPI as a weighted mean per Section 5.4.

        ASPI = Σ(weight × domain_score) / Σ(weight)

        Applicable domains only (NOT_APPLICABLE excluded from both numerator
        and denominator).

        Args:
            domains: Mapping of domain_id to DomainResult

        Returns:
            ASPI score on 0–100 scale
        """
        numerator = 0.0
        denominator = 0.0

        for d in domains.values():
            if d.applicability == Applicability.NOT_APPLICABLE:
                continue
            score = d.domain_score
            if score is None:
                continue
            numerator += d.weight * score
            denominator += d.weight

        if denominator == 0:
            return 0.0
        return round(numerator / denominator, 1)

    @staticmethod
    def t1_t2_gap_ratio(domains: dict[str, DomainResult]) -> float:
        """Calculate T1/T2 gap ratio.

        Fraction of controls with T1 > 0 but T2 = 0.
        High ratio indicates design claims without deployment evidence.

        Args:
            domains: Mapping of domain_id to DomainResult

        Returns:
            Ratio on 0–1 scale
        """
        t1_positive = 0
        t1_only = 0

        for d in domains.values():
            if d.applicability == Applicability.NOT_APPLICABLE:
                continue
            for c in d.controls:
                if c.t1_score > 0:
                    t1_positive += 1
                    if c.t2_score == 0:
                        t1_only += 1

        if t1_positive == 0:
            return 0.0
        return round(t1_only / t1_positive, 3)

    @staticmethod
    def domain_profile(
        domains: dict[str, DomainResult],
    ) -> dict[str, dict[str, Any]]:
        """Generate per-domain T1/T2/T3 breakdown.

        Args:
            domains: Mapping of domain_id to DomainResult

        Returns:
            Dict mapping domain_id to:
                {
                    "name": str,
                    "applicability": str,
                    "weight": float,
                    "domain_score": float | None,
                    "t1_aggregate": float,
                    "t2_aggregate": float,
                    "t3_aggregate": float,
                    "control_count": int,
                    "controls_not_reviewed": int,
                    "controls_partial": int,
                    "controls_not_applicable": int,
                }
        """
        profile = {}

        for domain_id, d in domains.items():
            not_reviewed = sum(
                1
                for c in d.controls
                if c.status.value == "not_reviewed"
            )
            partial = sum(
                1 for c in d.controls if c.status.value == "partial"
            )
            not_applicable = sum(
                1
                for c in d.controls
                if c.status.value == "not_applicable"
            )

            profile[domain_id] = {
                "name": d.domain_name,
                "applicability": d.applicability.value,
                "weight": d.weight,
                "domain_score": d.domain_score,
                "t1_aggregate": d.t1_aggregate,
                "t2_aggregate": d.t2_aggregate,
                "t3_aggregate": d.t3_aggregate,
                "control_count": len(d.controls),
                "controls_not_reviewed": not_reviewed,
                "controls_partial": partial,
                "controls_not_applicable": not_applicable,
            }

        return profile

    @staticmethod
    def stage_classification(domains: dict[str, DomainResult]) -> str:
        """Infer deployment stage (S1/S2/S3/S4) based on score patterns.

        Classification heuristic:
        - S1: ASPI < 30, most controls not_reviewed, T1 dominant
        - S2: ASPI 30–60, mixed T1/T2, few T3
        - S3: ASPI 60–85, strong T2/T3, most controls implemented
        - S4: ASPI >= 85, all tiers high, adversarial validation present

        Args:
            domains: Mapping of domain_id to DomainResult

        Returns:
            "S1", "S2", "S3", or "S4"
        """
        aspi = ASPICalculator.calculate_aspi(domains)

        # Count control statuses across all applicable domains
        not_reviewed = 0
        partial = 0
        not_a_finding = 0
        open_controls = 0

        for d in domains.values():
            if d.applicability == Applicability.NOT_APPLICABLE:
                continue
            for c in d.controls:
                if c.status.value == "not_reviewed":
                    not_reviewed += 1
                elif c.status.value == "partial":
                    partial += 1
                elif c.status.value == "not_a_finding":
                    not_a_finding += 1
                elif c.status.value == "open":
                    open_controls += 1

        total_controls = not_reviewed + partial + not_a_finding + open_controls

        if total_controls == 0:
            # No controls, default to S1
            return "S1"

        reviewed_fraction = (partial + not_a_finding) / total_controls
        implemented_fraction = not_a_finding / total_controls

        # Stage logic
        if aspi >= 85 and implemented_fraction >= 0.85:
            return "S4"
        elif aspi >= 60 and reviewed_fraction >= 0.60:
            return "S3"
        elif aspi >= 30 and reviewed_fraction >= 0.20:
            return "S2"
        else:
            return "S1"

    @staticmethod
    def compare_reports(
        report_a: EvaluationReport, report_b: EvaluationReport
    ) -> dict[str, Any]:
        """Delta analysis between two evaluations.

        Compares ASPI, T1/T2/T3 aggregates, control-by-control deltas,
        and severity distributions.

        Args:
            report_a: First evaluation report
            report_b: Second evaluation report

        Returns:
            Dict with:
                {
                    "aspi_delta": float,
                    "t1_t2_gap_delta": float,
                    "stage_a": str,
                    "stage_b": str,
                    "domain_deltas": {
                        domain_id: {
                            "score_delta": float,
                            "t1_delta": float,
                            "t2_delta": float,
                            "t3_delta": float,
                        }
                    },
                    "control_deltas": {
                        control_id: {
                            "composite_delta": float,
                            "t1_delta": float,
                            "t2_delta": float,
                            "t3_delta": float,
                            "status_a": str,
                            "status_b": str,
                        }
                    },
                    "severity_distribution_a": dict,
                    "severity_distribution_b": dict,
                }
        """
        aspi_a = report_a.aspi
        aspi_b = report_b.aspi
        gap_a = report_a.t1_t2_gap_ratio
        gap_b = report_b.t1_t2_gap_ratio

        stage_a = ASPICalculator.stage_classification(report_a.domains)
        stage_b = ASPICalculator.stage_classification(report_b.domains)

        domain_deltas = {}
        for domain_id in set(report_a.domains.keys()) | set(
            report_b.domains.keys()
        ):
            d_a = report_a.domains.get(domain_id)
            d_b = report_b.domains.get(domain_id)

            score_a = d_a.domain_score if d_a else 0.0
            score_b = d_b.domain_score if d_b else 0.0
            t1_a = d_a.t1_aggregate if d_a else 0.0
            t1_b = d_b.t1_aggregate if d_b else 0.0
            t2_a = d_a.t2_aggregate if d_a else 0.0
            t2_b = d_b.t2_aggregate if d_b else 0.0
            t3_a = d_a.t3_aggregate if d_a else 0.0
            t3_b = d_b.t3_aggregate if d_b else 0.0

            domain_deltas[domain_id] = {
                "score_delta": round(score_b - score_a, 1),
                "t1_delta": round(t1_b - t1_a, 2),
                "t2_delta": round(t2_b - t2_a, 2),
                "t3_delta": round(t3_b - t3_a, 2),
            }

        # Control-by-control deltas
        control_deltas = {}
        for domain_id in report_a.domains.keys():
            if domain_id not in report_b.domains:
                continue
            for ctrl_a in report_a.domains[domain_id].controls:
                # Find matching control in report_b
                ctrl_b = None
                for cb in report_b.domains[domain_id].controls:
                    if cb.control_id == ctrl_a.control_id:
                        ctrl_b = cb
                        break

                if ctrl_b:
                    control_id = ctrl_a.control_id
                    control_deltas[control_id] = {
                        "composite_delta": round(
                            ctrl_b.composite - ctrl_a.composite, 1
                        ),
                        "t1_delta": round(ctrl_b.t1_score - ctrl_a.t1_score, 2),
                        "t2_delta": round(ctrl_b.t2_score - ctrl_a.t2_score, 2),
                        "t3_delta": round(ctrl_b.t3_score - ctrl_a.t3_score, 2),
                        "status_a": ctrl_a.status.value,
                        "status_b": ctrl_b.status.value,
                    }

        # Severity distribution
        def _severity_dist(
            report: EvaluationReport,
        ) -> dict[str, int]:
            dist = {s.value: 0 for s in Severity}
            for d in report.domains.values():
                for c in d.controls:
                    for ev in c.evidence:
                        dist[ev.source_tool.split(":")[0]] = (
                            dist.get(ev.source_tool.split(":")[0], 0) + 1
                        )
            return dist

        return {
            "aspi_delta": round(aspi_b - aspi_a, 1),
            "t1_t2_gap_delta": round(gap_b - gap_a, 3),
            "stage_a": stage_a,
            "stage_b": stage_b,
            "domain_deltas": domain_deltas,
            "control_deltas": control_deltas,
            "severity_distribution_a": _severity_dist(report_a),
            "severity_distribution_b": _severity_dist(report_b),
        }


class PipelineScorer:
    """Pipeline-equivalent scoring using logarithmic penalty model.

    Matches the scan_pipeline.py ASPOBScore formula:
        domain_score = max(0, 100 - SUM(weight * ln(1 + count)))
        ASPI = D5 * 0.4 + D8 * 0.4 + D7 * 0.2

    For non-pipeline domains (D1-D4, D6), applies a generic penalty model
    based on negative findings (open/partial controls).
    """

    PIPELINE_WEIGHTS = {"D5": 0.4, "D8": 0.4, "D7": 0.2}

    PENALTY_WEIGHTS = {
        "D5": {
            "critical": 40.0,
            "high": 15.0,
            "medium": 8.0,
            "low": 1.5,
        },
        "D7": {
            "critical": 40.0,
            "high": 15.0,
            "medium": 8.0,
            "low": 1.5,
        },
        "D8": {
            "critical": 40.0,
            "high": 15.0,
            "medium": 2.5,
            "low": 0.5,
        },
    }

    GENERIC_PENALTY = {
        "critical": 30.0,
        "high": 12.0,
        "medium": 5.0,
        "low": 1.0,
    }

    @staticmethod
    def _log_penalty(count: int, weight: float) -> float:
        if count == 0:
            return 0.0
        return weight * math.log(1 + count)

    DOMAIN_SCANNER_MAP = {
        "D5": ["federation", "codebase"],
        "D7": ["itot", "codebase"],
        "D8": ["supply_chain", "codebase"],
        "D1": ["supply_chain", "codebase"],
        "D2": ["sandbox", "codebase"],
        "D3": ["tools", "codebase"],
        "D4": ["auth", "codebase"],
        "D6": ["observability", "codebase"],
    }

    @classmethod
    def score_domain(
        cls,
        domain: DomainResult,
        scan_results: dict | None = None,
        profile=None,
    ) -> float:
        """Score a single domain using the penalty model.

        Counts negative findings from scan_results (ScanFinding with severity)
        or falls back to counting controls with OPEN/PARTIALLY_IMPLEMENTED status.

        If a profile is provided, uses its penalty_weights and domain_scanner_map
        instead of the class-level defaults.
        """
        domain_id = domain.domain_id

        if profile and domain_id in profile.penalty_weights:
            weights = profile.penalty_weights[domain_id]
        elif profile:
            weights = profile.generic_penalty
        else:
            weights = cls.PENALTY_WEIGHTS.get(domain_id, cls.GENERIC_PENALTY)

        if profile and profile.domain_scanner_map:
            scanner_map = profile.domain_scanner_map
        else:
            scanner_map = cls.DOMAIN_SCANNER_MAP

        critical_count = 0
        high_count = 0
        medium_count = 0
        low_count = 0

        if scan_results:
            relevant_scanners = scanner_map.get(domain_id, [])
            for scanner_name, result in scan_results.items():
                if relevant_scanners and scanner_name not in relevant_scanners:
                    continue
                for finding in result.findings:
                    sev = finding.severity.value if hasattr(finding.severity, "value") else str(finding.severity)
                    if sev == "critical":
                        critical_count += 1
                    elif sev == "high":
                        high_count += 1
                    elif sev == "medium":
                        medium_count += 1
                    elif sev in ("low", "informational"):
                        low_count += 1
        else:
            for ctrl in domain.controls:
                if ctrl.status.value == "open":
                    high_count += 1
                elif ctrl.status.value == "partial":
                    medium_count += 1

        penalty = (
            cls._log_penalty(critical_count, weights["critical"])
            + cls._log_penalty(high_count, weights["high"])
            + cls._log_penalty(medium_count, weights["medium"])
            + cls._log_penalty(low_count, weights["low"])
        )
        return max(0.0, round(100.0 - penalty, 1))

    @classmethod
    def calculate_aspi(
        cls,
        domains: dict[str, DomainResult],
        scan_results: dict | None = None,
        profile=None,
    ) -> float:
        """Calculate ASPI using the pipeline penalty model.

        For D5/D7/D8: uses fixed weights (0.4/0.2/0.4) unless overridden by profile.
        For other domains: includes them with equal weight in the remainder.
        """
        pw = profile.pipeline_weights if profile and profile.pipeline_weights else cls.PIPELINE_WEIGHTS
        pipeline_domains = set(pw.keys())
        applicable = {
            k: v for k, v in domains.items()
            if v.applicability != Applicability.NOT_APPLICABLE
        }

        if not applicable:
            return 0.0

        present_pipeline = set(applicable.keys()) & pipeline_domains
        present_other = set(applicable.keys()) - pipeline_domains

        if present_pipeline and not present_other:
            total_weight = sum(
                pw.get(d, 0.2) for d in present_pipeline
            )
            numerator = sum(
                pw.get(d, 0.2) * cls.score_domain(applicable[d], scan_results, profile=profile)
                for d in present_pipeline
            )
            return round(numerator / total_weight, 1) if total_weight > 0 else 0.0

        # Mixed: pipeline domains get their weights, others get 1.0
        numerator = 0.0
        denominator = 0.0
        for domain_id, domain in applicable.items():
            score = cls.score_domain(domain, scan_results, profile=profile)
            weight = pw.get(domain_id, 1.0)
            numerator += weight * score
            denominator += weight

        return round(numerator / denominator, 1) if denominator > 0 else 0.0

    @classmethod
    def score_report(cls, report: EvaluationReport, profile=None) -> dict[str, Any]:
        """Score an entire report using pipeline mode.

        Args:
            report: The evaluation report to score.
            profile: Optional ScanProfile with custom penalty/pipeline weights.

        Returns dict with pipeline ASPI and per-domain scores.
        """
        scan_results = report.scan_results if hasattr(report, "scan_results") else None
        domain_scores = {}
        for domain_id, domain in report.domains.items():
            if domain.applicability == Applicability.NOT_APPLICABLE:
                continue
            domain_scores[domain_id] = cls.score_domain(domain, scan_results, profile=profile)

        aspi = cls.calculate_aspi(report.domains, scan_results, profile=profile)

        profile_name = profile.name if profile else "default"
        return {
            "scoring_mode": "pipeline",
            "profile": profile_name,
            "aspi": aspi,
            "stage": _pipeline_stage(aspi),
            "domain_scores": domain_scores,
            "formula": "max(0, 100 - SUM(weight * ln(1 + count)))",
        }


def _pipeline_stage(aspi: float) -> str:
    if aspi >= 90:
        return "S4 (Hardened)"
    elif aspi >= 70:
        return "S3 (Monitored)"
    elif aspi >= 50:
        return "S2 (Managed)"
    else:
        return "S1 (Minimal)"
