#!/usr/bin/env python3
"""
Agentic Framework CLI

Complete command-line interface for scientific AI workflows with OpenAI compatibility and UCS extensions.

Usage:
    # Basic Chat
    agentic chat                    # Interactive chat mode
    agentic chat-plus --attach file.csv  # Enhanced chat with file uploads
    
    # Background Process Management (Claude CLI-style)
    agentic bg run "Analyze protein sequence MKLLV..." --name protein_analysis
    agentic bg list                 # List running processes
    agentic bg show abc123          # Show process output
    agentic bg show abc123 --follow # Follow process in real-time
    agentic bg cancel abc123        # Cancel running process
    agentic bg cleanup              # Clean up old processes
    
    # File Management (supports @ navigation)
    agentic files upload file.txt   # Upload file for AI processing
    agentic files upload @*.csv     # Interactive picker for CSV files
    agentic files upload @data/     # Browse data directory
    agentic files list             # List uploaded files
    agentic files download FILE_ID # Download file by ID
    agentic files delete FILE_ID   # Delete file
    
    # Assistants API
    agentic assistants create      # Create AI assistant
    agentic assistants list        # List assistants
    
    # Threads & Conversations
    agentic threads create         # Create conversation thread
    agentic threads run THREAD_ID ASSISTANT_ID  # Run assistant on thread
    
    # UCS Extensions
    agentic agents invoke "text"   # Direct agent invocation
    agentic agents sessions        # List agent sessions

    # A2A Federation (Agent-to-Agent)
    agentic a2a generate-token     # Generate A2A auth token for federation
    agentic a2a generate-token --gateway-alias university-a  # With alias
    agentic a2a test-token --token TOKEN  # Test A2A token validity

    # Tool Management
    agentic tools list            # Available tools
    agentic tools register NAME   # Register external tool (admin)
    agentic tools delete NAME     # Delete external tool (admin)

    # Utilities
    agentic sessions list          # List saved sessions
    agentic benchmark             # Performance benchmarks
    agentic config show           # Show configuration
"""

import asyncio
import json
import sys
import os
import glob
import fnmatch
import logging
import shutil
import time
import warnings
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from logging.handlers import RotatingFileHandler

# Suppress SSL development warnings in CLI — every command connects to
# api.agentic.local with self-signed certs, so the warning is just noise.
# Library users who import the SDK directly still see it.
warnings.filterwarnings("ignore", message="Using self-signed certificate")

import click
import httpx
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.tree import Tree
from rich.columns import Columns
from rich import box

# Import our SDK
try:
    from agentic_framework_sdk import OpenAI, AsyncOpenAI
    from agentic_framework_sdk.exceptions import APIError, AuthenticationError
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False
    OpenAI = None
    AsyncOpenAI = None
    print("Warning: SDK not available. Please install agentic-framework-sdk.")

# Import background process manager
try:
    from .background_manager import BackgroundManager, ProcessStatus
    BACKGROUND_SUPPORT = True
except ImportError:
    BACKGROUND_SUPPORT = False
    BackgroundManager = None
    ProcessStatus = None

# Import keyboard handler
try:
    from .keyboard_handler import (
        keyboard_handler, 
        setup_keyboard_handling, 
        cleanup_keyboard_handling,
        monitor_keyboard_during_process
    )
    KEYBOARD_SUPPORT = True
except ImportError:
    KEYBOARD_SUPPORT = False
    keyboard_handler = None

def _create_console(config: Optional[Dict[str, Any]] = None) -> Console:
    """Create a Rich console respecting user configuration.

    By default (no config or color_output=False), all Rich rendering is
    disabled for maximum terminal compatibility.  When color_output=True,
    Rich markup and color are enabled for non-streaming output.

    Streaming chat output always bypasses the Rich console to avoid the
    ANSI cursor-repositioning bugs that caused terminal corruption in
    Session 59.
    """
    if config and config.get("color_output", False):
        return Console(highlight=False)
    return Console(no_color=True, force_terminal=False, highlight=False)


# Module-level active config — populated when AgenticCLI loads.
_active_config: Dict[str, Any] = {}


def _get_active_config() -> Dict[str, Any]:
    """Return the active CLI configuration (set during AgenticCLI init)."""
    return _active_config


# Module level — safe default before config loads
console = _create_console()


def _print_panel(content: str, title: str = "", border_style: str = "blue"):
    """Print a Rich Panel if rich_panels enabled, otherwise plain text."""
    cfg = _get_active_config()
    if cfg.get("rich_panels", False) and cfg.get("color_output", False):
        console.print(Panel.fit(content, title=title, border_style=border_style))
    else:
        if title:
            click.echo(f"── {title} ──")
        click.echo(content)


def _print_table(table: Table):
    """Print a Rich Table if rich_tables enabled, otherwise plain text."""
    cfg = _get_active_config()
    if cfg.get("rich_tables", False) and cfg.get("color_output", False):
        console.print(table)
    else:
        # Table renders as plain ASCII when console has no_color
        console.print(table)


def _print_markdown(text: str):
    """Render Markdown via Rich if rich_markdown enabled, otherwise raw text."""
    cfg = _get_active_config()
    if cfg.get("rich_markdown", False) and cfg.get("color_output", False):
        console.print(Markdown(text))
    else:
        click.echo(text)


class ConfigManager:
    """Advanced configuration manager for Agentic Framework CLI."""
    
    def __init__(self):
        self._ensure_directories()
        self._setup_logging()
        self.config = self._load_config()
        self._cleanup_temp_files()
        self._check_cache_size()
    
    def _ensure_directories(self):
        """Create all necessary directories."""
        directories = [
            CONFIG_DIR, SESSIONS_DIR, LOGS_DIR, CACHE_DIR, 
            UPLOADS_DIR, VECTOR_STORE_DIR, TEMP_DIR
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            
        # Set appropriate permissions
        for directory in directories:
            directory.chmod(0o700)  # Owner read/write/execute only
    
    def _setup_logging(self):
        """Setup rotating file logging."""
        log_file = LOGS_DIR / "agentic-cli.log"
        
        # Create rotating file handler
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=MAX_LOG_SIZE,
            backupCount=MAX_LOG_FILES
        )
        
        # Create console handler for errors
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.ERROR)
        
        # Set up formatting
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # Configure root logger
        logger = logging.getLogger('agentic_cli')
        logger.setLevel(logging.INFO)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        # Prevent duplicate logs
        logger.propagate = False
        
        self.logger = logger
        self.logger.info("CLI session started")
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration with enhanced defaults."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    config = json.load(f)
                self.logger.info("Configuration loaded successfully")
            except Exception as e:
                self.logger.error(f"Failed to load config: {e}")
                config = {}
        else:
            config = {}
        
        # Enhanced default configuration
        defaults = {
            # Connection settings
            "gateway_url": os.getenv("AGENT_GATEWAY_URL", "https://api.agentic.local"),
            "model": "agentic-framework:scientific-agent-v1",
            "api_key": None,
            
            # Session settings
            "default_session_prefix": "cli-session", 
            "auto_save_sessions": True,
            "session_history_limit": 100,
            
            # Chat settings
            "max_tokens": 2000,
            "temperature": 0.7,
            "stream": True,
            "auto_attach_context": True,
            
            # File management
            "upload_cache_ttl": 3600,  # 1 hour
            "auto_cleanup_temp": True,
            "compress_uploads": True,
            
            # Vector store settings
            "enable_local_vectorstore": True,
            "vectorstore_chunk_size": 1000,
            "vectorstore_chunk_overlap": 200,
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            
            # Logging settings
            "log_level": "INFO",
            "log_api_calls": False,
            "log_file_operations": True,
            
            # Performance settings
            "request_timeout": 300,
            "max_concurrent_uploads": 3,
            "enable_request_cache": True,
            
            # UI settings
            "color_output": True,
            "show_progress_bars": True,
            "confirm_destructive_actions": True,
            "rich_panels": True,
            "rich_tables": True,
            "rich_markdown": False,
        }
        
        # Merge with loaded config, defaults take precedence for missing keys
        for key, default_value in defaults.items():
            if key not in config:
                config[key] = default_value

        # Environment variable overrides saved config (Session 59 bootstrap fix)
        # This ensures AGENT_GATEWAY_URL=http://localhost:8083 agentic chat works
        # even when config.json has a different (e.g. Docker-internal) URL saved.
        env_gateway = os.getenv("AGENT_GATEWAY_URL")
        if env_gateway:
            config["gateway_url"] = env_gateway

        return config
    
    def save_config(self):
        """Save current configuration to file."""
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=2, default=str)
            CONFIG_FILE.chmod(0o600)  # Secure permissions
            self.logger.info("Configuration saved successfully")
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")
    
    def _cleanup_temp_files(self):
        """Clean up old temporary files."""
        if not self.config.get("auto_cleanup_temp", True):
            return
            
        try:
            # Clean files older than 1 hour
            cutoff_time = datetime.now().timestamp() - 3600
            
            for temp_file in TEMP_DIR.iterdir():
                if temp_file.stat().st_mtime < cutoff_time:
                    if temp_file.is_file():
                        temp_file.unlink()
                    elif temp_file.is_dir():
                        shutil.rmtree(temp_file)
            
            self.logger.debug("Temporary files cleaned up")
        except Exception as e:
            self.logger.warning(f"Failed to cleanup temp files: {e}")
    
    def _check_cache_size(self):
        """Monitor and manage cache size."""
        try:
            total_size = sum(
                f.stat().st_size 
                for f in CACHE_DIR.rglob('*') 
                if f.is_file()
            )
            
            if total_size > MAX_CACHE_SIZE:
                self._cleanup_cache()
                
        except Exception as e:
            self.logger.warning(f"Failed to check cache size: {e}")
    
    def _cleanup_cache(self):
        """Remove oldest cache files when limit exceeded."""
        try:
            # Get all cache files with their modification times
            cache_files = []
            for cache_file in CACHE_DIR.rglob('*'):
                if cache_file.is_file():
                    cache_files.append((
                        cache_file.stat().st_mtime,
                        cache_file.stat().st_size,
                        cache_file
                    ))
            
            # Sort by modification time (oldest first)
            cache_files.sort()
            
            # Remove files until we're under the limit
            total_removed = 0
            for mtime, size, cache_file in cache_files:
                cache_file.unlink()
                total_removed += size
                
                remaining_size = sum(
                    f.stat().st_size 
                    for f in CACHE_DIR.rglob('*') 
                    if f.is_file()
                )
                
                if remaining_size <= MAX_CACHE_SIZE * 0.8:  # 80% of limit
                    break
            
            self.logger.info(f"Cache cleanup: removed {total_removed} bytes")
            
        except Exception as e:
            self.logger.error(f"Failed to cleanup cache: {e}")
    
    def get_upload_path(self, filename: str) -> Path:
        """Get secure path for file upload."""
        # Sanitize filename
        safe_filename = "".join(
            c for c in filename 
            if c.isalnum() or c in ('-', '_', '.')
        )
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{timestamp}_{safe_filename}"
        
        return UPLOADS_DIR / unique_filename
    
    def get_cache_path(self, cache_key: str) -> Path:
        """Get cache file path for a given key."""
        safe_key = "".join(
            c for c in cache_key 
            if c.isalnum() or c in ('-', '_')
        )
        return CACHE_DIR / f"{safe_key}.cache"
    
    def get_vector_store_path(self) -> Path:
        """Get path for local vector store."""
        return VECTOR_STORE_DIR / "local_store"
    
    def log_api_call(self, endpoint: str, method: str, status: int, duration: float):
        """Log API call if enabled."""
        if self.config.get("log_api_calls", False):
            self.logger.info(
                f"API Call: {method} {endpoint} -> {status} ({duration:.2f}s)"
            )
    
    def log_file_operation(self, operation: str, file_path: str, success: bool):
        """Log file operation if enabled."""
        if self.config.get("log_file_operations", True):
            status = "SUCCESS" if success else "FAILED"
            self.logger.info(f"File {operation}: {file_path} -> {status}")
    
    def update_config(self, key: str, value: Any):
        """Update a configuration value."""
        self.config[key] = value
        self.save_config()
        self.logger.info(f"Configuration updated: {key} = {value}")
    
    def get_env_info(self) -> Dict[str, Any]:
        """Get environment information for diagnostics."""
        return {
            "config_dir": str(CONFIG_DIR),
            "config_exists": CONFIG_FILE.exists(),
            "directories": {
                "sessions": len(list(SESSIONS_DIR.glob("*.json"))),
                "logs": len(list(LOGS_DIR.glob("*.log*"))),
                "cache_files": len(list(CACHE_DIR.glob("*"))),
                "uploads": len(list(UPLOADS_DIR.glob("*"))),
                "temp_files": len(list(TEMP_DIR.glob("*"))),
            },
            "disk_usage": {
                "cache_size": sum(
                    f.stat().st_size for f in CACHE_DIR.rglob('*') if f.is_file()
                ),
                "uploads_size": sum(
                    f.stat().st_size for f in UPLOADS_DIR.rglob('*') if f.is_file()
                ),
            },
            "python_version": sys.version,
            "platform": sys.platform,
        }

