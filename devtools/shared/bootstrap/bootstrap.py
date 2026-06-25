#!/usr/bin/env python3
"""
ADEPT Bootstrap CLI - Team-agnostic development environment setup
Supports both local and remote execution via SSH/Fabric
"""

import os
import sys
import json
import yaml
from pathlib import Path
from typing import Optional, Dict, Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from fabric import Connection
from fabric.config import Config
from paramiko import SSHException
from invoke import UnexpectedExit

# Add the commands module to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from commands import setup, clone, remote, validate
from lib import env_manager, git_manager, ssh_executor

console = Console()

# Color scheme matching ADEPT's conventions
GREEN = "[green]"
YELLOW = "[yellow]"
RED = "[red]"
BLUE = "[blue]"
RESET = "[/]"


@click.group()
@click.option('--config', '-c', type=click.Path(exists=True),
              help='Path to team configuration file')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.pass_context
def cli(ctx, config, verbose):
    """
    ADEPT Bootstrap CLI - Team-agnostic development environment setup

    Supports multiple Git sources (GitHub, GitLab) and development teams.
    Can execute locally or remotely via SSH.
    """
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    ctx.obj['console'] = console

    if config:
        with open(config, 'r') as f:
            ctx.obj['config'] = yaml.safe_load(f)
    else:
        ctx.obj['config'] = {}

    # Display welcome banner
    if verbose:
        console.print(Panel.fit(
            "[bold blue]ADEPT Bootstrap CLI[/bold blue]\n"
            "Development Environment Setup Tool",
            border_style="blue"
        ))


@cli.command()
@click.option('--host', '-h', required=True, help='EC2 instance IP or hostname')
@click.option('--key', '-k', required=True, type=click.Path(exists=True),
              help='Path to SSH private key')
@click.option('--repo', '-r', required=True, help='Git repository URL')
@click.option('--token', '-t', help='Personal Access Token for Git')
@click.option('--branch', '-b', default='main', help='Git branch to clone')
@click.option('--folder', '-f', help='Clone folder name (default: repo name)')
@click.option('--python', '-p', default='3.11',
              type=click.Choice(['3.10', '3.11']),
              help='Python version for virtual environment')
