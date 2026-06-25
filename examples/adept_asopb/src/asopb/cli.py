"""
ASOPB Command-Line Interface

Click-based CLI for running evaluations, scans, and analysis on repositories.
Supports multiple output formats, custom configurations, and detailed reporting.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from asopb.config import EvalConfig
from asopb.evaluator import Evaluator, FrameworkVersionDetector
from asopb.logging import get_logger
from asopb.models import EvaluationReport


logger = get_logger(__name__)
console = Console()


# ============================================================================
# Utilities
# ============================================================================

def load_config(config_path: Optional[str]) -> EvalConfig:
    """Load configuration from YAML or use defaults."""
    if config_path:
        try:
            return EvalConfig.from_yaml(Path(config_path))
        except Exception as e:
            console.print(f"[red]Error loading config: {e}[/red]")
            sys.exit(1)
    return EvalConfig()


def _run_async(coro):
    """Run async function in event loop."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coro)


# ============================================================================
# Commands
# ============================================================================

@click.group()
@click.version_option(version="1.0.0")
def cli():
    """ASOPB: Agentic Security & Operations Performance Benchmark."""
    pass


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
@click.option(
    "--config", "-c",
    type=click.Path(exists=True),
    help="Path to asopb.yaml configuration file."
)
@click.option(
    "--model", "-m",
    default=None,
    help="Override LLM model (e.g., 'gpt-4o', 'claude-sonnet-4')."
)
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Output directory for reports and evidence bundles."
)
@click.option(
    "--format", "-f",
    type=click.Choice(["json", "markdown", "html"]),
    default="json",
    help="Output format for evaluation report."
)
@click.option(
    "--domains", "-d",
    type=str,
    default=None,
    help="Comma-separated domain IDs to evaluate (e.g., 'D1,D3,D5')."
)
@click.option(
    "--skip-llm",
    is_flag=True,
    help="Skip LLM-assisted scoring (deterministic only)."
)
@click.option(
    "--skip-analyzers",
    is_flag=True,
    help="Skip external analyzers (scanners only)."
)
@click.option(
    "--disable-analyzers",
    type=str,
    default=None,
    help="Comma-separated analyzer names to skip (e.g., 'tls,bandit')."
)
@click.option(
    "--only-analyzers",
    type=str,
    default=None,
    help="Run ONLY these analyzers (whitelist, e.g., 'semgrep,pip_audit')."
)
@click.option(
    "--disable-scanners",
    type=str,
    default=None,
    help="Comma-separated scanner names to skip (e.g., 'codebase')."
)
@click.option(
    "--only-scanners",
    type=str,
    default=None,
    help="Run ONLY these scanners (whitelist, e.g., 'federation,itot,supply_chain')."
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable verbose logging."
)
@click.option(
    "--stage-hint",
    type=click.Choice(["S1", "S2", "S3", "S4"]),
    default=None,
    help="Stage hint for applicability determination."
)
@click.option(
    "--custom-controls",
    type=click.Path(exists=True),
    help="Path to custom controls YAML file."
)
@click.option(
    "--redteam-dir",
    type=click.Path(exists=True),
    help="Directory containing red-team JSON results (promptfoo output or RedTeamReport)."
)
@click.option(
    "--scoring-mode",
    type=click.Choice(["composite", "pipeline"]),
    default=None,
    help="Scoring formula: 'composite' (T1+T2+T3 average) or 'pipeline' (penalty-based, targets 90+)."
)
@click.option(
    "--profile",
    type=str,
    default=None,
    help="Scan profile name ('generic', 'adept') or path to custom profile YAML."
)
@click.option(
    "--token-budget",
    type=int,
    default=0,
    help="Max token budget for T2 LLM grading. If exceeded, prompts for confirmation (0=unlimited)."
)
@click.option(
    "--token-budget-confirm",
    is_flag=True,
    help="Auto-confirm token budget (skip prompt). Use in CI/non-interactive mode."
)
def evaluate(
    repo_path,
    config,
    model,
    output,
    format,
    domains,
    skip_llm,
    skip_analyzers,
    disable_analyzers,
    only_analyzers,
    disable_scanners,
    only_scanners,
    verbose,
    stage_hint,
    custom_controls,
    redteam_dir,
    scoring_mode,
    profile,
    token_budget,
    token_budget_confirm,
):
    """Run full ASOPB evaluation on a repository."""
    console.print("[bold blue]ASOPB Evaluation[/bold blue]")
    console.print(f"Repository: {repo_path}")

    try:
        # Load base config
        eval_config = load_config(config)

        # Apply overrides
        if model:
            eval_config.llm.model = model
        if output:
            eval_config.output_dir = Path(output)
        if skip_llm:
            eval_config.skip_llm = True
        if verbose:
            eval_config.verbose = True
        if stage_hint:
            eval_config.scoring.stage_hint = stage_hint
        if custom_controls:
            eval_config.scoring.custom_controls_path = Path(custom_controls)
        if skip_analyzers:
            eval_config.analyzers.disabled = eval_config.analyzers.enabled
        elif disable_analyzers:
            disabled = [a.strip() for a in disable_analyzers.split(",")]
            eval_config.analyzers.disabled.extend(disabled)
        elif only_analyzers:
            allowed = [a.strip() for a in only_analyzers.split(",")]
            eval_config.analyzers.enabled = allowed
            eval_config.analyzers.disabled = []

        if disable_scanners:
            disabled = [s.strip() for s in disable_scanners.split(",")]
            eval_config.scanners.disabled.extend(disabled)
        elif only_scanners:
            allowed = [s.strip() for s in only_scanners.split(",")]
            eval_config.scanners.enabled = allowed
            eval_config.scanners.disabled = []

        if redteam_dir:
            import re as _re
            from pathlib import Path as _P
            rt_dir = _P(redteam_dir)
            json_files = sorted(rt_dir.glob("*.json"))
            for f in json_files:
                header = f.read_text(errors="replace")[:2048]
                if _re.search(r'"evalId"\s*:', header) or _re.search(r'"results"\s*:\s*\[', header):
                    eval_config.red_team.promptfoo_output_paths.append(str(f))
                else:
                    eval_config.red_team.report_paths.append(str(f))

        if domains:
            domain_list = [d.strip() for d in domains.split(",")]
            eval_config.scoring.domains_to_evaluate = domain_list

        if scoring_mode:
            eval_config.scoring.scoring_mode = scoring_mode

        # Load scan profile and apply overrides
        scan_profile = None
        if profile:
            from asopb.profiles import get_profile_registry
            registry = get_profile_registry()
            profile_path = Path(profile)
            if profile_path.exists() and profile_path.suffix in (".yaml", ".yml"):
                scan_profile = registry.load_yaml(profile_path)
            else:
                scan_profile = registry.get(profile)
                if scan_profile is None:
                    available = ", ".join(registry.list_names())
                    console.print(
                        f"[red]Unknown profile '{profile}'. Available: {available}[/red]"
                    )
                    sys.exit(1)
            console.print(f"[cyan]Profile:[/cyan] {scan_profile.name} — {scan_profile.description}")
            # Apply profile overrides to eval_config
            if scan_profile.domain_weights:
                eval_config.scoring.domain_weights = scan_profile.domain_weights
            if scan_profile.enabled_scanners:
                eval_config.scanners.enabled = scan_profile.enabled_scanners
            if scan_profile.disabled_scanners:
                eval_config.scanners.disabled.extend(scan_profile.disabled_scanners)
            if scan_profile.enabled_analyzers:
                eval_config.analyzers.enabled = scan_profile.enabled_analyzers
            if scan_profile.disabled_analyzers:
                eval_config.analyzers.disabled.extend(scan_profile.disabled_analyzers)

        # Apply token budget from CLI
        if token_budget > 0:
            eval_config.token_budget = token_budget
        if token_budget_confirm:
            eval_config.token_budget_auto_confirm = True

        # Create output directory if specified
        if eval_config.output_dir:
            eval_config.output_dir.mkdir(parents=True, exist_ok=True)

        # Token budget gate: estimate and prompt before LLM calls
        evaluator = Evaluator(config=eval_config)
        if not eval_config.skip_llm:
            estimate = evaluator.estimate_t2_token_budget()
            budget_str = "unlimited" if estimate["budget_limit"] == 0 else f"{estimate['budget_limit']:,}"
            console.print(
                Panel(
                    f"Estimated T2 LLM calls: [bold]{estimate['estimated_calls']}[/bold]\n"
                    f"Estimated input tokens:  {estimate['estimated_input_tokens']:,}\n"
                    f"Estimated output tokens: {estimate['estimated_output_tokens']:,}\n"
                    f"Estimated total tokens:  [bold]{estimate['estimated_total_tokens']:,}[/bold]\n"
                    f"Token budget limit:      {budget_str}",
                    title="T2 Token Budget Estimate",
                    border_style="cyan",
                )
            )
            if estimate["exceeds_budget"]:
                console.print(
                    f"[yellow]Estimated tokens ({estimate['estimated_total_tokens']:,}) "
                    f"exceed budget ({estimate['budget_limit']:,}).[/yellow]"
                )
                if not eval_config.token_budget_auto_confirm:
                    choice = click.prompt(
                        "Proceed with full LLM analysis (f), enforce cap and skip excess (c), or abort (a)?",
                        type=click.Choice(["f", "c", "a"]),
                        default="a",
                    )
                    if choice == "a":
                        console.print("[red]Aborted by user.[/red]")
                        sys.exit(1)
                    elif choice == "c":
                        eval_config.skip_llm = True
                        console.print("[yellow]LLM scoring disabled (budget cap enforced).[/yellow]")
                else:
                    console.print("[yellow]Auto-confirmed: proceeding despite budget exceeded.[/yellow]")

        # Run evaluation
        console.print("[yellow]Running evaluation...[/yellow]")
        report = _run_async(evaluator.evaluate(repo_path))

        # Stamp profile and scoring mode into report metadata
        if scan_profile:
            report.profile = scan_profile.name
        report.scoring_mode = eval_config.scoring.scoring_mode

        # Apply pipeline scoring mode if requested
        pipeline_scores = None
        if eval_config.scoring.scoring_mode == "pipeline":
            from asopb.scoring import PipelineScorer
            pipeline_scores = PipelineScorer.score_report(report, profile=scan_profile)
            console.print(
                f"[bold cyan]Pipeline scoring:[/bold cyan] ASPI = {pipeline_scores['aspi']} "
                f"({pipeline_scores['stage']})"
            )

        # Display summary
        _display_report_summary(report)

        # Export report in requested format
        report_path = _export_report(report, eval_config.output_dir, format)
        if report_path:
            console.print(f"[green]✓[/green] Report exported to {report_path}")

        # Write pipeline scoring overlay if mode=pipeline
        if pipeline_scores and eval_config.output_dir:
            import json as _json
            pipeline_path = eval_config.output_dir / "report.json"
            # Merge pipeline ASPI into the main report JSON
            if report_path and report_path.exists():
                report_data = _json.loads(report_path.read_text())
            else:
                report_data = _json.loads(report.model_dump_json())
            report_data["aspi"] = pipeline_scores["aspi"]
            report_data["scoring_mode"] = "pipeline"
            report_data["pipeline_scores"] = pipeline_scores
            report_data["composite_aspi"] = report.aspi
            pipeline_path.write_text(_json.dumps(report_data, indent=2, default=str))
            console.print(f"[green]✓[/green] Pipeline-scored report: {pipeline_path}")

    except Exception as e:
        console.print(f"[red]✗ Evaluation failed: {e}[/red]")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Output directory for scan results."
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable verbose logging."
)
def scan(repo_path, output, verbose):
    """Quick scan with scanners only (no LLM, no analyzers)."""
    console.print("[bold blue]ASOPB Quick Scan[/bold blue]")
    console.print(f"Repository: {repo_path}")

    try:
        config = EvalConfig(verbose=verbose)
        if output:
            config.output_dir = Path(output)
            config.output_dir.mkdir(parents=True, exist_ok=True)

        console.print("[yellow]Running scanners...[/yellow]")
        evaluator = Evaluator(config=config)
        results = _run_async(evaluator.quick_scan(repo_path))

        # Display results
        _display_scan_results(results)

        # Export if output directory specified
        if config.output_dir:
            output_file = config.output_dir / "scan_results.json"
            data = {k: v.model_dump() for k, v in results.items()}
            output_file.write_text(json.dumps(data, indent=2, default=str))
            console.print(f"[green]✓[/green] Scan results saved to {output_file}")

    except Exception as e:
        console.print(f"[red]✗ Scan failed: {e}[/red]")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command()