# Configuration - Enhanced directory structure
CONFIG_DIR = Path.home() / ".adept-agentic"
CONFIG_FILE = CONFIG_DIR / "config.json"
SESSIONS_DIR = CONFIG_DIR / "sessions"
LOGS_DIR = CONFIG_DIR / "logs"
CACHE_DIR = CONFIG_DIR / "cache"
UPLOADS_DIR = CONFIG_DIR / "uploads" 
VECTOR_STORE_DIR = CONFIG_DIR / "vector_store"
TEMP_DIR = CONFIG_DIR / "temp"

# File size limits
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
MAX_CACHE_SIZE = 500 * 1024 * 1024  # 500MB
MAX_LOG_SIZE = 10 * 1024 * 1024     # 10MB per log file
MAX_LOG_FILES = 5                    # Keep 5 rotated log files

class AgenticCLI:
    """Main CLI application class with enhanced configuration management."""
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.config = self.config_manager.config
        self.logger = self.config_manager.logger
        self.client = None
        self.current_session = None
        self.session_history = []
        self.conversation_history = []

        # Reconfigure global console based on loaded config (persisted
        # in ~/.adept-agentic/config.json).
        global console, _active_config
        _active_config = self.config
        console = _create_console(self.config)

        # Initialize background process manager
        if BACKGROUND_SUPPORT:
            self.background_manager = BackgroundManager(CONFIG_DIR)
        else:
            self.background_manager = None
            
        # Keyboard handling is only for interactive chat sessions.
        # Do NOT set up here — it puts the terminal into raw mode
        # (tty.setraw) which breaks newline handling for all output.
        # Interactive commands that need it should call setup_keyboard_handling() themselves.
    
    def _save_config(self):
        """Save CLI configuration using ConfigManager."""
        self.config_manager.save_config()
    
    def _initialize_client(self) -> bool:
        """Initialize SDK client with current configuration."""
        if not SDK_AVAILABLE:
            console.print("[red]SDK not available. Please install agentic-framework-sdk.[/red]")
            return False

        try:
            token = None

            # Priority 1: Fresh token from 'agentic auth login' (TokenStorage)
            try:
                from agentic_framework_sdk.auth import TokenStorage
                ts = TokenStorage()
                if ts.is_token_valid():
                    token_info = ts.get_token()
                    token = token_info.get("access_token")
            except Exception:
                pass  # TokenStorage unavailable or no valid token

            # Priority 2: Saved api_key from config (may be stale)
            if not token:
                token = self.config.get("api_key")

            # Priority 3: Auto-auth via Keycloak ROPC (notebook-user)
            if not token:
                token = self._get_user_token()

            if not token:
                console.print("[red]Authentication failed. Use 'agentic auth login' or 'agentic config set api_key <token>'.[/red]")
                return False

            self.client = OpenAI(
                base_url=f"{self.config['gateway_url']}/v1",
                api_key=token,
                timeout=float(self.config.get("request_timeout", 300)),
            )

            # Update config with current token for session reuse
            self.config["api_key"] = token
            self._save_config()

            # Test the connection
            models = self.client.models.list()
            if not models.get("data"):
                console.print("[yellow]Warning: No models available. Check connection.[/yellow]")

            return True

        except Exception as e:
            console.print(f"[red]Failed to initialize client: {e}[/red]")
            return False
    
    def _get_user_token(self) -> Optional[str]:
        """Get user token using Keycloak ROPC flow."""
        try:
            import requests
            
            keycloak_url = os.getenv('KEYCLOAK_URL', 'http://localhost:8180')
            keycloak_realm = os.getenv('KEYCLOAK_REALM', 'master')
            token_url = f"{keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/token"
            
            payload = {
                'client_id': 'login-client',
                'username': 'notebook-user',
                'password': 'notebook-password',
                'grant_type': 'password'
            }
            
            response = requests.post(token_url, data=payload, timeout=10)
            response.raise_for_status()
            token_data = response.json()
            return token_data['access_token']
                
        except Exception as e:
            console.print(f"[yellow]Auto-authentication failed: {e}[/yellow]")
            return None
    
    async def _background_current_process(self, process_info: Dict[str, Any]) -> bool:
        """Callback to background current process."""
        if not self.background_manager:
            return False
        
        try:
            # Create background process from current process
            process_id = self.background_manager.create_process(
                command=process_info.get('command', 'Unknown command'),
                name=process_info.get('name', f"bg-{int(time.time())}"),
                session_id=process_info.get('session_id', self.current_session),
                model=process_info.get('model', self.config.get('model'))
            )
            
            # The actual process continues running, we just track it as background
            process = self.background_manager.get_process(process_id)
            if process:
                process.status = ProcessStatus.RUNNING
                process.started_at = datetime.now()
                self.background_manager._save_processes()
                return True
            
        except Exception as e:
            console.print(f"[red]Failed to background process: {e}[/red]")
        
        return False
    
    async def _interrupt_current_process(self, process_info: Dict[str, Any]):
        """Callback to interrupt current process."""
        console.print("[red]Process interrupted by user[/red]")
        # The actual cancellation is handled by the keyboard handler
        
    async def _pause_current_process(self, process_info: Dict[str, Any]):
        """Callback to pause current process (suspend)."""
        console.print("[yellow]Process suspended[/yellow]")
        # In our context, pause = background


# ====================================================================================
# INTERACTIVE FILE PICKER WITH @ NAVIGATION
# ====================================================================================

class FilePickerPath(click.Path):
    """Custom Click path type that supports @ navigation for interactive file picking."""
    
    def convert(self, value, param, ctx):
        if isinstance(value, str) and value.startswith('@'):
            # Handle @ navigation
            return self._handle_at_navigation(value[1:], param, ctx)
        else:
            # Use standard Click path handling
            return super().convert(value, param, ctx)
    
    def _handle_at_navigation(self, pattern: str, param, ctx) -> str:
        """Handle @ prefixed paths with interactive file picker."""
        try:
            # Show interactive file picker
            selected = interactive_file_picker(pattern, multi_select=getattr(param, 'multiple', False))
            
            if selected:
                if isinstance(selected, list):
                    return selected if len(selected) > 1 else selected[0]
                return selected
            else:
                # User cancelled or no selection
                ctx.abort()
        except KeyboardInterrupt:
            console.print("\n[yellow]File selection cancelled.[/yellow]")
            ctx.abort()
        except Exception as e:
            console.print(f"[red]File picker error: {e}[/red]")
            ctx.abort()


def interactive_file_picker(pattern: str = "", multi_select: bool = False) -> Union[str, List[str], None]:
    """Interactive file picker with rich UI."""
    
    current_dir = Path.cwd()
    if pattern:
        # Handle different pattern types
        if pattern.startswith('/'):
            current_dir = Path(pattern)
        elif pattern.startswith('..'):
            current_dir = current_dir / pattern
        elif pattern.endswith('/'):
            current_dir = current_dir / pattern
        elif '*' in pattern or '?' in pattern:
            # Pattern matching mode
            return _pattern_file_picker(pattern, multi_select)
        else:
            # Fuzzy search mode
            return _fuzzy_file_picker(pattern, multi_select)
    
    # Directory browsing mode
    return _directory_file_picker(current_dir, multi_select)


def _pattern_file_picker(pattern: str, multi_select: bool) -> Union[str, List[str], None]:
    """Handle pattern-based file selection (*.txt, *.csv, etc.)."""
    
    matches = glob.glob(pattern, recursive=True)
    if not matches:
        console.print(f"[yellow]No files found matching pattern: {pattern}[/yellow]")
        return None
    
    # Sort matches by name and type
    matches.sort()
    files = [Path(m) for m in matches if Path(m).is_file()]
    
    if not files:
        console.print(f"[yellow]No files found matching pattern: {pattern}[/yellow]")
        return None
    
    console.print(f"\n📄 Files matching '{pattern}' ({len(files)} found):")
    
    # Create selection table
    table = Table(show_header=True, header_style="bold blue", box=box.MINIMAL)
    table.add_column("#", style="cyan", width=4)
    table.add_column("File", style="white")
    table.add_column("Size", justify="right", style="yellow", width=10)
    table.add_column("Modified", style="dim", width=16)
    
    for i, file_path in enumerate(files, 1):
        try:
            stat = file_path.stat()
            size = _format_file_size(stat.st_size)
            modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
        except:
            size, modified = "N/A", "N/A"
            
        table.add_row(str(i), str(file_path), size, modified)
    
    console.print(table)
    
    if multi_select:
        console.print(f"\n[dim]Enter numbers (e.g., '1,3,5' or '1-3') or 'all' for all files:[/dim]")
    else:
        console.print(f"\n[dim]Enter file number (1-{len(files)}):[/dim]")
    
    while True:
        try:
            selection = Prompt.ask("Select").strip()
            
            if not selection:
                return None
                
            if multi_select and selection.lower() == 'all':
                return [str(f) for f in files]
            
            # Parse selection
            selected_indices = _parse_selection(selection, len(files))
            if selected_indices:
                selected_files = [str(files[i-1]) for i in selected_indices]
                return selected_files if multi_select else selected_files[0]
            else:
                console.print(f"[red]Invalid selection. Enter numbers 1-{len(files)}[/red]")
                
        except KeyboardInterrupt:
            return None


def _fuzzy_file_picker(search_term: str, multi_select: bool) -> Union[str, List[str], None]:
    """Handle fuzzy search-based file selection."""
    
    current_dir = Path.cwd()
    all_files = []
    
    # Get all files in current directory and subdirectories
    try:
        for file_path in current_dir.rglob('*'):
            if file_path.is_file():
                all_files.append(file_path)
    except PermissionError:
        # Fall back to current directory only
        for file_path in current_dir.iterdir():
            if file_path.is_file():
                all_files.append(file_path)
    
    # Filter files by fuzzy matching
    matched_files = []
    search_lower = search_term.lower()
    
    for file_path in all_files:
        file_name_lower = file_path.name.lower()
        file_path_lower = str(file_path).lower()
        
        # Simple fuzzy matching: contains all characters in order
        if _fuzzy_match(search_lower, file_name_lower) or search_lower in file_path_lower:
            matched_files.append(file_path)
    
    if not matched_files:
        console.print(f"[yellow]No files found matching '{search_term}'[/yellow]")
        return None
    
    # Sort by relevance (name matches first, then path matches)
    matched_files.sort(key=lambda f: (
        search_lower not in f.name.lower(),  # Name matches first
        len(str(f)),  # Shorter paths first
        str(f).lower()  # Alphabetical
    ))
    
    # Limit results for performance
    matched_files = matched_files[:50]
    
    console.print(f"\n🔍 Files matching '{search_term}' ({len(matched_files)} found):")
    
    # Create selection table
    table = Table(show_header=True, header_style="bold blue", box=box.MINIMAL)
    table.add_column("#", style="cyan", width=4)
    table.add_column("File", style="white")
    table.add_column("Directory", style="dim")
    table.add_column("Size", justify="right", style="yellow", width=10)
    
    for i, file_path in enumerate(matched_files, 1):
        try:
            stat = file_path.stat()
            size = _format_file_size(stat.st_size)
        except:
            size = "N/A"
            
        # Highlight matching parts
        file_name = str(file_path.name)
        directory = str(file_path.parent) if file_path.parent != Path('.') else "."
            
        table.add_row(str(i), file_name, directory, size)
    
    console.print(table)
    
    if multi_select:
        console.print(f"\n[dim]Enter numbers (e.g., '1,3,5' or '1-3') or 'all':[/dim]")
    else:
        console.print(f"\n[dim]Enter file number (1-{len(matched_files)}):[/dim]")
    
    while True:
        try:
            selection = Prompt.ask("Select").strip()
            
            if not selection:
                return None
                
            if multi_select and selection.lower() == 'all':
                return [str(f) for f in matched_files]
            
            # Parse selection
            selected_indices = _parse_selection(selection, len(matched_files))
            if selected_indices:
                selected_files = [str(matched_files[i-1]) for i in selected_indices]
                return selected_files if multi_select else selected_files[0]
            else:
                console.print(f"[red]Invalid selection. Enter numbers 1-{len(matched_files)}[/red]")
                
        except KeyboardInterrupt:
            return None


