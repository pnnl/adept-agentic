#!/usr/bin/env python3
"""
Keyboard Control Handler for Agentic Framework CLI

Provides terminal-style job control with keyboard shortcuts:
- Ctrl+B Ctrl+B: Send current process to background
- Ctrl+C: Interrupt current process (with backgrounding option)
- Ctrl+Z: Pause current process (suspend)
- Ctrl+D: EOF handling

Similar to bash job control but adapted for AI agent processes.
"""

import asyncio
import signal
import sys
import termios
import tty
from typing import Optional, Callable, Dict, Any
from datetime import datetime
import threading
import queue

from rich.console import Console
from rich.panel import Panel

console = Console()

class KeyboardHandler:
    """Handles keyboard control sequences for process management."""
    
    def __init__(self):
        self.current_task: Optional[asyncio.Task] = None
        self.current_process_info: Optional[Dict[str, Any]] = None
        self.background_callback: Optional[Callable] = None
        self.interrupt_callback: Optional[Callable] = None
        self.pause_callback: Optional[Callable] = None
        
        # Control sequence state
        self.ctrl_sequence_active = False
        self.last_ctrl_key = None
        self.sequence_timeout = 1.0  # 1 second for sequence completion
        
        # Terminal state
        self.original_settings = None
        self.in_raw_mode = False
        
        # Key sequence mappings
        self.control_sequences = {
            ('ctrl+b', 'ctrl+b'): self._handle_background_sequence,
            ('ctrl+c', 'ctrl+c'): self._handle_ctrl_c,
        }
        
    def setup_terminal(self):
        """Setup terminal for raw input mode."""
        if sys.stdin.isatty():
            try:
                self.original_settings = termios.tcgetattr(sys.stdin.fileno())
                tty.setraw(sys.stdin.fileno())
                self.in_raw_mode = True
            except (termios.error, OSError):
                # Not a TTY or can't set raw mode
                self.in_raw_mode = False
    
    def restore_terminal(self):
        """Restore terminal settings."""
        if self.in_raw_mode and self.original_settings:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.original_settings)
                self.in_raw_mode = False
            except (termios.error, OSError):
                pass
    
    def set_current_process(self, task: asyncio.Task, process_info: Dict[str, Any]):
        """Set the currently running process."""
        self.current_task = task
        self.current_process_info = process_info
    
    def clear_current_process(self):
        """Clear the current process."""
        self.current_task = None
        self.current_process_info = None
    
    def set_callbacks(self, 
                     background_callback: Callable = None,
                     interrupt_callback: Callable = None,
                     pause_callback: Callable = None):
        """Set callback functions for process control."""
        self.background_callback = background_callback
        self.interrupt_callback = interrupt_callback
        self.pause_callback = pause_callback
    
    async def handle_keyboard_input(self) -> bool:
        """
        Handle keyboard input in non-blocking way.
        Returns True if input was handled, False if should be passed through.
        """
        if not self.in_raw_mode:
            return False
            
        try:
            # Check if input is available without blocking
            if not sys.stdin.readable():
                return False
                
            char = sys.stdin.read(1)
            if not char:
                return False
                
            # Handle control characters
            ord_char = ord(char)
            
            # Ctrl+C (ASCII 3)
            if ord_char == 3:
                return await self._handle_ctrl_c()
            
            # Ctrl+B (ASCII 2)
            elif ord_char == 2:
                return await self._handle_ctrl_b()
            
            # Ctrl+Z (ASCII 26)
            elif ord_char == 26:
                return await self._handle_ctrl_z()
            
            # Ctrl+D (ASCII 4)
            elif ord_char == 4:
                return await self._handle_ctrl_d()
            
            # Regular character - not handled
            else:
                return False
                
        except (OSError, IOError):
            return False
    
    async def _handle_ctrl_c(self) -> bool:
        """Handle Ctrl+C interrupt."""
        if not self.current_task or self.current_task.done():
            # No active process, let it through for normal handling
            return False
        
        # First Ctrl+C: Show options
        if not hasattr(self, '_ctrl_c_pressed'):
            self._ctrl_c_pressed = True
            
            console.print("\n[yellow]⚠️  Process interrupted![/yellow]")
            console.print(Panel.fit(
                "[bold]Options:[/bold]\n"
                "• [green]Ctrl+C again[/green] - Terminate process\n"
                "• [blue]Ctrl+B Ctrl+B[/blue] - Send to background\n"
                "• [yellow]Enter[/yellow] - Cancel and return to foreground\n"
                "• [red]Ctrl+D[/red] - Force quit CLI",
                title="Process Control",
                border_style="yellow"
            ))
            
            # Set a timeout to clear the flag
            asyncio.create_task(self._clear_ctrl_c_flag())
            return True
        
        # Second Ctrl+C: Actually interrupt
        else:
            delattr(self, '_ctrl_c_pressed')
            if self.interrupt_callback:
                await self.interrupt_callback(self.current_process_info)
            else:
                self.current_task.cancel()
            
            console.print("[red]🛑 Process terminated[/red]")
            self.clear_current_process()
            return True
    
    async def _handle_ctrl_b(self) -> bool:
        """Handle Ctrl+B for background sequence."""
        current_time = datetime.now()
        
        # Check if this is the second Ctrl+B in sequence
        if (hasattr(self, '_first_ctrl_b_time') and 
            (current_time - self._first_ctrl_b_time).total_seconds() < self.sequence_timeout):
            
            # Second Ctrl+B - execute background command
            delattr(self, '_first_ctrl_b_time')
            return await self._handle_background_sequence()
        
        else:
            # First Ctrl+B - start sequence
            self._first_ctrl_b_time = current_time
            console.print("[dim]Ctrl+B... (press Ctrl+B again to background process)[/dim]")
            
            # Set timeout to clear the sequence
            asyncio.create_task(self._clear_ctrl_b_sequence())
            return True
    
    async def _handle_ctrl_z(self) -> bool:
        """Handle Ctrl+Z for process suspension."""
        if not self.current_task or self.current_task.done():
            return False
        
        console.print("\n[yellow]⏸️  Process suspended[/yellow]")
        console.print("[dim]Note: Process continues running in the background. Use '/bg list' to monitor.[/dim]")
        
        if self.pause_callback:
            await self.pause_callback(self.current_process_info)
        
        # In our context, "suspend" means background the process
        return await self._handle_background_sequence()
    
    async def _handle_ctrl_d(self) -> bool:
        """Handle Ctrl+D EOF."""
        if self.current_task and not self.current_task.done():
            console.print("\n[red]⚠️  Cannot exit with active process. Use Ctrl+C to interrupt or Ctrl+B Ctrl+B to background.[/red]")
            return True
        
        console.print("\n[dim]Goodbye![/dim]")
        sys.exit(0)
    
    async def _handle_background_sequence(self) -> bool:
        """Handle the Ctrl+B Ctrl+B sequence to background a process."""
        if not self.current_task or self.current_task.done():
            console.print("[yellow]No active process to background[/yellow]")
            return True
        
        if not self.current_process_info:
            console.print("[red]Cannot background process - no process info available[/red]")
            return True
        
        console.print("[blue]📤 Sending process to background...[/blue]")
        
        if self.background_callback:
            success = await self.background_callback(self.current_process_info)
            if success:
                process_name = self.current_process_info.get('name', 'unknown')
                process_id = self.current_process_info.get('id', 'unknown')
                
                console.print(Panel.fit(
                    f"[green]✅ Process backgrounded successfully[/green]\n\n"
                    f"[bold]Process:[/bold] {process_name}\n"
                    f"[bold]ID:[/bold] {process_id}\n\n"
                    f"[dim]Use the following commands to monitor:[/dim]\n"
                    f"• [cyan]/bg show {process_id}[/cyan] - View output\n"
                    f"• [cyan]/bg show {process_id} --follow[/cyan] - Follow in real-time\n"
                    f"• [cyan]/bg list[/cyan] - List all processes",
                    title="🚀 Process Backgrounded",
                    border_style="green"
                ))
                
                self.clear_current_process()
                return True
            else:
                console.print("[red]❌ Failed to background process[/red]")
                return True
        else:
            console.print("[red]Background callback not available[/red]")
            return True
    
    async def _clear_ctrl_c_flag(self):
        """Clear the Ctrl+C flag after timeout."""
        await asyncio.sleep(3.0)  # 3 second timeout
        if hasattr(self, '_ctrl_c_pressed'):
            delattr(self, '_ctrl_c_pressed')
            console.print("[dim]Interrupt timeout - process continues[/dim]")
    
    async def _clear_ctrl_b_sequence(self):
        """Clear the Ctrl+B sequence after timeout."""
        await asyncio.sleep(self.sequence_timeout)
        if hasattr(self, '_first_ctrl_b_time'):
            delattr(self, '_first_ctrl_b_time')
    
    def show_control_help(self):
        """Show keyboard control help."""
        help_panel = Panel.fit(
            "[bold blue]🎮 Keyboard Controls[/bold blue]\n\n"
            "[bold]During Process Execution:[/bold]\n"
            "• [green]Ctrl+C[/green] - Interrupt (shows options)\n"
            "• [blue]Ctrl+B Ctrl+B[/blue] - Send to background\n"
            "• [yellow]Ctrl+Z[/yellow] - Suspend (backgrounds process)\n"
            "• [red]Ctrl+D[/red] - Quit CLI (if no active process)\n\n"
            "[bold]Two-Stage Interrupt:[/bold]\n"
            "1. First [green]Ctrl+C[/green] - Shows control options\n"
            "2. Second [green]Ctrl+C[/green] - Actually terminates\n"
            "   Or [blue]Ctrl+B Ctrl+B[/blue] - Backgrounds instead\n\n"
            "[dim]Similar to bash job control but for AI processes[/dim]",
            title="Process Control Help",
            border_style="blue"
        )
        console.print(help_panel)

# Global keyboard handler instance
keyboard_handler = KeyboardHandler()

def setup_keyboard_handling():
    """Setup global keyboard handling."""
    keyboard_handler.setup_terminal()

def cleanup_keyboard_handling():
    """Cleanup global keyboard handling."""
    keyboard_handler.restore_terminal()

async def monitor_keyboard_during_process(task: asyncio.Task, process_info: Dict[str, Any]) -> bool:
    """
    Monitor keyboard input during process execution.
    Returns True if process was backgrounded, False if completed normally.
    """
    keyboard_handler.set_current_process(task, process_info)
    
    try:
        while not task.done():
            # Check for keyboard input
            await keyboard_handler.handle_keyboard_input()
            
            # If process was backgrounded, return True
            if keyboard_handler.current_task is None:
                return True
            
            # Small delay to prevent busy waiting
            await asyncio.sleep(0.1)
        
        # Process completed normally
        keyboard_handler.clear_current_process()
        return False
        
    except asyncio.CancelledError:
        keyboard_handler.clear_current_process()
        raise