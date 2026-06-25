"""CLI subcommands for token utilization aggregation.

Wired into the main ASOPB CLI as `asopb token-usage`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


@click.group("token-usage")
def token_usage_cli():
    """Token utilization aggregation and trend analysis."""
    pass


@token_usage_cli.command()
@click.option("--backend", "-b", default="langfuse", help="Backend name (langfuse, aws, azure, gcp)")
@click.option("--endpoint", "-e", default=None, help="Backend endpoint URL")
@click.option("--public-key", default=None, help="Public key (or set LANGFUSE_PUBLIC_KEY)")
@click.option("--secret-key", default=None, help="Secret key (or set LANGFUSE_SECRET_KEY)")
@click.option("--region", default=None, help="Cloud region (for aws/azure/gcp)")
@click.option("--project", default=None, help="Project ID (for gcp)")
@click.option("--from-date", default=None, help="Filter: start date (YYYY-MM-DD)")
@click.option("--to-date", default=None, help="Filter: end date (YYYY-MM-DD)")
@click.option("--model-filter", default=None, help="Filter: model name substring")
@click.option("--dast-threshold", default=15000, type=int, help="DAST fingerprint threshold (input tokens)")
@click.option("--cost-model", "-c", default="azure-o4-mini", help="Pricing model name")
@click.option("--format", "-f", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.option("--save/--no-save", default=True, help="Persist to SQLite for trend analysis")
@click.option("--output", "-o", type=click.Path(), default=None, help="Write report to file")
def aggregate(
    backend, endpoint, public_key, secret_key, region, project,
    from_date, to_date, model_filter, dast_threshold, cost_model,
    format, save, output,
):
    """Aggregate token usage from an observability backend."""
    from .aggregator import TokenUtilizationAggregator
    from .factory import BackendFactory
    from .models import AggregationFilters
    from .persistence import TokenUtilizationStore

    # Build config from CLI args + env vars
    config = {
        "endpoint": endpoint or os.environ.get("LANGFUSE_HOST", "http://langfuse-web:3000"),
        "public_key": public_key or os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        "secret_key": secret_key or os.environ.get("LANGFUSE_SECRET_KEY", ""),
        "region": region or os.environ.get("AWS_REGION_NAME", ""),
        "project": project or os.environ.get("GCP_PROJECT_ID", ""),
        "extra": {},
    }

    # AWS-specific (case-insensitive match)
    if backend.lower() == "aws":
        config["extra"]["log_group"] = os.environ.get("AWS_LOG_GROUP", "")

    # Azure-specific (case-insensitive match)
    if backend.lower() == "azure":
        config["extra"]["workspace_id"] = os.environ.get("AZURE_WORKSPACE_ID", "")

    try:
        be = BackendFactory.create(backend, config)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    filters = AggregationFilters(
        from_date=from_date,
        to_date=to_date,
        model=model_filter,
        dast_fingerprint_threshold=dast_threshold,
    )

    console.print(f"[cyan]Backend:[/cyan] {be.name}")
    console.print(f"[cyan]Fetching generations...[/cyan]")

    try:
        aggregator = TokenUtilizationAggregator(be)
        report = aggregator.aggregate(filters=filters, cost_model=cost_model)
    except Exception as e:
        console.print(f"[red]Aggregation failed: {e}[/red]")
        sys.exit(1)

    # Output
    if format == "json":
        result = report.to_json()
        if output:
            Path(output).write_text(result)
            console.print(f"[green]Report written to {output}[/green]")
        else:
            print(result)
    else:
        text = report.format_text()
        if output:
            Path(output).write_text(text)
            console.print(f"[green]Report written to {output}[/green]")
        else:
            print(text)

    # Persist
    if save:
        try:
            store = TokenUtilizationStore()
            run_id = store.save_report(report)
            console.print(f"[green]Saved to SQLite: {run_id}[/green]")
        except Exception as e:
            console.print(f"[yellow]Warning: failed to persist: {e}[/yellow]")


@token_usage_cli.command()
@click.option("--last", "-n", default=10, type=int, help="Number of recent runs to show")
def trends(last):
    """Show cost trends across recent aggregation runs."""
    from .persistence import TokenUtilizationStore

    store = TokenUtilizationStore()
    data = store.get_trends(last_n=last)

    if not data:
        console.print("[yellow]No historical runs found. Run 'aggregate' first.[/yellow]")
        return

    table = Table(title="Token Utilization Trends", box=box.ROUNDED)
    table.add_column("Date", style="cyan")
    table.add_column("Backend")
    table.add_column("DAST Probes", justify="right")
    table.add_column("Total Gens", justify="right")
    table.add_column("DAST Cost", justify="right", style="yellow")
    table.add_column("Regular Cost", justify="right")
    table.add_column("Total Cost", justify="right", style="bold")

    for row in data:
        table.add_row(
            row["generated_at"][:10],
            row["backend"],
            str(row["dast_probe_count"]),
            str(row["total_generations"]),
            f"${row['dast_total_cost']:.4f}",
            f"${row['regular_total_cost']:.4f}",
            f"${row['total_cost']:.4f}",
        )

    console.print(table)


@token_usage_cli.command()
@click.option("--limit", "-n", default=20, type=int, help="Number of runs to list")
def history(limit):
    """List recent aggregation runs."""
    from .persistence import TokenUtilizationStore

    store = TokenUtilizationStore()
    runs = store.list_runs(limit=limit)

    if not runs:
        console.print("[yellow]No runs found.[/yellow]")
        return

    table = Table(title="Aggregation History", box=box.ROUNDED)
    table.add_column("Run ID", style="cyan")
    table.add_column("Date")
    table.add_column("Backend")
    table.add_column("Generations", justify="right")
    table.add_column("DAST", justify="right")
    table.add_column("Cost", justify="right", style="bold")

    for r in runs:
        table.add_row(
            r["run_id"][:30],
            r["generated_at"][:16],
            r["backend"],
            str(r["total_generations"]),
            str(r["dast_probe_count"]),
            f"${r['total_cost']:.4f}",
        )

    console.print(table)


@token_usage_cli.command()
@click.argument("run_id")
@click.option("--format", "-f", type=click.Choice(["text", "json"]), default="text")
def show(run_id, format):
    """Show details of a specific aggregation run."""
    from .persistence import TokenUtilizationStore

    store = TokenUtilizationStore()
    data = store.get_run(run_id)

    if not data:
        console.print(f"[red]Run '{run_id}' not found.[/red]")
        sys.exit(1)

    if format == "json":
        report_data = data.get("report", data)
        print(json.dumps(report_data, indent=2))
    else:
        console.print(f"[bold]Run:[/bold] {data['run_id']}")
        console.print(f"[bold]Date:[/bold] {data['generated_at']}")
        console.print(f"[bold]Backend:[/bold] {data['backend']}")
        console.print(f"[bold]Cost Model:[/bold] {data['cost_model']}")
        console.print(f"[bold]Generations:[/bold] {data['total_generations']}")
        console.print(f"[bold]DAST Probes:[/bold] {data['dast_probe_count']}")
        console.print(f"[bold]Total Cost:[/bold] ${data['total_cost']:.4f}")


@token_usage_cli.command()
def backends():
    """List available observability backends."""
    from .factory import BackendFactory

    available = BackendFactory.list_backends()

    table = Table(title="Available Backends", box=box.ROUNDED)
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Required Config")

    descriptions = {
        "langfuse": ("Langfuse v2/v3", "endpoint, public_key, secret_key"),
        "aws": ("AWS CloudWatch + Bedrock", "region, extra[log_group]"),
        "azure": ("Azure Monitor + App Insights", "extra[workspace_id]"),
        "gcp": ("GCP Cloud Logging + Vertex AI", "project"),
    }

    for name in available:
        desc, config = descriptions.get(name, ("Custom backend", "varies"))
        table.add_row(name, desc, config)

    console.print(table)