def _directory_file_picker(start_dir: Path, multi_select: bool) -> Union[str, List[str], None]:
    """Interactive directory browser for file selection."""
    
    current_dir = start_dir.resolve()
    selected_files = []
    
    while True:
        console.clear()
        console.print(Panel.fit(
            f"📁 [bold blue]Interactive File Browser[/bold blue]\n"
            f"Directory: {current_dir}\n"
            f"{'Multi-select mode' if multi_select else 'Single-select mode'}",
            title="File Picker",
            border_style="blue"
        ))
        
        # Get directory contents
        try:
            items = []
            
            # Add parent directory option
            if current_dir.parent != current_dir:
                items.append(("📁 ..", current_dir.parent, True, 0))
            
            # Add directories
            dirs = []
            files = []
            
            for item in current_dir.iterdir():
                try:
                    if item.is_dir():
                        dirs.append(item)
                    elif item.is_file():
                        files.append(item)
                except PermissionError:
                    continue
            
            # Sort directories and files
            dirs.sort()
            files.sort()
            
            # Add to items list
            for d in dirs:
                items.append((f"📁 {d.name}", d, True, 0))
            
            for f in files:
                try:
                    size = f.stat().st_size
                    icon = _get_file_icon(f)
                    items.append((f"{icon} {f.name}", f, False, size))
                except:
                    items.append((f"📄 {f.name}", f, False, 0))
            
        except PermissionError:
            console.print("[red]Permission denied accessing this directory.[/red]")
            if current_dir.parent != current_dir:
                current_dir = current_dir.parent
                continue
            else:
                return None
        
        if not items:
            console.print("[yellow]Directory is empty.[/yellow]")
            if not Confirm.ask("Go to parent directory?"):
                return None
            current_dir = current_dir.parent
            continue
        
        # Create display table
        table = Table(show_header=True, header_style="bold blue", box=box.MINIMAL)
        table.add_column("#", style="cyan", width=4)
        table.add_column("Name", style="white")
        table.add_column("Size", justify="right", style="yellow", width=12)
        table.add_column("Selected", justify="center", style="green", width=8)
        
        for i, (display_name, path, is_dir, size) in enumerate(items, 1):
            size_str = "" if is_dir else _format_file_size(size)
            selected_mark = "✓" if str(path) in [str(Path(f)) for f in selected_files] else ""
            
            table.add_row(str(i), display_name, size_str, selected_mark)
        
        console.print(table)
        
        # Show current selection if multi-select
        if multi_select and selected_files:
            console.print(f"\n[green]Selected files ({len(selected_files)}):[/green]")
            for sf in selected_files[:5]:  # Show first 5
                console.print(f"  • {sf}")
            if len(selected_files) > 5:
                console.print(f"  ... and {len(selected_files) - 5} more")
        
        # Show instructions
        instructions = []
        if multi_select:
            instructions.extend([
                "Enter number to toggle selection",
                "'done' to finish",
                "'clear' to clear selection"
            ])
        else:
            instructions.append("Enter number to select file")
        instructions.extend(["'q' to quit", "'.' for current directory"])
        
        console.print(f"\n[dim]{' | '.join(instructions)}[/dim]")
        
        # Get user input
        try:
            choice = Prompt.ask("Choice").strip().lower()
            
            if choice in ['q', 'quit', 'exit']:
                return selected_files if multi_select and selected_files else None
            
            if choice == '.':
                return [str(current_dir)]
            
            if multi_select:
                if choice == 'done':
                    return selected_files if selected_files else None
                elif choice == 'clear':
                    selected_files = []
                    continue
            
            # Try to parse as number
            try:
                index = int(choice) - 1
                if 0 <= index < len(items):
                    display_name, path, is_dir, size = items[index]
                    
                    if is_dir:
                        # Navigate to directory
                        current_dir = path.resolve()
                    else:
                        # Select file
                        file_path = str(path)
                        if multi_select:
                            if file_path in selected_files:
                                selected_files.remove(file_path)
                            else:
                                selected_files.append(file_path)
                        else:
                            return file_path
                else:
                    console.print(f"[red]Invalid choice. Enter 1-{len(items)}[/red]")
                    console.input("Press Enter to continue...")
            except ValueError:
                console.print(f"[red]Invalid input: {choice}[/red]")
                console.input("Press Enter to continue...")
                
        except KeyboardInterrupt:
            return selected_files if multi_select and selected_files else None


def _fuzzy_match(pattern: str, text: str) -> bool:
    """Simple fuzzy matching algorithm."""
    pattern_idx = 0
    for char in text:
        if pattern_idx < len(pattern) and char == pattern[pattern_idx]:
            pattern_idx += 1
    return pattern_idx == len(pattern)


def _parse_selection(selection: str, max_num: int) -> List[int]:
    """Parse selection string like '1,3,5' or '1-3' into list of indices."""
    indices = []
    
    for part in selection.split(','):
        part = part.strip()
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                start_idx = int(start.strip())
                end_idx = int(end.strip())
                indices.extend(range(start_idx, end_idx + 1))
            except ValueError:
                return []
        else:
            try:
                indices.append(int(part))
            except ValueError:
                return []
    
    # Filter valid indices
    return [i for i in indices if 1 <= i <= max_num]


def _format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format."""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"


def _get_file_icon(file_path: Path) -> str:
    """Get emoji icon for file type."""
    suffix = file_path.suffix.lower()
    
    icon_map = {
        '.py': '🐍', '.js': '🟨', '.ts': '🔷', '.html': '🌐', '.css': '🎨',
        '.json': '📋', '.yaml': '📝', '.yml': '📝', '.xml': '📄', '.txt': '📝',
        '.md': '📖', '.rst': '📚', '.pdf': '📕', '.doc': '📘', '.docx': '📘',
        '.xls': '📊', '.xlsx': '📊', '.csv': '📈', '.sql': '🗃️',
        '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🎭', '.svg': '🎨',
        '.mp3': '🎵', '.wav': '🎵', '.mp4': '🎬', '.avi': '🎬',
        '.zip': '📦', '.tar': '📦', '.gz': '📦', '.rar': '📦',
        '.exe': '⚙️', '.msi': '⚙️', '.deb': '📦', '.rpm': '📦',
        '.log': '📜', '.conf': '⚙️', '.ini': '⚙️', '.cfg': '⚙️'
    }
    
    return icon_map.get(suffix, '📄')


def _get_admin_token(username: str, password: str) -> Optional[str]:
    """Get admin token using Keycloak ROPC flow with login-client.

    Caches the token in ~/.adept-agentic/cache/admin_token.json for reuse
    within the token's TTL.
    """
    import requests

    # Check cached token first
    cache_file = CACHE_DIR / "admin_token.json"
    try:
        if cache_file.exists():
            with open(cache_file) as f:
                cached = json.load(f)
            # Check if cached token is for the same user and not expired
            if (cached.get("username") == username
                    and cached.get("expires_at", 0) > time.time() + 30):
                return cached["access_token"]
    except Exception:
        pass  # Cache read failure is non-fatal

    keycloak_url = os.getenv('KEYCLOAK_URL', 'http://localhost:8180')
    realm = os.getenv('KEYCLOAK_REALM', 'master')
    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"

    try:
        response = requests.post(token_url, data={
            'client_id': 'login-client',
            'username': username,
            'password': password,
            'grant_type': 'password',
        }, timeout=10)
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data['access_token']

        # Cache the token
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            expires_in = token_data.get('expires_in', 300)
            with open(cache_file, 'w') as f:
                json.dump({
                    "username": username,
                    "access_token": access_token,
                    "expires_at": time.time() + expires_in,
                }, f)
            cache_file.chmod(0o600)
        except Exception:
            pass  # Cache write failure is non-fatal

        return access_token
    except Exception as e:
        console.print(f"[yellow]Admin authentication failed: {e}[/yellow]")
        return None


@click.group()
def cli():
    """Agentic Framework CLI - Interactive scientific AI workflows."""
    pass


# Add authentication commands
try:
    from .auth_commands import auth_group
    cli.add_command(auth_group)
except ImportError:
    try:
        # Fallback for direct script execution
        from auth_commands import auth_group
        cli.add_command(auth_group)
    except ImportError:
        pass  # Auth commands not available


# Add A2A (Agent-to-Agent) federation commands
try:
    from .a2a_commands import a2a_group
    cli.add_command(a2a_group)
except ImportError:
    try:
        # Fallback for direct script execution
        from a2a_commands import a2a_group
        cli.add_command(a2a_group)
    except ImportError:
        pass  # A2A commands not available


@cli.command()
@click.option("--session", "-s", help="Session name for conversation continuity")
@click.option("--model", "-m", help="Model to use for chat")
@click.option("--stream/--no-stream", default=None, help="Enable/disable streaming")
def chat(session: Optional[str], model: Optional[str], stream: Optional[bool]):
    """Start interactive chat with scientific AI agent."""
    
    app = AgenticCLI()
    
    if not app._initialize_client():
        sys.exit(1)
    
    # Override config with command line options
    if model:
        app.config["model"] = model
    if stream is not None:
        app.config["stream"] = stream
    
    # Set up session
    if session:
        app.current_session = session
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        app.current_session = f"{app.config['default_session_prefix']}-{timestamp}"
    
    _print_panel(
        f"Model:     {app.config['model']}\n"
        f"Session:   {app.current_session}\n"
        f"Streaming: {'enabled' if app.config['stream'] else 'disabled'}",
        title="Agentic Framework Chat",
    )
    click.echo("Type 'help' for commands, 'exit' to quit, Ctrl+C to interrupt")

    # Main chat loop
    asyncio.run(_chat_loop(app))


async def _chat_loop(app: AgenticCLI):
    """Main interactive chat loop."""

    while True:
        try:
            # Get user input
            user_input = input("\nYou: ").strip()

            if not user_input:
                continue

            # Handle special commands
            if user_input.lower() in ['exit', 'quit']:
                if app.config.get("auto_save_sessions", True):
                    _save_session(app)

                # Shutdown background manager
                if app.background_manager:
                    await app.background_manager.shutdown()

                # Cleanup keyboard handling
                if KEYBOARD_SUPPORT:
                    cleanup_keyboard_handling()

                click.echo("Goodbye.")
                break
            elif user_input.lower() == 'help':
                _show_help()
                continue
            elif user_input.lower() == 'save':
                _save_session(app)
                continue
            elif user_input.lower() == 'clear':
                app.session_history.clear()
                click.echo("History cleared.")
                continue
            elif user_input.startswith('/bg '):
                # Handle background process commands
                await _handle_background_command(app, user_input[4:])
                continue
            elif user_input == '/bg':
                # Show background processes
                if app.background_manager:
                    app.background_manager.show_processes_table()
                else:
                    click.echo("Background process support not available", err=True)
                continue

            # Add user message to history
            app.session_history.append({"role": "user", "content": user_input})

            # Get response
            if app.config["stream"]:
                await _handle_streaming_response(app, user_input)
            else:
                await _handle_single_response(app, user_input)

        except (KeyboardInterrupt, EOFError):
            click.echo("\nInterrupted. Type 'exit' to quit.")
            continue
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            continue


async def _handle_streaming_response(app: AgenticCLI, user_input: str):
    """Handle streaming response using Response API with plain text output."""

    try:
        stream = app.client.responses.completions.create(
            model=app.config["model"],
            messages=app.session_history,
            session_id=app.current_session,
            mcp_session_id=f"mcp-{app.current_session}",
            stream=True
        )

        click.echo("\nAssistant: ", nl=False)
        assistant_message = ""
        for chunk in stream:
            choices = chunk.get("choices", []) if isinstance(chunk, dict) else getattr(chunk, "choices", [])
            if choices:
                first = choices[0]
                delta = first.get("delta", {}) if isinstance(first, dict) else getattr(first, "delta", {})
                content = delta.get("content") if isinstance(delta, dict) else getattr(delta, "content", None)
                if content:
                    print(content, end="", flush=True)
                    assistant_message += content
        print()  # newline after stream

        if assistant_message.strip():
            app.session_history.append({"role": "assistant", "content": assistant_message})

    except Exception as e:
        click.echo(f"\nError: {e}", err=True)


async def _handle_single_response(app: AgenticCLI, user_input: str):
    """Handle single (non-streaming) response using Response API."""

    try:
        response = app.client.responses.completions.create(
            model=app.config["model"],
            messages=app.session_history,
            session_id=app.current_session,
            mcp_session_id=f"mcp-{app.current_session}",
            stream=False
        )

        choices = response.get("choices", []) if isinstance(response, dict) else getattr(response, "choices", [])
        if choices:
            first = choices[0]
            message = first.get("message", {}) if isinstance(first, dict) else getattr(first, "message", {})
            content = message.get("content", "") if isinstance(message, dict) else getattr(message, "content", "")
            if content.strip() and _get_active_config().get("rich_markdown", False):
                click.echo()
                _print_markdown(content)
            else:
                click.echo(f"\nAssistant: {content}")
            app.session_history.append({"role": "assistant", "content": content})
        else:
            click.echo("\nAssistant: (no response)")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)


async def _handle_background_command(app: AgenticCLI, command: str):
    """Handle background process commands."""
    if not app.background_manager:
        click.echo("Background process support not available", err=True)
        return

    parts = command.strip().split()
    if not parts:
        app.background_manager.show_processes_table()
        return

    cmd = parts[0].lower()

    if cmd == 'run':
        # /bg run "command to execute in background" [--name process_name]
        if len(parts) < 2:
            click.echo("Usage: /bg run \"command\" [--name process_name]", err=True)
            return

        # Parse command and options
        bg_command = ' '.join(parts[1:])
        process_name = None

        if '--name' in parts:
            name_idx = parts.index('--name')
            if name_idx + 1 < len(parts):
                process_name = parts[name_idx + 1]
                # Remove --name and process_name from command
                parts_filtered = parts[1:name_idx] + parts[name_idx + 2:]
                bg_command = ' '.join(parts_filtered)

        # Remove quotes if present
        if bg_command.startswith('"') and bg_command.endswith('"'):
            bg_command = bg_command[1:-1]
        elif bg_command.startswith("'") and bg_command.endswith("'"):
            bg_command = bg_command[1:-1]

        # Create and start process
        process_id = app.background_manager.create_process(
            command=bg_command,
            name=process_name,
            session_id=app.current_session,
            model=app.config.get("model")
        )

        await app.background_manager.start_process(process_id, app.client)

    elif cmd == 'list':
        # /bg list [--all]
        show_all = '--all' in parts
        app.background_manager.show_processes_table(show_all)

    elif cmd == 'show' or cmd == 'logs':
        # /bg show <process_id> [--follow] [--tail N]
        if len(parts) < 2:
            click.echo("Usage: /bg show <process_id> [--follow] [--tail N]", err=True)
            return

        process_id = parts[1]
        follow = '--follow' in parts
        tail = 20

        if '--tail' in parts:
            tail_idx = parts.index('--tail')
            if tail_idx + 1 < len(parts):
                try:
                    tail = int(parts[tail_idx + 1])
                except ValueError:
                    click.echo("Invalid tail number", err=True)
                    return

        app.background_manager.show_process_output(process_id, tail=tail, follow=follow)

    elif cmd == 'cancel' or cmd == 'kill':
        # /bg cancel <process_id>
        if len(parts) < 2:
            click.echo("Usage: /bg cancel <process_id>", err=True)
            return

        process_id = parts[1]
        await app.background_manager.cancel_process(process_id)

    elif cmd == 'cleanup':
        # /bg cleanup [--days N]
        days = 7
        if '--days' in parts:
            days_idx = parts.index('--days')
            if days_idx + 1 < len(parts):
                try:
                    days = int(parts[days_idx + 1])
                except ValueError:
                    click.echo("Invalid days number", err=True)
                    return

        app.background_manager.cleanup_old_processes(days)

    else:
        click.echo(f"Unknown background command: {cmd}", err=True)
        click.echo("Available commands: run, list, show, cancel, cleanup")


def _show_help():
    """Show help information."""
    cfg = _get_active_config()
    if cfg.get("rich_tables", False) and cfg.get("color_output", False):
        table = Table(title="Commands", box=box.SIMPLE)
        table.add_column("Command", style="cyan")
        table.add_column("Description")
        table.add_row("help", "Show this help")
        table.add_row("clear", "Clear conversation history")
        table.add_row("save", "Save current session")
        table.add_row("exit/quit", "Exit chat (auto-saves if enabled)")
        table.add_row("/bg", "Show running background processes")
        table.add_row('/bg run "cmd"', "Run command in background")
        table.add_row("/bg list [--all]", "List processes")
        table.add_row("/bg show <id>", "Show process output")
        table.add_row("/bg cancel <id>", "Cancel running process")
        table.add_row("/bg cleanup", "Clean up old processes")
        console.print(table)
        console.print(
            "\nAsk the AI about: protein analysis, compound research,\n"
            "data analysis, literature review, research workflows"
        )
    else:
        click.echo("""
