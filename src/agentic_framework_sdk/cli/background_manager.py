#!/usr/bin/env python3
"""
Background Process Manager for Agentic Framework CLI

Provides Claude CLI-style background process support with:
- Concurrent long-running agent invocations
- Process status monitoring and control
- Background/foreground switching
- Process output streaming and management
"""

import asyncio
import json
import signal
import sys
import time
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, AsyncGenerator, Any, Callable
from dataclasses import dataclass, asdict
import threading
from concurrent.futures import ThreadPoolExecutor

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.live import Live
from rich.text import Text

console = Console()

class ProcessStatus(Enum):
    """Background process status states."""
    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"

@dataclass
class BackgroundProcess:
    """Represents a background process."""
    id: str
    name: str
    command: str
    status: ProcessStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    output_lines: List[str] = None
    error_lines: List[str] = None
    session_id: Optional[str] = None
    model: Optional[str] = None
    exit_code: Optional[int] = None
    
    def __post_init__(self):
        if self.output_lines is None:
            self.output_lines = []
        if self.error_lines is None:
            self.error_lines = []
    
    @property
    def duration(self) -> Optional[float]:
        """Calculate process duration."""
        if not self.started_at:
            return None
        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds()
    
    @property
    def is_active(self) -> bool:
        """Check if process is actively running."""
        return self.status in [ProcessStatus.STARTING, ProcessStatus.RUNNING, ProcessStatus.PAUSED]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        # Convert datetime objects to ISO strings
        for key in ['created_at', 'started_at', 'completed_at']:
            if data[key]:
                data[key] = data[key].isoformat()
        data['status'] = self.status.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BackgroundProcess':
        """Create from dictionary."""
        # Convert ISO strings back to datetime objects
        for key in ['created_at', 'started_at', 'completed_at']:
            if data[key]:
                data[key] = datetime.fromisoformat(data[key])
        data['status'] = ProcessStatus(data['status'])
        return cls(**data)