def tools():
    """List available analyzers and their installation status."""
    console.print("[bold blue]Available Tools[/bold blue]\n")

    analyzers_info = {
        "gitxray": "Analyze git history for security patterns",
        "semgrep": "Static analysis for security rules (YAML-configurable)",
        "bandit": "Security linter for Python code",
        "pip_audit": "Audit pip dependencies for vulnerabilities",
        "dockerfile": "Lint and analyze Dockerfiles",
        "tls": "Analyze TLS/SSL configurations",
    }

    table = Table(title="Analyzers", box=box.ROUNDED)
    table.add_column("Analyzer", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Installed", style="green")

    for analyzer, description in analyzers_info.items():
        installed = _check_tool_installed(analyzer)
        status = "[green]✓[/green]" if installed else "[red]✗[/red]"
        table.add_row(analyzer, description, status)

    console.print(table)

    # Print install instructions
    console.print("\n[bold]Installation:[/bold]")
    console.print("pip install asopb[analyzers]  # Install all analyzers")
    console.print("pip install asopb[gitxray,semgrep,bandit]  # Install specific tools")


@cli.command()
@click.argument("report_a", type=click.Path(exists=True))
@click.argument("report_b", type=click.Path(exists=True))
@click.option(
    "--format", "-f",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format for comparison."
)
def compare(report_a, report_b, format):
    """Compare two evaluation reports and show delta."""
    console.print("[bold blue]Report Comparison[/bold blue]\n")

    try:
        # Load reports
        report_a_obj = _load_report(Path(report_a))
        report_b_obj = _load_report(Path(report_b))

        if not report_a_obj or not report_b_obj:
            raise ValueError("Failed to load one or both reports")

        # Calculate deltas
        delta = _calculate_report_delta(report_a_obj, report_b_obj)

        if format == "json":
            console.print_json(data=delta)
        else:
            _display_comparison(report_a_obj, report_b_obj, delta)

    except Exception as e:
        console.print(f"[red]✗ Comparison failed: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.argument("report_json", type=click.Path(exists=True))
def validate(report_json):
    """Validate report integrity and evidence store consistency."""
    console.print("[bold blue]Report Validation[/bold blue]\n")

    try:
        report = _load_report(Path(report_json))
        if not report:
            raise ValueError("Failed to load report")

        console.print(f"Report ID: {report.report_id}")
        console.print(f"Framework: {report.framework.name}")
        console.print(f"Timestamp: {report.timestamp}")

        # Validate structure
        errors = []
        warnings = []

        # Check domains
        if not report.domains:
            warnings.append("No domains evaluated")
        for domain_id, domain in report.domains.items():
            if not domain.controls:
                warnings.append(f"Domain {domain_id} has no controls")

        # Check evidence
        total_evidence = 0
        for domain in report.domains.values():
            for control in domain.controls:
                total_evidence += len(control.evidence)

        # Verify report hash
        expected_hash = report.report_hash
        console.print(f"\nReport hash: {expected_hash}")

        # Display results
        if errors:
            console.print("\n[red]Errors:[/red]")
            for error in errors:
                console.print(f"  - {error}")
        else:
            console.print("\n[green]✓ No structural errors found[/green]")

        if warnings:
            console.print("\n[yellow]Warnings:[/yellow]")
            for warning in warnings:
                console.print(f"  - {warning}")

        console.print(f"\n[cyan]Total evidence pieces: {total_evidence}[/cyan]")
        console.print(f"[cyan]ASPI: {report.aspi}[/cyan]")

    except Exception as e:
        console.print(f"[red]✗ Validation failed: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option(
    "--path", "-p",
    type=click.Path(),
    default="./asopb.yaml",
    help="Path where to create the config file."
)
def init(path):
    """Create a default asopb.yaml configuration file."""
    config_path = Path(path)

    if config_path.exists():
        if not click.confirm(f"{path} already exists. Overwrite?"):
            console.print("Aborted.")
            return

    default_config = """# ASOPB Configuration

llm:
  model: "claude-sonnet-4-20250514"
  temperature: 0.1
  max_tokens: 4096

analyzers:
  enabled:
    - gitxray
    - semgrep
    - bandit
    - pip_audit
    - dockerfile
    - tls
  timeout_seconds: 300

scoring:
  domain_weights:
    D1: 1.5  # Foundation Model Integrity
    D2: 1.0  # Orchestration Security
    D3: 1.0  # Tool and MCP Security
    D4: 1.0  # Identity and Authentication
    D5: 1.0  # Federation and Trust
    D6: 1.0  # Observability and Audit
    D7: 1.5  # IT/OT Convergence
    D8: 1.0  # Ecosystem and Supply Chain
  stage_hint: null  # "S1", "S2", "S3", or "S4"

evidence_store:
  enabled: true
  db_path: ./asopb_evidence.db

red_team:
  report_paths: []
  simulator_plugins: []

skip_llm: false
verbose: false
max_concurrency: 8
output_dir: ./asopb_output
"""

    try:
        config_path.write_text(default_config)
        console.print(f"[green]✓[/green] Created {path}")
        console.print("\nEdit this file to customize your evaluation configuration.")
    except Exception as e:
        console.print(f"[red]✗ Failed to create config: {e}[/red]")
        sys.exit(1)


# ============================================================================
# Helper functions
# ============================================================================

def _display_report_summary(report: EvaluationReport) -> None:
    """Display a summary of evaluation results."""
    console.print("\n[bold]Evaluation Results[/bold]\n")

    # ASPI score
    aspi_color = _get_score_color(report.aspi)
    console.print(f"[bold]ASPI: [{aspi_color}]{report.aspi}[/{aspi_color}][/bold]")

    # Per-domain scores
    console.print("\n[bold]Domain Scores:[/bold]")
    table = Table(box=box.ROUNDED)
    table.add_column("Domain", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("T1", justify="right")
    table.add_column("T2", justify="right")
    table.add_column("T3", justify="right")
    table.add_column("Status")

    for domain_id, domain in sorted(report.domains.items()):
        score_str = (
            f"[{_get_score_color(domain.domain_score)}]{domain.domain_score}[/]"
            if domain.domain_score is not None
            else "[yellow]N/A[/]"
        )
        table.add_row(
            domain_id,
            score_str,
            f"{domain.t1_aggregate:.1f}",
            f"{domain.t2_aggregate:.1f}",
            f"{domain.t3_aggregate:.1f}",
            "[green]✓[/green]" if domain.domain_score is not None else "[yellow]N/A[/yellow]",
        )

    console.print(table)

    # Metadata
    console.print(f"\n[cyan]Duration: {report.evaluation_duration_seconds:.1f}s[/cyan]")
    console.print(f"[cyan]LLM Calls: {report.llm_calls_made}[/cyan]")
    console.print(f"[cyan]Tokens: {report.llm_tokens_used}[/cyan]")

    if report.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for warning in report.warnings:
            console.print(f"  - {warning}")


def _display_scan_results(results: dict[str, any]) -> None:
    """Display scanner results."""
    console.print("\n[bold]Scan Results[/bold]\n")

    table = Table(box=box.ROUNDED)
    table.add_column("Scanner", style="cyan")
    table.add_column("Findings", justify="right")
    table.add_column("Status")

    for scanner_name, result in sorted(results.items()):
        status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
        table.add_row(scanner_name, str(result.finding_count), status)

    console.print(table)


def _display_comparison(report_a, report_b, delta) -> None:
    """Display comparison between two reports."""
    console.print(f"Report A: {report_a.report_id}")
    console.print(f"Report B: {report_b.report_id}\n")

    # ASPI delta
    aspi_delta = report_b.aspi - report_a.aspi
    delta_color = "green" if aspi_delta >= 0 else "red"
    delta_str = f"{aspi_delta:+.1f}"
    console.print(f"ASPI: {report_a.aspi} → {report_b.aspi} [{delta_color}]{delta_str}[/{delta_color}]")

    # Per-domain deltas
    console.print("\n[bold]Domain Deltas:[/bold]")
    table = Table(box=box.ROUNDED)
    table.add_column("Domain", style="cyan")
    table.add_column("Before")
    table.add_column("After")
    table.add_column("Delta")

    for domain_id in sorted(set(report_a.domains.keys()) | set(report_b.domains.keys())):
        score_a = report_a.domains.get(domain_id).domain_score if domain_id in report_a.domains else 0
        score_b = report_b.domains.get(domain_id).domain_score if domain_id in report_b.domains else 0
        domain_delta = score_b - score_a if score_a and score_b else 0

        delta_color = "green" if domain_delta >= 0 else "red"
        delta_str = f"{domain_delta:+.1f}" if domain_delta else "—"
        table.add_row(
            domain_id,
            f"{score_a:.1f}" if score_a else "—",
            f"{score_b:.1f}" if score_b else "—",
            f"[{delta_color}]{delta_str}[/{delta_color}]",
        )

    console.print(table)


def _export_report(
    report: EvaluationReport,
    output_dir: Optional[Path],
    format: str,
) -> Optional[Path]:
    """Export report in specified format."""
    if not output_dir:
        return None

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if format == "json":
        path = output_dir / f"{report.report_id}.json"
        path.write_text(report.model_dump_json(indent=2))
        return path

    elif format == "markdown":
        path = output_dir / f"{report.report_id}.md"
        md_content = _generate_markdown_report(report)
        path.write_text(md_content)
        return path

    elif format == "html":
        path = output_dir / f"{report.report_id}.html"
        html_content = _generate_html_report(report)
        path.write_text(html_content)
        return path

    return None


def _generate_markdown_report(report: EvaluationReport) -> str:
    """Generate markdown version of report."""
    md = f"""# ASOPB Evaluation Report

**Report ID:** {report.report_id}
**Framework:** {report.framework.name}
**Timestamp:** {report.timestamp}
**ASPI:** {report.aspi}

## Summary

- Evaluation Duration: {report.evaluation_duration_seconds:.1f}s
- LLM Calls: {report.llm_calls_made}
- Tokens Used: {report.llm_tokens_used}

## Domain Scores

| Domain | Score | T1 | T2 | T3 |
|--------|-------|----|----|-----|
"""
    for domain_id, domain in sorted(report.domains.items()):
        md += f"| {domain_id} | {domain.domain_score or 'N/A'} | {domain.t1_aggregate:.1f} | {domain.t2_aggregate:.1f} | {domain.t3_aggregate:.1f} |\n"

    return md


def _generate_html_report(report: EvaluationReport) -> str:
    """Generate HTML version of report."""
    html = f"""<html>
<head>
  <title>ASOPB Report: {report.report_id}</title>
  <style>
    body {{ font-family: sans-serif; margin: 20px; }}
    h1 {{ color: #333; }}
    table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
    th {{ background-color: #f2f2f2; }}
  </style>
</head>
<body>
  <h1>ASOPB Evaluation Report</h1>
  <p><strong>Report ID:</strong> {report.report_id}</p>
  <p><strong>Framework:</strong> {report.framework.name}</p>
  <p><strong>ASPI:</strong> {report.aspi}</p>
  <h2>Domain Scores</h2>
  <table>
    <tr><th>Domain</th><th>Score</th><th>T1</th><th>T2</th><th>T3</th></tr>
"""
    for domain_id, domain in sorted(report.domains.items()):
        html += f"    <tr><td>{domain_id}</td><td>{domain.domain_score or 'N/A'}</td><td>{domain.t1_aggregate:.1f}</td><td>{domain.t2_aggregate:.1f}</td><td>{domain.t3_aggregate:.1f}</td></tr>\n"

    html += """  </table>
</body>
</html>
"""
    return html


def _load_report(path: Path) -> Optional[EvaluationReport]:
    """Load report from JSON file."""
    try:
        data = json.loads(path.read_text())
        return EvaluationReport(**data)
    except Exception as e:
        logger.error(f"Failed to load report {path}: {e}")
        return None


def _calculate_report_delta(report_a: EvaluationReport, report_b: EvaluationReport) -> dict:
    """Calculate differences between two reports."""
    return {
        "aspi_delta": report_b.aspi - report_a.aspi,
        "domain_deltas": {
            domain_id: {
                "before": report_a.domains.get(domain_id).domain_score,
                "after": report_b.domains.get(domain_id).domain_score,
            }
            for domain_id in sorted(set(report_a.domains.keys()) | set(report_b.domains.keys()))
        },
    }


def _check_tool_installed(tool_name: str) -> bool:
    """Check if an external tool is installed."""
    import shutil

    # Map tool names to executables
    executables = {
        "gitxray": "git",
        "semgrep": "semgrep",
        "bandit": "bandit",
        "pip_audit": "pip-audit",
        "dockerfile": "hadolint",
        "tls": "openssl",
    }

    exe = executables.get(tool_name)
    if not exe:
        return False

    return shutil.which(exe) is not None


def _get_score_color(score: Optional[float]) -> str:
    """Get color for score display."""
    if score is None:
        return "yellow"
    if score >= 80:
        return "green"
    if score >= 60:
        return "yellow"
    return "red"


from asopb.observability.cli import token_usage_cli

cli.add_command(token_usage_cli)


if __name__ == "__main__":
    cli()