Commands:
  help       - Show this help
  clear      - Clear conversation history
  save       - Save current session
  exit/quit  - Exit chat (auto-saves if enabled)

Background Process Commands:
  /bg                          - Show running background processes
  /bg run "command"            - Run command in background
  /bg run "command" --name N   - Run with custom name
  /bg list [--all]             - List processes
  /bg show <id> [--follow]     - Show process output
  /bg cancel <id>              - Cancel running process
  /bg cleanup                  - Clean up old processes

Ask the AI about:
  - Protein analysis (BLAST, UniProt, structure prediction)
  - Compound research (PubChem, molecular properties)
  - Data analysis (Python/R execution, visualization)
  - Literature review (paper search and synthesis)
  - Research workflows (multi-step analysis pipelines)
""")


def _save_session(app: AgenticCLI):
    """Save current session to file."""
    try:
        session_file = SESSIONS_DIR / f"{app.current_session}.json"
        session_data = {
            "session_id": app.current_session,
            "created": datetime.now().isoformat(),
            "model": app.config["model"],
            "history": app.session_history
        }

        with open(session_file, 'w') as f:
            json.dump(session_data, f, indent=2)

        click.echo(f"Session saved to {session_file}")

    except Exception as e:
        click.echo(f"Error saving session: {e}", err=True)


@cli.group()
def sessions():
    """Manage chat sessions."""
    pass


@sessions.command("list")
def sessions_list():
    """List saved sessions."""
    try:
        session_files = list(SESSIONS_DIR.glob("*.json"))
        
        if not session_files:
            console.print("[dim]No saved sessions found.[/dim]")
            return
            
        table = Table(title="Saved Sessions")
        table.add_column("Session ID", style="cyan")
        table.add_column("Created", style="green")
        table.add_column("Messages", style="yellow")
        table.add_column("Model", style="blue")
        
        for session_file in sorted(session_files, key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                with open(session_file) as f:
                    data = json.load(f)
                
                table.add_row(
                    data.get("session_id", session_file.stem),
                    data.get("created", "Unknown")[:19],
                    str(len(data.get("history", []))),
                    data.get("model", "Unknown")
                )
            except Exception:
                continue
                
        console.print(table)
        
    except Exception as e:
        console.print(f"[red]Error listing sessions: {e}[/red]")


@sessions.command("load")  
@click.argument("session_id")
def sessions_load(session_id: str):
    """Load a saved session for continuation."""
    try:
        session_file = SESSIONS_DIR / f"{session_id}.json"
        
        if not session_file.exists():
            console.print(f"[red]Session '{session_id}' not found.[/red]")
            return
            
        with open(session_file) as f:
            session_data = json.load(f)
        
        console.print(f"[green]Session '{session_id}' loaded with {len(session_data['history'])} messages.[/green]")
        console.print(f"Use: [bold]agentic chat --session {session_id}[/bold] to continue")
        
    except Exception as e:
        console.print(f"[red]Error loading session: {e}[/red]")


@sessions.command("attach")
@click.argument("thread_id")
@click.option("--model", "-m", default=None, help="Model override")
@click.option("--tail", "-n", default=10, help="Number of recent messages to show (default: 10)")
def sessions_attach(thread_id: str, model: Optional[str], tail: int):
    """Attach to an existing ADEPT thread and continue interactively.

    THREAD_ID is the portable session identifier from any ADEPT client
    (Streamlit, perform-demo, Claude adaptor, or another CLI session).
    """
    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)

    if model:
        app.config["model"] = model

    try:
        messages_resp = app.client.beta.threads.messages.list(thread_id=thread_id)
        messages_data = messages_resp.get("data", [])
    except Exception as e:
        console.print(f"[red]Failed to retrieve thread {thread_id}: {e}[/red]")
        sys.exit(1)

    if not messages_data:
        console.print(f"[yellow]Thread {thread_id} exists but has no messages yet.[/yellow]")
    else:
        recent = messages_data[:tail]
        recent.reverse()

        console.print(f"\n[bold]Session history[/bold] (last {len(recent)} of {len(messages_data)} messages):\n")
        for msg in recent:
            role = msg.get("role", "?")
            content_blocks = msg.get("content", [])
            text = ""
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", {}).get("value", "")
                    break
                elif isinstance(block, str):
                    text = block
                    break
            preview = text[:200] + ("..." if len(text) > 200 else "")
            style = "cyan" if role == "user" else "green"
            console.print(f"  [{style}]{role}:[/{style}] {preview}")
        console.print()

    app.current_session = thread_id
    app.session_history = []
    for msg in reversed(messages_data):
        role = msg.get("role", "user")
        content_blocks = msg.get("content", [])
        text = ""
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", {}).get("value", "")
                break
            elif isinstance(block, str):
                text = block
                break
        if text:
            app.session_history.append({"role": role, "content": text})

    _print_panel(
        f"Thread:    {thread_id}\n"
        f"Model:     {app.config['model']}\n"
        f"Messages:  {len(messages_data)} loaded\n"
        f"Streaming: {'enabled' if app.config['stream'] else 'disabled'}",
        title="Session Attached",
    )
    click.echo("Type 'help' for commands, 'exit' to quit, Ctrl+C to interrupt")
    asyncio.run(_chat_loop(app))


@cli.group()
def config():
    """Manage CLI configuration."""
    pass


@config.command("show")
@click.option("--verbose", "-v", is_flag=True, help="Show directory info and disk usage")
def config_show(verbose):
    """Show current configuration."""
    app = AgenticCLI()

    table = Table(title="Current Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    for key, value in app.config.items():
        if key == "api_key" and value:
            value = f"{value[:8]}..." if len(value) > 8 else "***"
        table.add_row(key, str(value))

    console.print(table)

    if verbose:
        env_info = app.config_manager.get_env_info()

        console.print("\n[bold]Directory Information[/bold]")
        dir_table = Table()
        dir_table.add_column("Directory", style="cyan")
        dir_table.add_column("Files", style="green")
        for dir_name, count in env_info["directories"].items():
            dir_table.add_row(dir_name, str(count))
        console.print(dir_table)

        console.print("\n[bold]Disk Usage[/bold]")
        for key, size in env_info["disk_usage"].items():
            console.print(f"  {key}: {size:,} bytes")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Set configuration value."""
    app = AgenticCLI()

    # Type conversion for known numeric values
    if key in ["max_tokens", "session_history_limit", "request_timeout",
                "max_concurrent_uploads", "vectorstore_chunk_size",
                "vectorstore_chunk_overlap"]:
        try:
            value = int(value)
        except ValueError:
            console.print(f"[yellow]Expected an integer for {key}[/yellow]")
            return
    elif key in ["temperature"]:
        try:
            float_val = float(value)
            if float_val < 0 or float_val > 2:
                console.print("[yellow]Temperature should be between 0 and 2[/yellow]")
                return
            value = float_val
        except ValueError:
            console.print(f"[yellow]Expected a number for {key}[/yellow]")
            return
    elif key in ["auto_save", "stream", "auto_cleanup_temp", "compress_uploads",
                 "enable_local_vectorstore", "log_api_calls", "log_file_operations",
                 "color_output", "show_progress_bars", "confirm_destructive_actions",
                 "auto_attach_context", "enable_request_cache"]:
        if value.lower() in ["true", "false"]:
            value = value.lower() == "true"

    app.config_manager.update_config(key, value)
    console.print(f"[green]Configuration updated: {key} = {value}[/green]")


@config.command("reset")
def config_reset():
    """Reset configuration to defaults."""
    if Confirm.ask("Are you sure you want to reset all configuration to defaults?"):
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
        # Reinitialize with defaults
        app = AgenticCLI()
        console.print("[green]Configuration reset to defaults.[/green]")