@click.option('--use-conda', is_flag=True, help='Use conda instead of UV')
@click.option('--conda-env', default='adept', help='Conda environment name')
@click.option('--team', help='Team configuration name')
@click.pass_context
def init(ctx, host, key, repo, token, branch, folder, python, use_conda, conda_env, team):
    """
    Initialize development environment with Git repository and Python environment

    Examples:

        # GitHub with UV
        bootstrap init -h 10.0.0.1 -k ~/.ssh/key.pem -r https://github.com/pnnl/adept-agentic.git -t ghp_xxx

        # GitLab with Conda
        bootstrap init -h 10.0.0.1 -k ~/.ssh/key.pem -r https://gitlab.example.com/adept.git --use-conda
    """
    console.print(f"\n{BLUE}Initializing ADEPT development environment...{RESET}")

    # Load team config if specified
    team_config = {}
    if team and 'teams' in ctx.obj['config']:
        team_config = ctx.obj['config']['teams'].get(team, {})

    # Extract repo name if folder not specified
    if not folder:
        folder = Path(repo).stem.replace('.git', '')

    # Establish SSH connection
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task(f"Connecting to {host}...", total=None)

            conn = Connection(
                host=host,
                user='ubuntu',
                connect_kwargs={'key_filename': key},
                config=Config(overrides={'run': {'hide': not ctx.obj['verbose']}})
            )

            # Test connection
            conn.run('echo "Connection established"', hide=True)
            progress.update(task, description=f"{GREEN}✓ Connected to {host}{RESET}")

    except (SSHException, UnexpectedExit) as e:
        console.print(f"{RED}✗ Failed to connect: {e}{RESET}")
        sys.exit(1)

    # Create workspace directory
    workspace_dir = "/data/workspace"
    console.print(f"\n{BLUE}Setting up workspace...{RESET}")

    try:
        # Ensure workspace exists with proper permissions
        conn.run(f'sudo mkdir -p {workspace_dir}')
        conn.run(f'sudo chown ubuntu:ubuntu {workspace_dir}')
        conn.run(f'sudo chmod 777 {workspace_dir}')
        conn.run(f'sudo chmod g+s {workspace_dir}')

        # Clone repository
        clone_path = f"{workspace_dir}/{folder}"
        console.print(f"  Cloning repository to {clone_path}...")

        # Build clone command with authentication
        if token:
            # Extract domain and path from repo URL
            if 'github.com' in repo:
                auth_repo = repo.replace('https://', f'https://{token}@')
            elif 'gitlab' in repo.lower():
                auth_repo = repo.replace('https://', f'https://oauth2:{token}@')
            else:
                auth_repo = repo
        else:
            auth_repo = repo

        # Clone the repository
        result = conn.run(
            f'cd {workspace_dir} && git clone -b {branch} {auth_repo} {folder}',
            hide=True,
            warn=True
        )

        if result.failed:
            if 'already exists' in result.stderr:
                console.print(f"  {YELLOW}⚠ Repository already exists, pulling latest...{RESET}")
                conn.run(f'cd {clone_path} && git pull origin {branch}')
            else:
                raise UnexpectedExit(result)
        else:
            console.print(f"  {GREEN}✓ Repository cloned successfully{RESET}")

        # Set up Python environment
        if use_conda:
            console.print(f"\n{BLUE}Setting up Conda environment '{conda_env}'...{RESET}")

            # Create conda environment
            conn.run(
                f'/opt/miniconda3/bin/conda create -n {conda_env} python={python} -y',
                hide=not ctx.obj['verbose']
            )

            # Install UV in conda env for package management
            conn.run(
                f'/opt/miniconda3/bin/conda run -n {conda_env} pip install uv',
                hide=not ctx.obj['verbose']
            )

            # If uv.lock exists, sync dependencies
            check_uv = conn.run(f'test -f {clone_path}/uv.lock', warn=True)
            if check_uv.ok:
                console.print(f"  Installing dependencies from uv.lock...")
                conn.run(
                    f'cd {clone_path} && /opt/miniconda3/bin/conda run -n {conda_env} uv sync --all-extras',
                    hide=not ctx.obj['verbose']
                )

            console.print(f"  {GREEN}✓ Conda environment '{conda_env}' created{RESET}")
            console.print(f"  {BLUE}Activate with: conda activate {conda_env}{RESET}")

        else:
            console.print(f"\n{BLUE}Setting up UV virtual environment...{RESET}")

            # Check if UV is installed, install if missing
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
            ) as progress:
                task = progress.add_task("Checking UV installation...", total=None)

                uv_check = conn.run('test -f /home/ubuntu/.local/bin/uv', warn=True, hide=True)
                if not uv_check.ok:
                    progress.update(task, description="Installing UV package manager...")
                    conn.run('curl -LsSf https://astral.sh/uv/install.sh | sh', hide=not ctx.obj['verbose'])
                    progress.update(task, description=f"{GREEN}✓ UV installed{RESET}")
                else:
                    progress.update(task, description=f"{GREEN}✓ UV already installed{RESET}")

            # Create virtual environment with UV
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
            ) as progress:
                task = progress.add_task(f"Creating Python {python} virtual environment...", total=None)

                conn.run(
                    f'cd {clone_path} && /home/ubuntu/.local/bin/uv venv .venv --python {python}',
                    hide=not ctx.obj['verbose']
                )
                progress.update(task, description=f"{GREEN}✓ Virtual environment created{RESET}")

            # Sync dependencies if uv.lock exists
            check_uv = conn.run(f'test -f {clone_path}/uv.lock', warn=True)
            if check_uv.ok:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    transient=True,
                ) as progress:
                    task = progress.add_task("Syncing dependencies from uv.lock...", total=None)

                    conn.run(
                        f'cd {clone_path} && /home/ubuntu/.local/bin/uv sync --all-extras',
                        hide=not ctx.obj['verbose']
                    )
                    progress.update(task, description=f"{GREEN}✓ Dependencies synced{RESET}")

                    # Install in editable mode
                    task = progress.add_task("Installing package in editable mode...", total=None)
                    conn.run(
                        f'cd {clone_path} && .venv/bin/pip install -e .',
                        hide=not ctx.obj['verbose']
                    )
                    progress.update(task, description=f"{GREEN}✓ Package installed in editable mode{RESET}")

            console.print(f"  {GREEN}✓ Virtual environment created at {clone_path}/.venv{RESET}")
            console.print(f"  {BLUE}Activate with: source {clone_path}/.venv/bin/activate{RESET}")

        # Set up .env file if template exists
        check_env = conn.run(f'test -f {clone_path}/.env.example', warn=True)
        if check_env.ok:
            console.print(f"\n{BLUE}Setting up environment configuration...{RESET}")
            conn.run(f'cp {clone_path}/.env.example {clone_path}/.env')
            console.print(f"  {GREEN}✓ Created .env from template{RESET}")
            console.print(f"  {YELLOW}⚠ Remember to update .env with your credentials{RESET}")

        # Display summary
        console.print(f"\n{GREEN}✅ Environment initialization complete!{RESET}")

        # Create summary table
        table = Table(title="Environment Summary", show_header=True)
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Host", host)
        table.add_row("Repository", repo)
        table.add_row("Branch", branch)
        table.add_row("Clone Path", clone_path)
        table.add_row("Python Version", python)

        if use_conda:
            table.add_row("Environment Type", "Conda")
            table.add_row("Conda Env Name", conda_env)
        else:
            table.add_row("Environment Type", "UV Virtual Environment")
            table.add_row("Venv Path", f"{clone_path}/.venv")

        console.print(table)

        # Next steps
        console.print(f"\n{BLUE}Next steps:{RESET}")
        console.print(f"  1. SSH to instance: ssh -i {key} ubuntu@{host}")
        console.print(f"  2. Navigate to: cd {clone_path}")

        if use_conda:
            console.print(f"  3. Activate environment: conda activate {conda_env}")
        else:
            console.print(f"  3. Activate environment: source .venv/bin/activate")

        console.print(f"  4. Update .env file with your credentials")
        console.print(f"  5. Setup ADEPT volumes and data folders: make init-shared-volume-permissions")
        console.print(f"  6. Start ADEPT services: make start")

    except Exception as e:
        console.print(f"{RED}✗ Initialization failed: {e}{RESET}")
        sys.exit(1)
    finally:
        conn.close()