class BackgroundManager:
    """Manages background processes for the CLI."""
    
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.processes_file = config_dir / "background_processes.json"
        self.processes: Dict[str, BackgroundProcess] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.executor = ThreadPoolExecutor(max_workers=5)  # Limit concurrent processes
        
        # Load existing processes
        self._load_processes()
    
    def _load_processes(self):
        """Load processes from disk."""
        if not self.processes_file.exists():
            return
        
        try:
            with open(self.processes_file, 'r') as f:
                data = json.load(f)
            
            for proc_data in data.get('processes', []):
                process = BackgroundProcess.from_dict(proc_data)
                self.processes[process.id] = process
                
                # Mark as failed if it was running when CLI exited
                if process.is_active:
                    process.status = ProcessStatus.FAILED
                    process.completed_at = datetime.now()
                    process.error_lines.append("Process interrupted by CLI restart")
            
            console.print(f"[dim]Loaded {len(self.processes)} background processes[/dim]")
            
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to load background processes: {e}[/yellow]")
    
    def _save_processes(self):
        """Save processes to disk."""
        try:
            data = {
                'processes': [proc.to_dict() for proc in self.processes.values()],
                'last_saved': datetime.now().isoformat()
            }
            
            with open(self.processes_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
                
        except Exception as e:
            console.print(f"[red]Failed to save background processes: {e}[/red]")
    
    def create_process(
        self, 
        command: str, 
        name: Optional[str] = None,
        session_id: Optional[str] = None,
        model: Optional[str] = None
    ) -> str:
        """Create a new background process."""
        process_id = str(uuid.uuid4())[:8]
        process_name = name or f"agent-{process_id}"
        
        process = BackgroundProcess(
            id=process_id,
            name=process_name,
            command=command,
            status=ProcessStatus.STARTING,
            created_at=datetime.now(),
            session_id=session_id,
            model=model
        )
        
        self.processes[process_id] = process
        self._save_processes()
        
        return process_id
    
    async def start_process(self, process_id: str, app_client) -> bool:
        """Start a background process."""
        if process_id not in self.processes:
            console.print(f"[red]Process {process_id} not found[/red]")
            return False
        
        process = self.processes[process_id]
        if process.is_active:
            console.print(f"[yellow]Process {process_id} is already running[/yellow]")
            return False
        
        # Create async task for the process
        task = asyncio.create_task(self._run_process(process, app_client))
        self.tasks[process_id] = task
        
        process.status = ProcessStatus.RUNNING
        process.started_at = datetime.now()
        self._save_processes()
        
        console.print(f"[green]✅ Started background process: {process.name} ({process_id})[/green]")
        return True
    
    async def _run_process(self, process: BackgroundProcess, app_client):
        """Run a background process."""
        try:
            process.output_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] Starting process...")
            
            # Use agent invocation for background processing
            if hasattr(app_client, 'agentic') and hasattr(app_client.agentic, 'agents'):
                try:
                    response = app_client.agentic.agents.invoke(
                        input=process.command,
                        session_id=process.session_id or f"bg-{process.id}",
                        model=process.model
                    )
                    
                    if response and "output" in response:
                        # Add response to output lines
                        output_text = response["output"]
                        for line in output_text.split('\n'):
                            if line.strip():
                                timestamp = datetime.now().strftime('%H:%M:%S')
                                process.output_lines.append(f"[{timestamp}] {line}")
                        
                        process.status = ProcessStatus.COMPLETED
                        process.exit_code = 0
                    else:
                        process.status = ProcessStatus.FAILED
                        process.error_lines.append("No output received from agent")
                        process.exit_code = 1
                        
                except Exception as e:
                    process.status = ProcessStatus.FAILED
                    process.error_lines.append(f"Agent invocation error: {str(e)}")
                    process.exit_code = 1
            else:
                # Fallback to chat completions
                try:
                    messages = [{"role": "user", "content": process.command}]
                    response = app_client.chat.completions.create(
                        model=process.model or "agentic-framework:scientific-agent-v1",
                        messages=messages,
                        stream=False
                    )
                    
                    if response.choices:
                        output_text = response.choices[0].message.content
                        for line in output_text.split('\n'):
                            if line.strip():
                                timestamp = datetime.now().strftime('%H:%M:%S')
                                process.output_lines.append(f"[{timestamp}] {line}")
                        
                        process.status = ProcessStatus.COMPLETED
                        process.exit_code = 0
                    else:
                        process.status = ProcessStatus.FAILED
                        process.error_lines.append("No response from chat completion")
                        process.exit_code = 1
                        
                except Exception as e:
                    process.status = ProcessStatus.FAILED
                    process.error_lines.append(f"Chat completion error: {str(e)}")
                    process.exit_code = 1
            
        except asyncio.CancelledError:
            process.status = ProcessStatus.CANCELLED
            process.error_lines.append("Process was cancelled")
            process.exit_code = -1
        except Exception as e:
            process.status = ProcessStatus.FAILED
            process.error_lines.append(f"Unexpected error: {str(e)}")
            process.exit_code = 1
        finally:
            process.completed_at = datetime.now()
            timestamp = datetime.now().strftime('%H:%M:%S')
            process.output_lines.append(f"[{timestamp}] Process completed with status: {process.status.value}")
            
            # Clean up task
            if process.id in self.tasks:
                del self.tasks[process.id]
            
            self._save_processes()
    
    def list_processes(self, show_all: bool = False) -> List[BackgroundProcess]:
        """List background processes."""
        if show_all:
            return list(self.processes.values())
        else:
            # Show only recent processes (last 24 hours)
            cutoff = datetime.now().timestamp() - 86400  # 24 hours
            return [
                proc for proc in self.processes.values()
                if proc.created_at.timestamp() > cutoff
            ]
    
    def get_process(self, process_id: str) -> Optional[BackgroundProcess]:
        """Get a specific process."""
        return self.processes.get(process_id)
    
    async def cancel_process(self, process_id: str) -> bool:
        """Cancel a running process."""
        if process_id not in self.processes:
            console.print(f"[red]Process {process_id} not found[/red]")
            return False
        
        process = self.processes[process_id]
        if not process.is_active:
            console.print(f"[yellow]Process {process_id} is not running[/yellow]")
            return False
        
        if process_id in self.tasks:
            self.tasks[process_id].cancel()
            try:
                await self.tasks[process_id]
            except asyncio.CancelledError:
                pass
        
        process.status = ProcessStatus.CANCELLED
        process.completed_at = datetime.now()
        self._save_processes()
        
        console.print(f"[yellow]Cancelled process: {process.name} ({process_id})[/yellow]")
        return True
    
    def show_process_output(self, process_id: str, tail: int = 20, follow: bool = False):
        """Show process output."""
        if process_id not in self.processes:
            console.print(f"[red]Process {process_id} not found[/red]")
            return
        
        process = self.processes[process_id]
        
        # Show process info
        console.print(Panel.fit(
            f"[bold]Process:[/bold] {process.name} ({process.id})\n"
            f"[bold]Command:[/bold] {process.command[:60]}{'...' if len(process.command) > 60 else ''}\n"
            f"[bold]Status:[/bold] {process.status.value}\n"
            f"[bold]Duration:[/bold] {process.duration:.1f}s" if process.duration else "N/A",
            title="Process Info",
            border_style="blue"
        ))
        
        if follow and process.is_active:
            self._follow_process_output(process)
        else:
            # Show recent output
            output_lines = process.output_lines[-tail:] if tail > 0 else process.output_lines
            
            if output_lines:
                console.print(Panel.fit(
                    "\n".join(output_lines),
                    title="Output",
                    border_style="green"
                ))
            
            if process.error_lines:
                console.print(Panel.fit(
                    "\n".join(process.error_lines),
                    title="Errors",
                    border_style="red"
                ))
    
    def _follow_process_output(self, process: BackgroundProcess):
        """Follow process output in real-time."""
        last_line_count = len(process.output_lines)
        
        console.print("[dim]Following process output... Press Ctrl+C to stop[/dim]")
        
        try:
            with Live(console=console, refresh_per_second=2) as live:
                while process.is_active:
                    current_lines = len(process.output_lines)
                    if current_lines > last_line_count:
                        # Show new lines
                        new_lines = process.output_lines[last_line_count:]
                        content = "\n".join(new_lines)
                        live.update(Text(content))
                        last_line_count = current_lines
                    
                    time.sleep(0.5)
                
                # Show final status
                live.update(Text(f"Process completed with status: {process.status.value}"))
                
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped following output[/yellow]")
    
    def show_processes_table(self, show_all: bool = False):
        """Display processes in a table format."""
        processes = self.list_processes(show_all)
        
        if not processes:
            console.print("[yellow]No background processes found[/yellow]")
            return
        
        table = Table(title=f"Background Processes ({len(processes)} total)")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name", style="white")
        table.add_column("Status", style="yellow")
        table.add_column("Duration", justify="right", style="green")
        table.add_column("Command", style="dim")
        
        # Sort by creation time (newest first)
        processes.sort(key=lambda p: p.created_at, reverse=True)
        
        for process in processes:
            # Status styling
            if process.status == ProcessStatus.RUNNING:
                status_style = "green"
            elif process.status == ProcessStatus.COMPLETED:
                status_style = "blue"
            elif process.status in [ProcessStatus.FAILED, ProcessStatus.CANCELLED]:
                status_style = "red"
            else:
                status_style = "yellow"
            
            duration_str = f"{process.duration:.1f}s" if process.duration else "N/A"
            command_preview = process.command[:40] + "..." if len(process.command) > 40 else process.command
            
            table.add_row(
                process.id,
                process.name,
                f"[{status_style}]{process.status.value}[/{status_style}]",
                duration_str,
                command_preview
            )
        
        console.print(table)
    
    def cleanup_old_processes(self, days: int = 7):
        """Clean up old completed processes."""
        cutoff = datetime.now().timestamp() - (days * 86400)
        to_remove = []
        
        for process_id, process in self.processes.items():
            if (not process.is_active and 
                process.created_at.timestamp() < cutoff):
                to_remove.append(process_id)
        
        for process_id in to_remove:
            del self.processes[process_id]
        
        if to_remove:
            self._save_processes()
            console.print(f"[green]Cleaned up {len(to_remove)} old processes[/green]")
    
    async def shutdown(self):
        """Shutdown the background manager."""
        # Cancel all running tasks
        for process_id, task in list(self.tasks.items()):
            if not task.done():
                console.print(f"[yellow]Cancelling background process: {process_id}[/yellow]")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Mark running processes as failed
        for process in self.processes.values():
            if process.is_active:
                process.status = ProcessStatus.FAILED
                process.completed_at = datetime.now()
                process.error_lines.append("Process interrupted by CLI shutdown")
        
        self._save_processes()
        self.executor.shutdown(wait=False)
        console.print("[dim]Background manager shut down[/dim]")