@config.command("init")
def config_init():
    """Initialize CLI configuration interactively."""
    console.print("[bold]Agentic Framework CLI Setup[/bold]\n")

    gateway_url = Prompt.ask("Gateway URL", default="https://api.agentic.local")
    model = Prompt.ask("Model", default="agentic-framework:scientific-agent-v1")

    config_updates = {
        "gateway_url": gateway_url,
        "model": model,
    }

    if Confirm.ask("Configure API key?", default=False):
        api_key = Prompt.ask("API Key")
        config_updates["api_key"] = api_key

    if Confirm.ask("Configure advanced settings?", default=False):
        max_tokens = Prompt.ask("Max tokens", default="2000")
        temperature = Prompt.ask("Temperature", default="0.7")
        config_updates["max_tokens"] = int(max_tokens)
        config_updates["temperature"] = float(temperature)

    app = AgenticCLI()
    for k, v in config_updates.items():
        app.config_manager.update_config(k, v)

    console.print("[green]Configuration saved successfully.[/green]")


@config.command("auth")
@click.option("--token", default=None, help="Set API token directly")
def config_auth(token):
    """Authenticate with the gateway."""
    app = AgenticCLI()

    if token:
        app.config_manager.update_config("api_key", token)
        console.print("[green]API token configured.[/green]")
        return

    username = click.prompt("Username")
    password = click.prompt("Password")

    try:
        import requests
        keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
        realm = os.getenv("KEYCLOAK_REALM", "master")
        token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"

        response = requests.post(token_url, data={
            "client_id": "login-client",
            "username": username,
            "password": password,
            "grant_type": "password",
        }, timeout=10)
        response.raise_for_status()

        access_token = response.json()["access_token"]
        app.config_manager.update_config("api_key", access_token)
        console.print("[green]Authentication successful.[/green]")
    except Exception as e:
        console.print(f"[red]Authentication failed: {e}[/red]")


@config.command("clean")
@click.option("--cache", "clean_cache", is_flag=True, help="Clean cache files")
@click.option("--temp", "clean_temp", is_flag=True, help="Clean temp files")
@click.option("--logs", "clean_logs", is_flag=True, help="Clean log files")
@click.option("--all", "clean_all", is_flag=True, help="Clean everything")
def config_clean(clean_cache, clean_temp, clean_logs, clean_all):
    """Clean up cache, temp, and log files."""
    if not any([clean_cache, clean_temp, clean_logs, clean_all]):
        console.print("[yellow]Specify what to clean: --cache, --temp, --logs, or --all[/yellow]")
        return

    app = AgenticCLI()

    if clean_all or clean_cache:
        if Confirm.ask("Remove all cache files?"):
            for f in CACHE_DIR.iterdir():
                if f.is_file():
                    f.unlink()
                elif f.is_dir():
                    shutil.rmtree(f)
            console.print("[green]Cache cleaned.[/green]")

    if clean_all or clean_temp:
        if Confirm.ask("Remove all temp files?"):
            for f in TEMP_DIR.iterdir():
                if f.is_file():
                    f.unlink()
                elif f.is_dir():
                    shutil.rmtree(f)
            console.print("[green]Temp files cleaned.[/green]")

    if clean_all or clean_logs:
        if Confirm.ask("Remove all log files?"):
            for f in LOGS_DIR.glob("*.log*"):
                f.unlink()
            console.print("[green]Logs cleaned.[/green]")


@config.command("backup")
@click.option("--output", "-o", default=None, help="Output file path")
def config_backup(output):
    """Backup configuration to a tar.gz archive."""
    import tarfile

    if not output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"agentic_config_backup_{timestamp}.tar.gz"

    try:
        with tarfile.open(output, "w:gz") as tar:
            if CONFIG_DIR.exists():
                tar.add(CONFIG_DIR, arcname=".adept-agentic")
        console.print(f"[green]Configuration backed up to {output}[/green]")
    except Exception as e:
        console.print(f"[red]Backup failed: {e}[/red]")


@config.command("restore")
@click.argument("backup_file")
def config_restore(backup_file):
    """Restore configuration from a backup archive."""
    import tarfile

    backup_path = Path(backup_file)
    if not backup_path.exists():
        console.print(f"[red]Backup file not found: {backup_file}[/red]")
        raise SystemExit(1)

    if Confirm.ask(f"Restore configuration from {backup_file}? This will overwrite current config."):
        try:
            with tarfile.open(backup_file, "r:gz") as tar:
                tar.extractall(path=CONFIG_DIR.parent)
            console.print("[green]Configuration restored successfully.[/green]")
        except Exception as e:
            console.print(f"[red]Restore failed: {e}[/red]")
            raise SystemExit(1)


@config.command("doctor")
def config_doctor():
    """Run health checks on CLI configuration and connectivity."""
    console.print("[bold]Health Check[/bold]\n")

    app = AgenticCLI()

    # Check SDK
    if SDK_AVAILABLE:
        console.print("[green]✓[/green] SDK available")
    else:
        console.print("[red]✗[/red] SDK not available")

    # Check config directory
    if CONFIG_DIR.exists():
        console.print(f"[green]✓[/green] Config directory: {CONFIG_DIR}")
    else:
        console.print(f"[red]✗[/red] Config directory missing: {CONFIG_DIR}")

    # Check config file
    if CONFIG_FILE.exists():
        console.print("[green]✓[/green] Config file exists")
    else:
        console.print("[yellow]![/yellow] Config file missing (using defaults)")

    # Check gateway connectivity
    gateway_url = app.config.get("gateway_url", "")
    if gateway_url:
        try:
            import requests
            response = requests.get(f"{gateway_url}/v1/models", timeout=5)
            if response.status_code == 200:
                console.print(f"[green]✓[/green] Gateway reachable: {gateway_url}")
            else:
                console.print(f"[yellow]![/yellow] Gateway returned {response.status_code}: {gateway_url}")
        except Exception as e:
            console.print(f"[red]✗[/red] Gateway unreachable: {gateway_url} ({e})")

    # Check directories
    env_info = app.config_manager.get_env_info()
    console.print(f"\n[bold]Storage[/bold]")
    console.print(f"  Sessions: {env_info['directories']['sessions']} files")
    console.print(f"  Cache: {env_info['directories']['cache_files']} files ({env_info['disk_usage']['cache_size']:,} bytes)")
    console.print(f"  Uploads: {env_info['directories']['uploads']} files ({env_info['disk_usage']['uploads_size']:,} bytes)")


@config.command("bootstrap")
@click.option("--gateway-url", default=None, help="Gateway URL (auto-detected if omitted)")
@click.option("--keycloak-url", default=None, help="Keycloak URL (auto-detected if omitted)")
@click.option("--username", default=None, help="Username for authentication")
@click.option("--password", default=None, help="Password for authentication")
@click.option("--non-interactive", is_flag=True, help="Skip prompts, use defaults/env vars")
def config_bootstrap(gateway_url, keycloak_url, username, password, non_interactive):
    """Auto-detect environment, discover services, authenticate, and save a working config.

    Solves the common problem where the saved config has a Docker-internal URL
    (e.g. https://api.agentic.local) that is unreachable from the host machine.
    This command auto-discovers the correct gateway URL, verifies Keycloak
    reachability, obtains a fresh JWT token, and saves everything to config.
    """
    import requests as _requests

    click.echo("Agentic Framework CLI Bootstrap")
    click.echo("=" * 34)

    # ── Step 1: Detect environment ───────────────────────────────────────
    in_docker = Path("/.dockerenv").exists()
    env_label = "Docker container" if in_docker else "host machine"
    click.echo(f"[1/5] Detecting environment... {env_label}")

    # ── Step 2: Discover + test gateway URL ──────────────────────────────
    click.echo("[2/5] Discovering gateway... ", nl=False)
    discovered_gateway = None

    gateway_candidates = []
    if gateway_url:
        gateway_candidates.append(gateway_url)
    env_gw = os.getenv("AGENT_GATEWAY_URL")
    if env_gw:
        gateway_candidates.append(env_gw)
    if in_docker:
        gateway_candidates.extend([
            "https://api.agentic.local",
            "http://agent_gateway:8081/v1",
        ])
    else:
        gateway_candidates.extend([
            "http://localhost:8083",
            "https://api.agentic.local",
        ])

    for candidate in gateway_candidates:
        try:
            # Strip /v1 suffix for health probe
            probe_url = candidate.rstrip("/")
            if probe_url.endswith("/v1"):
                probe_url = probe_url[:-3]
            resp = _requests.get(
                f"{probe_url}/v1/models",
                timeout=3,
                verify=False,
            )
            # 200 = healthy, 401 = alive but needs auth — both mean reachable
            if resp.status_code in (200, 401, 403):
                discovered_gateway = candidate
                break
        except Exception:
            continue

    if discovered_gateway:
        click.echo(f"{discovered_gateway} (OK)")
    else:
        if not non_interactive:
            discovered_gateway = click.prompt(
                "Could not auto-detect gateway. Enter URL",
                default="http://localhost:8083",
            )
        else:
            click.echo("FAILED")
            click.echo(
                "Error: Could not reach any gateway URL. "
                "Ensure services are running (make start) or pass --gateway-url."
            )
            raise SystemExit(1)

    # ── Step 3: Discover + test Keycloak URL ─────────────────────────────
    click.echo("[3/5] Discovering Keycloak... ", nl=False)
    discovered_keycloak = None

    kc_candidates = []
    if keycloak_url:
        kc_candidates.append(keycloak_url)
    env_kc = os.getenv("KEYCLOAK_URL")
    if env_kc:
        kc_candidates.append(env_kc)
    if in_docker:
        kc_candidates.extend([
            "http://keycloak:8180",
            "http://localhost:8180",
        ])
    else:
        kc_candidates.extend([
            "http://localhost:8180",
            "http://keycloak:8180",
        ])

    realm = os.getenv("KEYCLOAK_REALM", "master")
    for candidate in kc_candidates:
        try:
            oidc_url = (
                f"{candidate.rstrip('/')}/realms/{realm}"
                f"/.well-known/openid-configuration"
            )
            resp = _requests.get(oidc_url, timeout=3, verify=False)
            if resp.status_code == 200:
                discovered_keycloak = candidate
                break
        except Exception:
            continue

    if discovered_keycloak:
        click.echo(f"{discovered_keycloak} (OK)")
    else:
        if not non_interactive:
            discovered_keycloak = click.prompt(
                "Could not auto-detect Keycloak. Enter URL",
                default="http://localhost:8180",
            )
        else:
            click.echo("FAILED")
            click.echo(
                "Warning: Keycloak not reachable. "
                "Authentication will be skipped."
            )

    # ── Step 4: Authenticate ─────────────────────────────────────────────
    click.echo("[4/5] Authenticating... ", nl=False)
    access_token = None

    if discovered_keycloak:
        auth_username = username
        auth_password = password

        if not auth_username:
            auth_username = os.getenv("AGENTIC_USERNAME", "notebook-user")
        if not auth_password:
            auth_password = os.getenv("AGENTIC_PASSWORD", "notebook-password")

        if not non_interactive and not username:
            auth_username = click.prompt("Username", default=auth_username)
        if not non_interactive and not password:
            auth_password = click.prompt("Password", default=auth_password, hide_input=True)

        token_url = (
            f"{discovered_keycloak.rstrip('/')}/realms/{realm}"
            f"/protocol/openid-connect/token"
        )
        try:
            resp = _requests.post(
                token_url,
                data={
                    "client_id": "login-client",
                    "username": auth_username,
                    "password": auth_password,
                    "grant_type": "password",
                },
                timeout=10,
                verify=False,
            )
            if resp.status_code == 200:
                access_token = resp.json().get("access_token")
                click.echo(f"{auth_username} (token obtained)")
            else:
                click.echo(f"FAILED (HTTP {resp.status_code})")
                detail = resp.json().get("error_description", resp.text[:120])
                click.echo(f"  Auth error: {detail}")
        except Exception as e:
            click.echo(f"FAILED ({e})")
    else:
        click.echo("skipped (no Keycloak)")

    # ── Step 5: Save config + print summary ──────────────────────────────
    click.echo("[5/5] Saving configuration... ", nl=False)

    app = AgenticCLI()
    app.config_manager.update_config("gateway_url", discovered_gateway)
    if access_token:
        app.config_manager.update_config("api_key", access_token)

    click.echo(str(CONFIG_FILE))

    click.echo("")
    click.echo("Bootstrap complete. Try:")
    click.echo("  agentic config doctor")
    click.echo("  agentic tools list")
    click.echo("  agentic chat")