@cli.command()
@click.option('--host', '-h', required=True, help='EC2 instance IP or hostname')
@click.option('--key', '-k', required=True, type=click.Path(exists=True),
              help='Path to SSH private key')
@click.option('--check', '-c', multiple=True,
              type=click.Choice(['docker', 'python', 'services', 'network', 'env']),
              help='Specific checks to run')
@click.pass_context
def validate(ctx, host, key, check):
    """
    Validate the development environment setup

    Examples:

        # Run all validations
        bootstrap validate -h 10.0.0.1 -k ~/.ssh/key.pem

        # Run specific checks
        bootstrap validate -h 10.0.0.1 -k ~/.ssh/key.pem -c docker -c python
    """
    console.print(f"\n{BLUE}Validating ADEPT development environment...{RESET}")

    checks_to_run = check if check else ['docker', 'python', 'services', 'network', 'env']

    try:
        conn = Connection(
            host=host,
            user='ubuntu',
            connect_kwargs={'key_filename': key},
            config=Config(overrides={'run': {'hide': True}})
        )

        results = []

        # Docker check
        if 'docker' in checks_to_run:
            result = conn.run('docker --version', warn=True)
            if result.ok:
                version = result.stdout.strip()
                results.append(('Docker', f'✓ {version}', 'green'))
            else:
                results.append(('Docker', '✗ Not installed', 'red'))

        # Python check
        if 'python' in checks_to_run:
            for py_version in ['3.10', '3.11']:
                result = conn.run(f'python{py_version} --version', warn=True)
                if result.ok:
                    results.append((f'Python {py_version}', '✓ Installed', 'green'))
                else:
                    results.append((f'Python {py_version}', '✗ Not found', 'yellow'))

        # UV check
        result = conn.run('/home/ubuntu/.local/bin/uv --version', warn=True)
        if result.ok:
            results.append(('UV', f'✓ {result.stdout.strip()}', 'green'))
        else:
            results.append(('UV', '✗ Not installed', 'red'))

        # Conda check
        result = conn.run('/opt/miniconda3/bin/conda --version', warn=True)
        if result.ok:
            results.append(('Conda', f'✓ {result.stdout.strip()}', 'green'))
        else:
            results.append(('Conda', '✗ Not installed', 'yellow'))

        # ADEPT services check
        if 'services' in checks_to_run:
            result = conn.run('cd /data/workspace/*/  2>/dev/null && test -f Makefile', warn=True)
            if result.ok:
                results.append(('ADEPT Makefile', '✓ Found', 'green'))

                # Check if services are running
                result = conn.run('docker ps --format "{{.Names}}" | grep -E "(orchestration|gateway)" | wc -l', warn=True)
                if result.ok and int(result.stdout.strip()) > 0:
                    count = result.stdout.strip()
                    results.append(('ADEPT Services', f'✓ {count} running', 'green'))
                else:
                    results.append(('ADEPT Services', '⚠ Not running', 'yellow'))
            else:
                results.append(('ADEPT Repository', '✗ Not found', 'yellow'))

        # Display results
        table = Table(title="Validation Results", show_header=True)
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="white")

        for component, status, color in results:
            table.add_row(component, f"[{color}]{status}[/]")

        console.print(table)

        # Overall status
        errors = [r for r in results if 'red' in r[2]]
        warnings = [r for r in results if 'yellow' in r[2]]

        if errors:
            console.print(f"\n{RED}✗ Validation failed: {len(errors)} critical issues found{RESET}")
            sys.exit(1)
        elif warnings:
            console.print(f"\n{YELLOW}⚠ Validation passed with {len(warnings)} warnings{RESET}")
        else:
            console.print(f"\n{GREEN}✅ All validations passed!{RESET}")

    except Exception as e:
        console.print(f"{RED}✗ Validation failed: {e}{RESET}")
        sys.exit(1)
    finally:
        if 'conn' in locals():
            conn.close()


