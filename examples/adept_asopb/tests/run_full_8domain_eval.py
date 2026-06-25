"""
Full 8-Domain ASOPB Evaluation Runner

Runs the complete ASPI pipeline with all 8 domain evaluators and optional
promptfoo red-team T3 penalty integration. Outputs per-domain scores and
composite ASPI with stage classification.

Usage:
    python tests/run_full_8domain_eval.py [--promptfoo-dir DIR] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from asopb.config import EvalConfig, RedTeamConfig
from asopb.evaluator import ASPICalculator, Evaluator
from asopb.scoring import ASPICalculator as ScoringEngine


def discover_promptfoo_outputs(search_dir: Path) -> list[Path]:
    """Find all promptfoo output JSON files in a directory tree."""
    outputs = []
    for pattern in ("**/output.json", "**/*_output.json", "**/*_results.json"):
        outputs.extend(search_dir.glob(pattern))
    return sorted(set(outputs))


async def run_evaluation(
    promptfoo_paths: list[Path],
    output_json: bool = False,
) -> dict:
    config = EvalConfig(
        skip_llm=True,
        red_team=RedTeamConfig(promptfoo_output_paths=promptfoo_paths),
    )
    evaluator = Evaluator(config)

    rt_reports = evaluator._load_red_team_reports()
    domains = await evaluator._evaluate_all_domains({}, {}, rt_reports)

    aspi = ASPICalculator.calculate(domains)
    stage = ScoringEngine.stage_classification(domains)

    result = {
        "aspi": aspi,
        "stage": stage,
        "domains_evaluated": len(domains),
        "red_team_reports": len(rt_reports),
        "red_team_scenarios": sum(len(r.scenarios) for r in rt_reports),
        "domains": {},
    }

    for did, d in sorted(domains.items()):
        result["domains"][did] = {
            "name": d.domain_name,
            "score": d.domain_score,
            "t1_aggregate": round(d.t1_aggregate, 2),
            "t2_aggregate": round(d.t2_aggregate, 2),
            "t3_aggregate": round(d.t3_aggregate, 2),
            "controls": len(d.controls),
        }

    if output_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"ASPI: {aspi} (Stage: {stage})")
        print(f"Domains evaluated: {len(domains)}")
        if rt_reports:
            total_scenarios = sum(len(r.scenarios) for r in rt_reports)
            bypasses = sum(
                1
                for r in rt_reports
                for s in r.scenarios
                if "bypass" in s.outcome
            )
            print(f"Red-team: {len(rt_reports)} reports, {total_scenarios} scenarios, {bypasses} bypasses")
        print()
        for did, d in sorted(domains.items()):
            print(
                f"  {did} ({d.domain_name}): score={d.domain_score}, "
                f"T1={d.t1_aggregate:.1f}, T2={d.t2_aggregate:.1f}, T3={d.t3_aggregate:.1f}"
            )

    return result


def main():
    parser = argparse.ArgumentParser(description="Run full 8-domain ASOPB evaluation")
    parser.add_argument(
        "--promptfoo-dir",
        type=Path,
        default=None,
        help="Directory to search for promptfoo output JSON files",
    )
    parser.add_argument(
        "--promptfoo-file",
        type=Path,
        action="append",
        default=[],
        help="Explicit promptfoo output JSON file (can be repeated)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    pf_paths: list[Path] = list(args.promptfoo_file)
    if args.promptfoo_dir and args.promptfoo_dir.exists():
        pf_paths.extend(discover_promptfoo_outputs(args.promptfoo_dir))

    result = asyncio.run(run_evaluation(pf_paths, output_json=args.json))

    gate = 60.0
    if result["aspi"] < gate:
        sys.exit(1)


if __name__ == "__main__":
    main()