@cli.command()
@click.option("--compare-langgraph", is_flag=True, help="Compare with LangGraph performance")
@click.option("--output", "-o", help="Output file for results")
def benchmark(compare_langgraph: bool, output: Optional[str]):
    """Run performance benchmarks."""
    
    console.print("[bold blue]🚀 Agentic Framework Benchmarks[/bold blue]")
    
    if not SDK_AVAILABLE:
        console.print("[red]SDK not available for benchmarking.[/red]")
        return
    
    console.print("[yellow]Benchmark implementation coming soon![/yellow]")
    console.print("Will test:")
    console.print("- Agent reuse performance (2-4x speedup expected)")
    console.print("- Session persistence benefits") 
    console.print("- Tool calling performance")
    console.print("- Concurrent session handling")
    
    if compare_langgraph:
        console.print("- Head-to-head comparison with LangGraph")


@cli.group(invoke_without_command=True)
@click.pass_context
def tools(ctx):
    """Manage and list scientific tools."""
    if ctx.invoked_subcommand is None:
        # Backward compat: bare `agentic tools` behaves like `agentic tools list`
        ctx.invoke(tools_list)


@tools.command("list")
@click.option("--username", envvar="ADMIN_USERNAME", default=None, help="Admin username (env: ADMIN_USERNAME)")
@click.option("--password", envvar="ADMIN_PASSWORD", default=None, help="Admin password (env: ADMIN_PASSWORD)")
def tools_list(username, password):
    """List available scientific tools.

    Requires admin role. Use --username/--password or set ADMIN_USERNAME/ADMIN_PASSWORD.
    Defaults to admin/admin if no credentials provided.
    """
    click.echo("Available Scientific Tools")

    if not SDK_AVAILABLE:
        click.echo("Error: SDK not available. Cannot fetch tool list.", err=True)
        return

    # Default to admin credentials for tool listing
    if not username:
        username = os.getenv("ADMIN_USERNAME", "admin")
    if not password:
        password = os.getenv("ADMIN_PASSWORD", "admin")

    token = _get_admin_token(username, password)
    if not token:
        click.echo("Warning: Admin authentication failed. Falling back to default auth (may fail).")

    app = AgenticCLI()
    if token:
        app.config["api_key"] = token
    if not app._initialize_client():
        return

    try:
        tools_response = app.client.agentic.tools.list()

        if isinstance(tools_response, dict) and "tools" in tools_response:
            fetched_tools = tools_response["tools"]
        elif isinstance(tools_response, list):
            fetched_tools = tools_response
        else:
            fetched_tools = []

        if not fetched_tools:
            click.echo("No tools found or tool listing not available.")
            _show_default_tool_categories()
            return

        # Display tools as plain text
        click.echo(f"{'Name':<35} {'Category':<20} {'Description'}")
        click.echo("-" * 80)
        for tool in fetched_tools[:20]:
            t_name = tool.get("name", "Unknown")
            t_cat = _categorize_tool(t_name)
            t_desc = tool.get("description", "No description available")[:40]
            click.echo(f"{t_name:<35} {t_cat:<20} {t_desc}")

        if len(fetched_tools) > 20:
            click.echo(f"\nShowing first 20 of {len(fetched_tools)} tools. Use API for full list.")

    except Exception as e:
        error_msg = str(e)
        if "403" in error_msg or "admin" in error_msg:
            click.echo("Error: Access denied. Tool listing requires admin role.", err=True)
            click.echo("  Use: agentic tools list --username admin --password admin", err=True)
        else:
            click.echo(f"Error fetching tools: {error_msg}", err=True)
        _show_default_tool_categories()


@tools.command("register")
@click.argument("name")
@click.option("--description", "-d", required=True, help="Tool description")
@click.option("--protocol", "-p", type=click.Choice(["http", "stdio", "mcp"]), default="http", help="Invocation protocol")
@click.option("--url", "-u", help="Endpoint URL (required for http and mcp protocols)")
@click.option("--command", "-c", help="Command to run (required for stdio protocol, comma-separated)")
@click.option("--tool-name", default=None, help="Tool name on remote MCP server (for mcp protocol)")
@click.option("--acl-groups", help="Comma-separated ACL groups (default: global access)")
@click.option("--acl-global/--no-acl-global", default=True, help="Allow global access (default: true)")
@click.option("--args-schema", help="JSON string of argument schema")
@click.option("--username", envvar="ADMIN_USERNAME", default=None, help="Admin username (env: ADMIN_USERNAME)")
@click.option("--password", envvar="ADMIN_PASSWORD", default=None, help="Admin password (env: ADMIN_PASSWORD)")
def tools_register(name, description, protocol, url, command, tool_name, acl_groups, acl_global, args_schema, username, password):
    """Register an external tool with the framework.

    Requires admin role. Use --username/--password or set ADMIN_USERNAME/ADMIN_PASSWORD.

    \b
    Examples:
      agentic tools register execute_opentrons_protocol \\
        -d "Execute an OpenTrons liquid handling protocol" \\
        -p mcp -u http://opentrons_mcp_server:9003 \\
        --tool-name execute_opentrons_protocol_tool \\
        --username admin --password admin

      agentic tools register my_http_tool \\
        -d "An HTTP tool" \\
        -p http -u http://my-service:8080/endpoint \\
        --username admin --password admin

      agentic tools register my_stdio_tool \\
        -d "Custom stdio tool" \\
        -p stdio -c "python3,-m,my_tool" \\
        --username admin --password admin
    """
    # Validate protocol-specific requirements
    if protocol == "http" and not url:
        click.echo("Error: --url is required for http protocol.", err=True)
        raise SystemExit(1)
    if protocol == "mcp" and not url:
        click.echo("Error: --url is required for mcp protocol.", err=True)
        raise SystemExit(1)
    if protocol == "stdio" and not command:
        click.echo("Error: --command is required for stdio protocol.", err=True)
        raise SystemExit(1)

    if not SDK_AVAILABLE:
        click.echo("Error: SDK not available. Cannot register tool.", err=True)
        raise SystemExit(1)

    # Build tool config matching ExternalToolManager schema
    tool_config = {
        "name": name,
        "description": description,
        "invocation": {
            "protocol": protocol,
        },
    }

    if protocol == "http":
        tool_config["invocation"]["connection"] = {"url": url}
    elif protocol == "mcp":
        tool_config["invocation"]["connection"] = {
            "url": url,
            "tool_name": tool_name or name,  # Default to registered name
        }
    elif protocol == "stdio":
        tool_config["invocation"]["command"] = command.split(",")

    # ACL configuration
    acl = {"global": acl_global}
    if acl_groups:
        acl["groups"] = [g.strip() for g in acl_groups.split(",")]
        acl["global"] = False  # Explicit groups override global
    tool_config["acl"] = acl

    # Optional args schema
    if args_schema:
        try:
            tool_config["args_schema"] = json.loads(args_schema)
        except json.JSONDecodeError as e:
            click.echo(f"Error: Invalid JSON in --args-schema: {e}", err=True)
            raise SystemExit(1)

    # Get admin token
    token = _get_admin_token(username, password) if username and password else None
    if not token:
        if username or password:
            click.echo("Error: Admin authentication failed. Check credentials.", err=True)
            raise SystemExit(1)
        click.echo("Warning: No admin credentials provided. Using default auth (may fail if not admin).")

    # Initialize client with admin token
    app = AgenticCLI()
    if token:
        app.config["api_key"] = token
    if not app._initialize_client():
        raise SystemExit(1)

    try:
        result = app.client.agentic.tools.register(tool_config)
        click.echo(f"Tool '{name}' registered.")
        if isinstance(result, dict) and result.get("message"):
            click.echo(result['message'])
        click.echo(f"Verify with: agentic tools list")
    except Exception as e:
        error_msg = str(e)
        if "403" in error_msg or "Forbidden" in error_msg:
            click.echo("Error: Access denied. Tool registration requires admin role.", err=True)
        elif "400" in error_msg:
            click.echo(f"Error: Invalid tool configuration: {error_msg}", err=True)
        else:
            click.echo(f"Error registering tool: {error_msg}", err=True)
        raise SystemExit(1)


@tools.command("delete")
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.option("--username", envvar="ADMIN_USERNAME", default=None, help="Admin username (env: ADMIN_USERNAME)")
@click.option("--password", envvar="ADMIN_PASSWORD", default=None, help="Admin password (env: ADMIN_PASSWORD)")
def tools_delete(name, yes, username, password):
    """Delete a registered external tool.

    Requires admin role. Use --username/--password or set ADMIN_USERNAME/ADMIN_PASSWORD.
    """
    if not SDK_AVAILABLE:
        click.echo("Error: SDK not available. Cannot delete tool.", err=True)
        raise SystemExit(1)

    if not yes:
        if not click.confirm(f"Delete tool '{name}'?"):
            click.echo("Cancelled.")
            return

    # Get admin token
    token = _get_admin_token(username, password) if username and password else None
    if not token:
        if username or password:
            click.echo("Error: Admin authentication failed. Check credentials.", err=True)
            raise SystemExit(1)
        click.echo("Warning: No admin credentials provided. Using default auth (may fail if not admin).")

    app = AgenticCLI()
    if token:
        app.config["api_key"] = token
    if not app._initialize_client():
        raise SystemExit(1)

    try:
        result = app.client.agentic.tools.delete(name)
        click.echo(f"Tool '{name}' deleted.")
        if isinstance(result, dict) and result.get("message"):
            click.echo(result['message'])
    except Exception as e:
        error_msg = str(e)
        if "403" in error_msg or "Forbidden" in error_msg:
            click.echo("Error: Access denied. Tool deletion requires admin role.", err=True)
        elif "404" in error_msg:
            click.echo(f"Error: Tool '{name}' not found.", err=True)
        else:
            click.echo(f"Error deleting tool: {error_msg}", err=True)
        raise SystemExit(1)


def _categorize_tool(tool_name: str) -> str:
    """Categorize a tool based on its name."""
    name = tool_name.lower()
    if any(x in name for x in ["blast", "uniprot", "protein", "sequence", "pdb"]):
        return "Bioinformatics"
    elif any(x in name for x in ["pubchem", "compound", "molecule", "chemical"]):
        return "Chemistry"
    elif any(x in name for x in ["python", "code", "execute", "plot", "data"]):
        return "Data Science"
    elif any(x in name for x in ["search", "paper", "literature", "arxiv"]):
        return "Research"
    elif any(x in name for x in ["web", "http", "url"]):
        return "Web"
    else:
        return "General"


def _show_default_tool_categories():
    """Show default tool categories when API is unavailable."""
    click.echo("Available tool categories:")
    click.echo("- Bioinformatics: BLAST, UniProt, protein analysis")
    click.echo("- Chemistry: PubChem, molecular properties")
    click.echo("- Data Science: Python/R execution, visualization")
    click.echo("- Research: Literature search, paper analysis")
    click.echo("- Web: HTTP requests, web scraping")
    click.echo("- General: File operations, utilities")


# ====================================================================================
# FILE MANAGEMENT COMMANDS
# ====================================================================================

@cli.group()
def files():
    """Manage files for AI workflows."""
    pass


@files.command("upload")
@click.argument("file_path", type=FilePickerPath(exists=True))
@click.option("--purpose", "-p", default="assistants", help="File purpose (assistants, fine-tune, etc.)")
@click.option("--description", "-d", help="Optional file description")
def files_upload(file_path: str, purpose: str, description: Optional[str]):
    """Upload a file for use in AI workflows."""
    
    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)
    
    file_path = Path(file_path)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task(f"Uploading {file_path.name}...", total=None)
            
            with open(file_path, "rb") as f:
                result = app.client.files.create(
                    file=f,
                    purpose=purpose,
                    **({"description": description} if description else {})
                )
            
        console.print(Panel.fit(
            f"✅ [bold green]File uploaded successfully[/bold green]\n"
            f"File ID: {result.get('id', 'N/A')}\n"
            f"Filename: {result.get('filename', file_path.name)}\n"
            f"Size: {result.get('bytes', 0):,} bytes\n"
            f"Purpose: {result.get('purpose', purpose)}",
            title="Upload Complete",
            border_style="green"
        ))
        
    except Exception as e:
        console.print(f"[red]❌ Upload failed: {e}[/red]")
        sys.exit(1)