@cli.command()
@click.option('--host', '-h', required=True, help='EC2 instance IP or hostname')
@click.option('--key', '-k', required=True, type=click.Path(exists=True),
              help='Path to SSH private key')
@click.argument('command')
@click.pass_context
def remote(ctx, host, key, command):
    """
    Execute a command on the remote EC2 instance

    Examples:

        # Run make command
        bootstrap remote -h 10.0.0.1 -k ~/.ssh/key.pem "cd /data/workspace/adept && make start"

        # Check Docker status
        bootstrap remote -h 10.0.0.1 -k ~/.ssh/key.pem "docker ps"
    """
    console.print(f"\n{BLUE}Executing remote command...{RESET}")
    console.print(f"  Command: {command}")

    try:
        conn = Connection(
            host=host,
            user='ubuntu',
            connect_kwargs={'key_filename': key}
        )

        result = conn.run(command, hide=False)

        if result.ok:
            console.print(f"\n{GREEN}✓ Command executed successfully{RESET}")
        else:
            console.print(f"\n{RED}✗ Command failed with exit code {result.return_code}{RESET}")
            sys.exit(result.return_code)

    except Exception as e:
        console.print(f"{RED}✗ Remote execution failed: {e}{RESET}")
        sys.exit(1)
    finally:
        if 'conn' in locals():
            conn.close()


if __name__ == '__main__':
    cli()