@files.command("list")
@click.option("--limit", "-l", default=20, help="Number of files to show")
def files_list(limit: int):
    """List uploaded files."""
    
    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task("Fetching files...", total=None)
            result = app.client.files.list()
        
        files_data = result.get('data', [])
        
        if not files_data:
            console.print("[yellow]No files found.[/yellow]")
            return
        
        # Create table
        table = Table(title=f"📁 Files ({len(files_data)} total)")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Filename", style="white")
        table.add_column("Size", justify="right", style="yellow")
        table.add_column("Purpose", style="magenta")
        table.add_column("Created", style="dim")
        
        for file_info in files_data[:limit]:
            table.add_row(
                file_info.get('id', 'N/A')[:12] + '...',
                file_info.get('filename', 'Unknown'),
                f"{file_info.get('bytes', 0):,}",
                file_info.get('purpose', 'N/A'),
                datetime.fromtimestamp(file_info.get('created_at', 0)).strftime('%Y-%m-%d %H:%M') if file_info.get('created_at') else 'N/A'
            )
        
        console.print(table)
        
        if len(files_data) > limit:
            console.print(f"[dim]Showing {limit} of {len(files_data)} files. Use --limit to see more.[/dim]")
            
    except Exception as e:
        console.print(f"[red]❌ Failed to list files: {e}[/red]")
        sys.exit(1)


@files.command("download")
@click.argument("file_id")
@click.option("--output", "-o", help="Output filename (default: use original name)")
def files_download(file_id: str, output: Optional[str]):
    """Download a file by ID."""
    
    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task(f"Downloading file {file_id[:8]}...", total=None)
            
            # Get file metadata first
            file_info = app.client.files.retrieve(file_id)
            filename = output or file_info.get('filename', f"file_{file_id[:8]}")
            
            # Download file content
            response = app.client.http_client.get(f"/files/{file_id}/content")
            response.raise_for_status()
            
            # Save to disk
            with open(filename, 'wb') as f:
                f.write(response.content)
            
        console.print(Panel.fit(
            f"✅ [bold green]File downloaded successfully[/bold green]\n"
            f"Saved as: {filename}\n"
            f"Size: {len(response.content):,} bytes",
            title="Download Complete",
            border_style="green"
        ))
        
    except Exception as e:
        console.print(f"[red]❌ Download failed: {e}[/red]")
        sys.exit(1)


@files.command("delete")
@click.argument("file_id")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
def files_delete(file_id: str, force: bool):
    """Delete a file by ID."""
    
    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)
    
    try:
        # Get file info first
        file_info = app.client.files.retrieve(file_id)
        filename = file_info.get('filename', 'Unknown')
        
        if not force:
            if not Confirm.ask(f"Delete file '{filename}' ({file_id[:12]}...)?"):
                console.print("[yellow]Cancelled.[/yellow]")
                return
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task("Deleting file...", total=None)
            app.client.files.delete(file_id)
        
        console.print(f"✅ [bold green]File '{filename}' deleted successfully[/bold green]")
        
    except Exception as e:
        console.print(f"[red]❌ Delete failed: {e}[/red]")
        sys.exit(1)


@files.command("register-local")
@click.argument("file_path")
@click.option("--session-id", "-s", help="Session ID to register with (uses current if not provided)")
@click.option("--alias", "-a", help="Friendly name/alias for the file")
@click.option("--no-copy", is_flag=True, help="Don't copy file to session, just register reference")
def files_register_local(file_path: str, session_id: Optional[str], alias: Optional[str], no_copy: bool):
    """Register an existing file from the filesystem with the current session.

    This allows accessing files that were uploaded in different sessions
    or exist on the filesystem through other means.

    Example:
        agentic files register-local /app/data/uploaded_files/sessions/old_session/file-abc.pdf --alias report.pdf
    """

    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)

    try:
        import os

        # Check if file exists
        if not os.path.exists(file_path):
            console.print(f"[red]❌ File not found: {file_path}[/red]")
            sys.exit(1)

        # Get file info
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        display_name = alias or file_name

        console.print(f"📄 Registering file: [cyan]{display_name}[/cyan]")
        console.print(f"   Path: {file_path}")
        console.print(f"   Size: {file_size:,} bytes")
        if session_id:
            console.print(f"   Session: {session_id}")
        console.print(f"   Copy to session: {'Yes' if not no_copy else 'No'}")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task("Registering file...", total=None)

            result = app.client.files.register_local(
                file_path=file_path,
                session_id=session_id,
                alias=alias,
                copy_to_session=not no_copy
            )

        # Display result
        if result.get('status') == 'success':
            console.print(f"✅ [bold green]File registered successfully[/bold green]")
            console.print(f"   File ID: [cyan]{result.get('file_id')}[/cyan]")
            console.print(f"   Display name: {result.get('display_name')}")
            console.print(f"   Path: {result.get('path')}")
            if result.get('copied'):
                console.print(f"   [green]File copied to session directory[/green]")
            console.print(f"\n💡 {result.get('usage_hint', 'File is now available for processing')}")
        else:
            console.print(f"[red]❌ Registration failed: {result.get('message', 'Unknown error')}[/red]")
            sys.exit(1)

    except Exception as e:
        console.print(f"[red]❌ Registration failed: {e}[/red]")
        sys.exit(1)


# ====================================================================================
# ASSISTANTS API COMMANDS
# ====================================================================================

@cli.group()
def assistants():
    """Manage AI assistants."""
    pass


@assistants.command("create")
@click.option("--name", "-n", prompt=True, help="Assistant name")
@click.option("--instructions", "-i", prompt=True, help="System instructions for the assistant")
@click.option("--model", "-m", help="Model to use (default from config)")
@click.option("--tools", help="Comma-separated list of tools to enable")
def assistants_create(name: str, instructions: str, model: Optional[str], tools: Optional[str]):
    """Create a new AI assistant."""
    
    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)
    
    try:
        payload = {
            "name": name,
            "instructions": instructions,
            "model": model or app.config.get("model", "agentic-framework:scientific-agent-v1")
        }
        
        if tools:
            tool_list = [{"type": "function", "function": {"name": tool.strip()}} 
                        for tool in tools.split(",")]
            payload["tools"] = tool_list
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task("Creating assistant...", total=None)
            result = app.client.beta.assistants.create(**payload)
        
        console.print(Panel.fit(
            f"✅ [bold green]Assistant created successfully[/bold green]\n"
            f"ID: {result.get('id', 'N/A')}\n"
            f"Name: {result.get('name', name)}\n"
            f"Model: {result.get('model', 'N/A')}\n"
            f"Tools: {len(result.get('tools', []))}",
            title="Assistant Created",
            border_style="green"
        ))
        
    except Exception as e:
        console.print(f"[red]❌ Failed to create assistant: {e}[/red]")
        sys.exit(1)


@assistants.command("list")
@click.option("--limit", "-l", default=20, help="Number of assistants to show")
def assistants_list(limit: int):
    """List AI assistants."""
    
    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)
    
    try:
        with Progress(
            SpinnerColumn(), 
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task("Fetching assistants...", total=None)
            result = app.client.beta.assistants.list(limit=limit)
        
        assistants_data = result.get('data', [])
        
        if not assistants_data:
            console.print("[yellow]No assistants found.[/yellow]")
            return
        
        # Create table
        table = Table(title=f"🤖 Assistants ({len(assistants_data)} total)")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name", style="white")
        table.add_column("Model", style="yellow")
        table.add_column("Tools", justify="center", style="magenta")
        table.add_column("Created", style="dim")
        
        for assistant in assistants_data:
            table.add_row(
                assistant.get('id', 'N/A')[:12] + '...',
                assistant.get('name', 'Unnamed'),
                assistant.get('model', 'N/A'),
                str(len(assistant.get('tools', []))),
                datetime.fromtimestamp(assistant.get('created_at', 0)).strftime('%Y-%m-%d %H:%M') if assistant.get('created_at') else 'N/A'
            )
        
        console.print(table)
        
    except Exception as e:
        console.print(f"[red]❌ Failed to list assistants: {e}[/red]")
        sys.exit(1)


# ====================================================================================
# THREADS AND RUNS COMMANDS
# ====================================================================================

@cli.group()
def threads():
    """Manage conversation threads."""
    pass


@threads.command("create")
@click.option("--assistant", "-a", help="Assistant ID to use")
@click.option("--message", "-m", help="Initial message")
def threads_create(assistant: Optional[str], message: Optional[str]):
    """Create a new conversation thread."""
    
    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task("Creating thread...", total=None)
            thread = app.client.beta.threads.create()
        
        thread_id = thread.get('id')
        console.print(Panel.fit(
            f"✅ [bold green]Thread created successfully[/bold green]\n"
            f"Thread ID: {thread_id}",
            title="Thread Created",
            border_style="green"
        ))
        
        # Add initial message if provided
        if message:
            progress.add_task("Adding initial message...", total=None)
            app.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user", 
                content=message
            )
            console.print(f"✅ Added message: {message[:50]}...")
            
        # Start run if assistant provided
        if assistant and message:
            progress.add_task("Starting run...", total=None)
            run = app.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant
            )
            console.print(f"✅ Run started: {run.get('id')}")
        
    except Exception as e:
        console.print(f"[red]❌ Failed to create thread: {e}[/red]")
        sys.exit(1)


@threads.command("run")
@click.argument("thread_id")
@click.argument("assistant_id")
@click.option("--wait", "-w", is_flag=True, help="Wait for completion")
def threads_run(thread_id: str, assistant_id: str, wait: bool):
    """Run an assistant on a thread."""
    
    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Starting run...", total=None)
            run = app.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id
            )
            
            run_id = run.get('id')
            console.print(f"✅ Run started: {run_id}")
            
            if wait:
                progress.update(task, description="Waiting for completion...")
                
                while True:
                    run_status = app.client.beta.threads.runs.retrieve(
                        thread_id=thread_id,
                        run_id=run_id
                    )
                    
                    status = run_status.get('status')
                    if status in ['completed', 'failed', 'cancelled', 'expired']:
                        break
                        
                    progress.update(task, description=f"Status: {status}")
                    import time
                    time.sleep(2)
                
                console.print(f"✅ Run completed with status: {status}")
                
                # Show messages
                messages = app.client.beta.threads.messages.list(thread_id=thread_id)
                for msg in messages.get('data', [])[:3]:  # Show last 3 messages
                    role = msg.get('role', 'unknown')
                    content = msg.get('content', [{}])[0].get('text', {}).get('value', 'No content')
                    console.print(f"[bold]{role.title()}:[/bold] {content[:100]}...")
        
    except Exception as e:
        console.print(f"[red]❌ Failed to run thread: {e}[/red]")
        sys.exit(1)


# ====================================================================================
# UCS EXTENSIONS COMMANDS  
# ====================================================================================

@cli.group()
def agents():
    """UCS agent management commands."""
    pass


@agents.command("invoke")
@click.argument("input_text")
@click.option("--session", "-s", help="Session ID for context")
@click.option("--model", "-m", help="Model override")
def agents_invoke(input_text: str, session: Optional[str], model: Optional[str]):
    """Directly invoke UCS agent functionality."""
    
    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)
    
    try:
        payload = {"input": input_text}
        if session:
            payload["session_id"] = session
        if model:
            payload["model"] = model
            
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task("Invoking agent...", total=None)
            result = app.client.agentic.agents.invoke(payload)
        
        console.print(Panel.fit(
            f"🤖 [bold blue]Agent Response[/bold blue]\n"
            f"{result.get('response', 'No response')}\n"
            f"Session: {result.get('session_id', 'N/A')}",
            title="UCS Agent Result",
            border_style="blue"
        ))
        
    except Exception as e:
        console.print(f"[red]❌ Agent invoke failed: {e}[/red]")
        sys.exit(1)


@agents.command("sessions") 
@click.option("--active", "-a", is_flag=True, help="Show only active sessions")
def agents_sessions(active: bool):
    """List agent sessions."""
    
    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task("Fetching sessions...", total=None)
            result = app.client.agentic.sessions.list()
        
        sessions = result.get('sessions', [])
        if active:
            sessions = [s for s in sessions if s.get('status') == 'active']
        
        if not sessions:
            console.print("[yellow]No sessions found.[/yellow]")
            return
        
        table = Table(title=f"🔄 Agent Sessions ({len(sessions)} total)")
        table.add_column("Session ID", style="cyan")
        table.add_column("Status", style="green") 
        table.add_column("Model", style="yellow")
        table.add_column("Messages", justify="center", style="magenta")
        table.add_column("Last Active", style="dim")
        
        for session in sessions:
            table.add_row(
                session.get('session_id', 'N/A')[:16] + '...',
                session.get('status', 'unknown'),
                session.get('model', 'N/A'),
                str(session.get('message_count', 0)),
                session.get('last_active', 'N/A')
            )
        
        console.print(table)
        
    except Exception as e:
        console.print(f"[red]❌ Failed to list sessions: {e}[/red]")
        sys.exit(1)


# ====================================================================================
# ENHANCED CHAT WITH FILE ATTACHMENTS
# ====================================================================================

@cli.command("chat-plus")
@click.option("--session", "-s", help="Session name for conversation continuity")
@click.option("--model", "-m", help="Model to use for chat")
@click.option("--attach", "-a", multiple=True, type=FilePickerPath(exists=True), help="Attach files (supports @ navigation, can be used multiple times)")
def chat_plus(session: Optional[str], model: Optional[str], attach: tuple):
    """Enhanced chat with file attachment support."""

    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)

    # Set up session BEFORE file uploads so uploads are linked to session
    if session:
        app.current_session = session
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        app.current_session = f"{app.config['default_session_prefix']}-{timestamp}"

    # Override config
    if model:
        app.config["model"] = model

    mcp_session_id = f"mcp-{app.current_session}"

    # Process file attachments (with session_id for discoverability)
    attached_files = []
    if attach:
        click.echo(f"Uploading {len(attach)} file(s)...")

        for file_path in attach:
            try:
                with open(file_path, "rb") as f:
                    result = app.client.files.create(
                        file=f,
                        purpose="assistants",
                        session_id=mcp_session_id,
                    )
                attached_files.append({
                    'file_id': result.get('id'),
                    'filename': Path(file_path).name
                })
                click.echo(f"  Uploaded: {Path(file_path).name}")
            except Exception as e:
                click.echo(f"  Failed to upload {file_path}: {e}", err=True)

    banner_lines = (
        f"Model:          {app.config['model']}\n"
        f"Session:        {app.current_session}\n"
        f"Attached Files: {len(attached_files)}"
    )
    _print_panel(banner_lines, title="Agentic Framework Enhanced Chat")

    if attached_files:
        click.echo("Attached files:")
        for file_info in attached_files:
            click.echo(f"  {file_info['filename']} ({file_info['file_id'][:8]}...)")

    click.echo("Type 'help' for commands, 'exit' to quit, '/attach <file>' to add more files")

    # Start enhanced chat loop
    asyncio.run(_enhanced_chat_loop(app, attached_files))


async def _enhanced_chat_loop(app: AgenticCLI, attached_files: List[Dict]):
    """Enhanced chat loop with file attachment support."""

    while True:
        try:
            user_input = input("\nYou: ").strip()

            if not user_input:
                continue

            # Handle special commands
            if user_input.lower() in ['exit', 'quit', 'bye']:
                click.echo("Goodbye.")
                break
            elif user_input.lower() == 'help':
                _show_enhanced_help()
                continue
            elif user_input.lower() == 'clear':
                app.session_history.clear()
                click.echo("History cleared.")
                continue
            elif user_input.startswith('/attach '):
                file_path = user_input[8:].strip()

                # Handle @ navigation for file selection
                if file_path.startswith('@'):
                    try:
                        selected_files = interactive_file_picker(file_path[1:], multi_select=True)
                        if not selected_files:
                            click.echo("No files selected.")
                            continue

                        # Convert single file to list for consistency
                        if isinstance(selected_files, str):
                            selected_files = [selected_files]

                        # Attach all selected files
                        mcp_sid = f"mcp-{app.current_session}"
                        for file_path_item in selected_files:
                            try:
                                with open(file_path_item, "rb") as f:
                                    result = app.client.files.create(
                                        file=f,
                                        purpose="assistants",
                                        session_id=mcp_sid,
                                    )
                                attached_files.append({
                                    'file_id': result.get('id'),
                                    'filename': Path(file_path_item).name
                                })
                                click.echo(f"  Attached: {Path(file_path_item).name}")
                            except Exception as e:
                                click.echo(f"  Failed to attach {file_path_item}: {e}", err=True)
                    except KeyboardInterrupt:
                        click.echo("\nFile selection cancelled.")
                    except Exception as e:
                        click.echo(f"File picker error: {e}", err=True)
                else:
                    # Regular file path attachment
                    try:
                        mcp_sid = f"mcp-{app.current_session}"
                        with open(file_path, "rb") as f:
                            result = app.client.files.create(
                                file=f,
                                purpose="assistants",
                                session_id=mcp_sid,
                            )
                        attached_files.append({
                            'file_id': result.get('id'),
                            'filename': Path(file_path).name
                        })
                        click.echo(f"  Attached: {Path(file_path).name}")
                    except Exception as e:
                        click.echo(f"  Failed to attach {file_path}: {e}", err=True)
                continue
            elif user_input.startswith('/save'):
                _save_session(app)
                continue

            # Prepare message with file attachments
            messages = [{"role": "user", "content": user_input}]

            # Add file context if files are attached
            if attached_files:
                file_context = "Attached files: " + ", ".join([f['filename'] for f in attached_files])
                messages[0]["content"] = f"{user_input}\n\n{file_context}"

            # Send message
            if app.config["stream"]:
                await _handle_enhanced_streaming_response(app, messages, attached_files)
            else:
                await _handle_enhanced_single_response(app, messages, attached_files)

        except (KeyboardInterrupt, EOFError):
            click.echo("\nInterrupted. Type 'exit' to quit.")
        except Exception as e:
            click.echo(f"Error: {e}", err=True)


async def _handle_enhanced_streaming_response(app: AgenticCLI, messages: List[Dict], attached_files: List[Dict]):
    """Handle streaming response for enhanced chat."""

    try:
        stream = app.client.responses.completions.create(
            model=app.config["model"],
            messages=messages,
            stream=True,
            session_id=app.current_session,
            mcp_session_id=f"mcp-{app.current_session}"
        )

        click.echo("\nAssistant: ", nl=False)

        full_response = ""
        for chunk in stream:
            choices = chunk.get("choices", []) if isinstance(chunk, dict) else getattr(chunk, "choices", [])
            if choices:
                first = choices[0]
                delta = first.get("delta", {}) if isinstance(first, dict) else getattr(first, "delta", {})
                content = delta.get("content") if isinstance(delta, dict) else getattr(delta, "content", None)
                if content:
                    print(content, end="", flush=True)
                    full_response += content
        print()  # newline after stream

        # Store in conversation history
        if hasattr(app, 'conversation_history'):
            app.conversation_history.extend(messages)
            app.conversation_history.append({
                "role": "assistant",
                "content": full_response
            })

    except Exception as e:
        click.echo(f"\nError during streaming: {e}", err=True)


async def _handle_enhanced_single_response(app: AgenticCLI, messages: List[Dict], attached_files: List[Dict]):
    """Handle single response for enhanced chat."""

    try:
        response = app.client.responses.completions.create(
            model=app.config["model"],
            messages=messages,
            session_id=app.current_session,
            mcp_session_id=f"mcp-{app.current_session}"
        )

        choices = response.get("choices", []) if isinstance(response, dict) else getattr(response, "choices", [])
        if choices:
            first = choices[0]
            message = first.get("message", {}) if isinstance(first, dict) else getattr(first, "message", {})
            content = message.get("content", "") if isinstance(message, dict) else getattr(message, "content", "")
            if content.strip() and _get_active_config().get("rich_markdown", False):
                click.echo()
                _print_markdown(content)
            else:
                click.echo(f"\nAssistant: {content}")

            # Store in conversation history
            if hasattr(app, 'conversation_history'):
                app.conversation_history.extend(messages)
                app.conversation_history.append({
                    "role": "assistant",
                    "content": content
                })
        else:
            click.echo("\nAssistant: (no response)")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)


def _show_enhanced_help():
    """Show help for enhanced chat."""
    cfg = _get_active_config()
    if cfg.get("rich_tables", False) and cfg.get("color_output", False):
        table = Table(title="Enhanced Chat Commands", box=box.SIMPLE)
        table.add_column("Command", style="cyan")
        table.add_column("Description")
        table.add_row("help", "Show this help")
        table.add_row("clear", "Clear conversation history")
        table.add_row("exit/quit/bye", "Exit chat")
        table.add_row("/attach <path>", "Attach a file to the conversation")
        table.add_row("/attach @", "Interactive file picker (@ navigation)")
        table.add_row("/save", "Save current session")
        console.print(table)

        nav = Table(title="@ Navigation", box=box.SIMPLE)
        nav.add_column("Pattern", style="cyan")
        nav.add_column("Description")
        nav.add_row("@*.csv", "Pattern matching (find all CSV files)")
        nav.add_row("@data/", "Browse directory interactively")
        nav.add_row("@proj", "Fuzzy search for 'proj' in filenames")
        nav.add_row("@", "Browse current directory")
        console.print(nav)
    else:
        click.echo("""
Commands:
  help                 - Show this help
  clear                - Clear conversation history
  exit/quit/bye        - Exit chat

File Commands:
  /attach <file_path>  - Attach a file to the conversation
  /attach @            - Interactive file picker (@ navigation)
  /save                - Save current session

@ Navigation:
  @*.csv               - Pattern matching (find all CSV files)
  @data/               - Browse directory interactively
  @proj                - Fuzzy search for 'proj' in filenames
  @                    - Browse current directory

Tips:
  - Attached files are automatically processed by the AI
  - File context persists throughout the conversation
  - Multiple file attachments are supported with @ navigation
""")


# ====================================================================================
# BACKGROUND PROCESS COMMANDS
# ====================================================================================

@cli.group()
def bg():
    """Manage background processes."""
    pass


@bg.command("run")
@click.argument("command")
@click.option("--name", "-n", help="Process name")
@click.option("--session", "-s", help="Session ID to use")
@click.option("--model", "-m", help="Model to use")
def bg_run(command: str, name: Optional[str], session: Optional[str], model: Optional[str]):
    """Run a command in the background."""
    
    app = AgenticCLI()
    if not app._initialize_client():
        sys.exit(1)
    
    if not app.background_manager:
        console.print("[red]Background process support not available[/red]")
        sys.exit(1)
    
    async def run_bg():
        # Create and start process
        process_id = app.background_manager.create_process(
            command=command,
            name=name,
            session_id=session or f"bg-{int(time.time())}",
            model=model or app.config.get("model")
        )
        
        success = await app.background_manager.start_process(process_id, app.client)
        if success:
            console.print(f"[green]Process started with ID: {process_id}[/green]")
            console.print(f"[dim]Use 'agentic bg show {process_id}' to monitor progress[/dim]")
        else:
            sys.exit(1)
    
    asyncio.run(run_bg())


@bg.command("list")
@click.option("--all", "-a", is_flag=True, help="Show all processes")
def bg_list(all: bool):
    """List background processes."""
    
    app = AgenticCLI()
    if not app.background_manager:
        console.print("[red]Background process support not available[/red]")
        sys.exit(1)
    
    app.background_manager.show_processes_table(show_all=all)


@bg.command("show")
@click.argument("process_id")
@click.option("--follow", "-f", is_flag=True, help="Follow output in real-time")
@click.option("--tail", "-t", type=int, default=20, help="Number of lines to show")
def bg_show(process_id: str, follow: bool, tail: int):
    """Show process output."""
    
    app = AgenticCLI()
    if not app.background_manager:
        console.print("[red]Background process support not available[/red]")
        sys.exit(1)
    
    app.background_manager.show_process_output(process_id, tail=tail, follow=follow)


@bg.command("cancel")
@click.argument("process_id")
def bg_cancel(process_id: str):
    """Cancel a running process."""
    
    app = AgenticCLI()
    if not app.background_manager:
        console.print("[red]Background process support not available[/red]")
        sys.exit(1)
    
    async def cancel_bg():
        await app.background_manager.cancel_process(process_id)
    
    asyncio.run(cancel_bg())


@bg.command("cleanup")
@click.option("--days", "-d", type=int, default=7, help="Clean processes older than N days")
def bg_cleanup(days: int):
    """Clean up old completed processes."""
    
    app = AgenticCLI()
    if not app.background_manager:
        console.print("[red]Background process support not available[/red]")
        sys.exit(1)
    
    app.background_manager.cleanup_old_processes(days)


if __name__ == "__main__":
    cli()