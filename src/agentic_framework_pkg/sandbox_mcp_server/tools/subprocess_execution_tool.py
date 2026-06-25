"""
Simplified subprocess execution approach for code execution.

This is an alternative to Docker-in-Docker that executes code directly within 
the sandbox_mcp_server container using subprocess, with proper security controls.

Benefits:
- Files go directly to shared volume /app/data/uploaded_files
- No Docker-in-Docker complexity
- Faster execution (no container creation overhead)
- Simpler debugging

Security considerations:
- Process isolation with timeouts and resource limits
- Code execution restrictions
- File system access controls
"""

import os
import subprocess
import tempfile
import uuid
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import time
import signal
import resource
import shutil

from ...logger_config import get_logger
logger = get_logger(__name__)

# --- nsjail integration ---
NSJAIL_BINARY = "/usr/local/bin/nsjail"
NSJAIL_CONFIG = "/etc/nsjail/sandbox.cfg"
SANDBOX_USE_NSJAIL = os.getenv("SANDBOX_USE_NSJAIL", "auto").lower()


def _is_nsjail_available() -> bool:
    """Check if nsjail binary exists and is executable."""
    return os.path.isfile(NSJAIL_BINARY) and os.access(NSJAIL_BINARY, os.X_OK)


def _should_use_nsjail() -> bool:
    """Determine whether to use nsjail based on env var and availability."""
    if SANDBOX_USE_NSJAIL == "false":
        return False
    if SANDBOX_USE_NSJAIL == "true":
        if not _is_nsjail_available():
            logger.error("[NSJAIL] SANDBOX_USE_NSJAIL=true but nsjail binary not found")
            raise RuntimeError("nsjail required (SANDBOX_USE_NSJAIL=true) but binary not available")
        return True
    # auto mode: use if available, fallback silently
    available = _is_nsjail_available()
    if available:
        logger.info("[NSJAIL] nsjail available — using kernel-level syscall filtering")
    else:
        logger.info("[NSJAIL] nsjail not available — falling back to subprocess-only isolation")
    return available


def _build_nsjail_command(
    script_path: str,
    working_dir: str,
    env: Dict[str, str],
    timeout: int,
    python_bin: str = "/app/.venv/bin/python",
) -> Tuple[List[str], Dict[str, str]]:
    """Build the nsjail CLI command for sandboxed Python execution.

    Returns (cmd_list, env_for_nsjail_parent) — the parent env is minimal since
    nsjail manages the child environment via --env flags.
    """
    shared_upload_dir = os.getenv("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")

    cmd = [
        NSJAIL_BINARY,
        "--config", NSJAIL_CONFIG,
        "--time_limit", str(timeout),
        # Bind-mount the working directory as read-write
        "--bindmount", f"{working_dir}:/workspace",
        # Bind-mount the shared uploads volume (read-write) so user code can
        # save artifacts to /app/data/uploaded_files/ and have them persist
        # beyond the ephemeral jail lifetime for file registration + download.
        "--bindmount", f"{shared_upload_dir}:{shared_upload_dir}",
        # Bind-mount the script file (read-only)
        "--bindmount_ro", f"{script_path}:{script_path}",
    ]

    # Override UID mapping if SANDBOX_EXEC_USER is configured (Gurobi token server auth)
    exec_user = os.getenv("SANDBOX_EXEC_USER", "")
    if exec_user:
        import pwd
        try:
            pw = pwd.getpwnam(exec_user)
            cmd.extend(["--uid_mapping", f"{pw.pw_uid}:0:1"])
            cmd.extend(["--gid_mapping", f"{pw.pw_gid}:0:1"])
            # Bind-mount /etc/passwd so getpwuid resolves inside the jail
            cmd.extend(["--bindmount_ro", "/etc/passwd:/etc/passwd"])
        except KeyError:
            logger.warning(f"[NSJAIL] SANDBOX_EXEC_USER={exec_user} not in /etc/passwd")

    # Pass restricted env vars into the jail
    for key, value in env.items():
        cmd.extend(["--env", f"{key}={value}"])

    # Override CWD to the working directory
    cmd.extend(["--cwd", "/workspace"])

    # The command to execute inside the jail
    cmd.append("--")
    cmd.append(python_bin)
    cmd.append(script_path)

    # Parent process env — nsjail itself needs minimal env
    parent_env = {"PATH": "/usr/local/bin:/usr/bin:/bin"}

    return cmd, parent_env

# Configurable timeout settings (same as in code_execution_tool.py)
def _env_int(key: str, default: int) -> int:
    val = os.getenv(key, str(default)).split("#")[0].strip()
    return int(val) if val else default

DEFAULT_TIMEOUT = _env_int("SANDBOX_DEFAULT_TIMEOUT", 30)
MAX_TIMEOUT = _env_int("SANDBOX_MAX_TIMEOUT", 300)
DOWNLOAD_TIMEOUT = _env_int("SANDBOX_DOWNLOAD_TIMEOUT", 120)

# Concurrency control: limit concurrent subprocess executions to prevent memory exhaustion.
# With a 10GB container and ~500MB-1GB per subprocess, 5 concurrent is a safe default.
MAX_CONCURRENT_EXECUTIONS = int(os.getenv("SANDBOX_MAX_CONCURRENT_EXECUTIONS", "5"))
_subprocess_semaphore: Optional[asyncio.Semaphore] = None


def _get_subprocess_semaphore() -> asyncio.Semaphore:
    """Lazy-init module-level semaphore (must be created inside an event loop)."""
    global _subprocess_semaphore
    if _subprocess_semaphore is None:
        _subprocess_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXECUTIONS)
        logger.info(f"[CONCURRENCY] Initialized subprocess semaphore: max_concurrent={MAX_CONCURRENT_EXECUTIONS}")
    return _subprocess_semaphore

import re

# Pre-compiled pattern matching internal framework log lines that leak into
# subprocess stdout/stderr via the preexec_fn (_set_resource_limits).  These
# lines carry zero value for the LLM and waste tokens.
_FRAMEWORK_LOG_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ - "
    r"agentic_framework_pkg\.sandbox_mcp_server\."
)


def _strip_framework_log_noise(text: str) -> str:
    """Remove internal framework log lines from subprocess output.

    Lines matching the ``agentic_framework_pkg.sandbox_mcp_server.*`` logger
    pattern (e.g. ``Set subprocess memory limit to 30GB``) are stripped so
    that only actual program output is returned to the orchestration layer.
    """
    if not text:
        return text
    return "\n".join(
        line for line in text.splitlines()
        if not _FRAMEWORK_LOG_PATTERN.match(line)
    ).strip()


class SubprocessCodeExecutor:
    """Simplified code executor using subprocess instead of Docker-in-Docker."""
    
    def __init__(self, 
                 shared_volume_path: str = "/app/data/uploaded_files",
                 execution_timeout: int = 30,
                 memory_limit_mb: int = 512,
                 session_id: Optional[str] = None,
                 use_session_isolation: bool = True):
        self.shared_volume_path = shared_volume_path
        self.execution_timeout = execution_timeout
        self.memory_limit_mb = memory_limit_mb
        self.session_id = session_id or f"subprocess_{uuid.uuid4().hex[:8]}"
        self.use_session_isolation = use_session_isolation
        
        # Set up session-specific temp directory for isolation
        if use_session_isolation:
            self.temp_dir = f"/tmp/sandbox_sessions/{self.session_id}/temp"
        else:
            self.temp_dir = "/tmp/sandbox_execution"
        
        # Track all spawned subprocess PIDs for cleanup
        self._active_processes: Dict[str, asyncio.subprocess.Process] = {}

        # Ensure directories exist and are owned by the exec user
        os.makedirs(self.shared_volume_path, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        exec_uid = int(os.getenv("SANDBOX_EXEC_UID", "0") or "0")
        exec_gid = int(os.getenv("SANDBOX_EXEC_GID", "0") or "0")
        if exec_uid and os.getuid() == 0:
            for d in (self.shared_volume_path, self.temp_dir):
                try:
                    os.chown(d, exec_uid, exec_gid)
                except OSError:
                    pass

    def _set_resource_limits(self):
        """Set resource limits and create new process group for the subprocess."""
        # Create a new session/process group so we can kill all descendants
        # (e.g., multiprocessing workers, MILP solvers, subprocess.Popen children)
        os.setsid()

        # Switch to SANDBOX_EXEC_USER identity if configured (Gurobi token server auth)
        # Fail closed: if identity switch fails, abort rather than run as root
        exec_user = os.getenv("SANDBOX_EXEC_USER", "")
        if exec_user:
            import pwd
            try:
                pw = pwd.getpwnam(exec_user)
                os.setgid(pw.pw_gid)
                os.setuid(pw.pw_uid)
            except KeyError:
                raise RuntimeError(
                    f"SANDBOX_EXEC_USER={exec_user} not found in /etc/passwd — "
                    "refusing to execute as root"
                )
            except PermissionError:
                raise RuntimeError(
                    f"Cannot setuid to {exec_user} — insufficient privileges. "
                    "Container must run as root for identity switching."
                )

        # Use configurable memory limit from environment, default to 30GB for COBRApy
        try:
            memory_gb = int(os.getenv("SUBPROCESS_MEMORY_LIMIT_GB", "30"))
            memory_bytes = memory_gb * 1024 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            logger.info(f"Set subprocess memory limit to {memory_gb}GB")
        except (OSError, ValueError) as e:
            # Skip memory limits if they can't be set
            logger.warning(f"Could not set memory limit: {e}")
            pass
            
        # Remove CPU time limit - it's too restrictive for subprocess execution
        # The asyncio timeout will handle wall-clock time limits
        
    def _create_restricted_env(self) -> Dict[str, str]:
        """Create a restricted environment for subprocess execution."""
        exec_user = os.getenv("SANDBOX_EXEC_USER", "")
        restricted_env = {
            'PATH': '/usr/local/bin:/usr/bin:/bin',
            'PYTHONPATH': '/app/.venv/lib/python3.11/site-packages',
            'SHARED_VOLUME_PATH': self.shared_volume_path,
            'HOME': self.temp_dir,
            'TMPDIR': self.temp_dir,
        }
        if exec_user:
            restricted_env['USER'] = exec_user
            restricted_env['LOGNAME'] = exec_user
        return restricted_env
        
    async def execute_python_code(self, code: str, 
                                generate_plot: bool = False,
                                working_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute Python code using subprocess.
        
        Args:
            code: Python code to execute
            generate_plot: Whether plot generation is expected
            working_dir: Working directory (defaults to shared volume path)
            
        Returns:
            Dictionary with execution results
        """
        execution_id = uuid.uuid4().hex[:8]
        script_name = f"script_{execution_id}.py"
        script_path = os.path.join(self.temp_dir, script_name)
        
        working_dir = working_dir or self.shared_volume_path
        
        logger.info(f"[SUBPROCESS] Executing Python code with ID {execution_id}")
        logger.info(f"[SUBPROCESS] Working directory: {working_dir}")
        logger.info(f"[SUBPROCESS] Script path: {script_path}")
        
        try:
            # Determine nsjail mode early — affects all path references in generated code
            use_nsjail = _should_use_nsjail()
            effective_working_dir = "/workspace" if use_nsjail else working_dir
            effective_shared_path = "/workspace" if use_nsjail else self.shared_volume_path

            # Prepare the code with additional setup and plotting library installation
            plotting_setup = ""
            plot_capture_postamble = ""

            if generate_plot:
                if use_nsjail:
                    # nsjail: venv is read-only, pip install impossible.
                    # All scientific packages are pre-installed in the container image.
                    plotting_setup = """
# Configure matplotlib for non-interactive backend (packages pre-installed)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
"""
                else:
                    plotting_setup = """
# Install plotting libraries for data visualization
import subprocess
import sys
try:
    import matplotlib
    print("matplotlib already installed")
except ImportError:
    print("Installing matplotlib and seaborn...")
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'matplotlib', 'seaborn', 'scipy', 'scikit-learn', '--quiet'])
    print("Plotting libraries installed successfully")

# Configure matplotlib for non-interactive backend
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
"""

                # Automatic plot capture postamble — uses effective path (jail or host)
                plot_capture_postamble = f"""

# Automatic plot capture (executed after user code)
import matplotlib.pyplot as plt
import os
import uuid

# Ensure plots directory exists
plots_dir = os.path.join('{effective_working_dir}', 'plots')
os.makedirs(plots_dir, exist_ok=True)

# Save all open figures
fig_managers = plt.get_fignums()
if fig_managers:
    print(f"Capturing {{len(fig_managers)}} matplotlib figure(s)...")
    for fig_num in fig_managers:
        fig = plt.figure(fig_num)
        plot_filename = f"{{uuid.uuid4().hex}}.png"
        plot_path = os.path.join(plots_dir, plot_filename)
        fig.savefig(plot_path, dpi=100, bbox_inches='tight')
        print(f"Saved plot to: {{plot_path}}")
        plt.close(fig)
else:
    print("No matplotlib figures found to save")
"""

            enhanced_code = f"""
import os
import sys

# Set working directory to shared volume
os.chdir('{effective_working_dir}')
sys.path.insert(0, '{effective_working_dir}')

# Ensure required directories exist
os.makedirs('{effective_shared_path}', exist_ok=True)

{plotting_setup}

# User code starts here
{code}
{plot_capture_postamble}
"""
            
            # Write code to temporary file
            with open(script_path, 'w') as f:
                f.write(enhanced_code)
                
            logger.info(f"[SUBPROCESS] Created script file: {script_path}")
            
            # Prepare subprocess execution
            env = self._create_restricted_env()

            if use_nsjail:
                try:
                    os.chmod(working_dir, 0o777)
                except OSError:
                    pass
                cmd, parent_env = _build_nsjail_command(
                    script_path=script_path,
                    working_dir=working_dir,
                    env=env,
                    timeout=self.execution_timeout,
                )
                exec_env = parent_env
                exec_cwd = "/"
                preexec = None  # nsjail handles isolation; no preexec_fn needed
                logger.info(f"[NSJAIL] Executing via nsjail: {' '.join(cmd[:6])}...")
            else:
                cmd = ['/app/.venv/bin/python', script_path]
                exec_env = env
                exec_cwd = working_dir
                preexec = self._set_resource_limits
                logger.info(f"[SUBPROCESS] Command: {' '.join(cmd)}")

            logger.info(f"[SUBPROCESS] Environment keys: {list(exec_env.keys())}")

            # Execute with timeout and resource limits
            start_time = time.time()
            process = None  # Initialize for finally-block cleanup

            # Acquire concurrency semaphore to prevent memory exhaustion
            semaphore = _get_subprocess_semaphore()
            await semaphore.acquire()
            logger.info(f"[CONCURRENCY] Semaphore acquired for {execution_id} "
                        f"({MAX_CONCURRENT_EXECUTIONS - semaphore._value}/{MAX_CONCURRENT_EXECUTIONS} slots in use)")
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=exec_env,
                    cwd=exec_cwd,
                    preexec_fn=preexec
                )
            except Exception:
                semaphore.release()
                raise
            self._active_processes[execution_id] = process

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), 
                    timeout=self.execution_timeout
                )
                exit_code = process.returncode
                
            except asyncio.TimeoutError:
                logger.warning(f"[SUBPROCESS_TIMEOUT] Execution timed out after {self.execution_timeout}s")
                # Kill the entire process group (subprocess + all its children)
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError) as kill_err:
                    logger.warning(f"[SUBPROCESS_TIMEOUT] Process group kill failed (already dead?): {kill_err}")
                await process.wait()
                return {
                    "status": "error",
                    "message": f"Code execution timed out after {self.execution_timeout} seconds",
                    "stdout": "",
                    "stderr": f"TimeoutError: Execution exceeded {self.execution_timeout} seconds",
                    "exit_code": -1,
                    "execution_time": time.time() - start_time
                }
                
            execution_time = time.time() - start_time
            
            # Decode output
            stdout_str = stdout.decode('utf-8') if stdout else ""
            stderr_str = stderr.decode('utf-8') if stderr else ""

            # Strip internal framework log lines from stdout/stderr before
            # returning to the orchestration layer.  These are emitted by
            # _set_resource_limits() (e.g. "Set subprocess memory limit to
            # 30GB") and pollute the output the LLM sees, wasting tokens and
            # obscuring actual program output.
            stdout_str = _strip_framework_log_noise(stdout_str)
            stderr_str = _strip_framework_log_noise(stderr_str)

            logger.info(f"Execution {execution_id} completed in {execution_time:.2f}s, exit_code={exit_code}")

            # Log truncated stdout/stderr for diagnostics (max 500 chars each)
            _max_log = 500
            if stdout_str:
                _stdout_preview = stdout_str[:_max_log] + ("..." if len(stdout_str) > _max_log else "")
                logger.info(f"[SUBPROCESS_STDOUT] ({len(stdout_str)} chars): {_stdout_preview}")
            if stderr_str:
                _stderr_preview = stderr_str[:_max_log] + ("..." if len(stderr_str) > _max_log else "")
                logger.warning(f"[SUBPROCESS_STDERR] ({len(stderr_str)} chars): {_stderr_preview}")
            
            # Scan for generated files in shared volume
            generated_files = self._scan_generated_files()
            logger.info(f"[SUBPROCESS] Found {len(generated_files)} generated files: {generated_files}")

            # Detect and process plot files if requested
            plots_data = self._detect_plots(generate_plot=generate_plot, working_dir=working_dir)
            logger.info(f"[PLOT_DETECT] Detected {len(plots_data)} plots")

            # Determine status
            status = "success" if exit_code == 0 else "error"
            message = "Code executed successfully" if exit_code == 0 else f"Code execution failed with exit code {exit_code}"

            return {
                "status": status,
                "message": message,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "exit_code": exit_code,
                "execution_time": execution_time,
                "generated_files": generated_files,
                "plots": plots_data
            }
            
        except Exception as e:
            logger.error(f"[SUBPROCESS] Exception during execution: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Execution failed with exception: {str(e)}",
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "execution_time": 0,
                "generated_files": [],
                "plots": []
            }
            
        finally:
            # Cleanup temporary script file
            try:
                if os.path.exists(script_path):
                    os.remove(script_path)
                    logger.info(f"[SUBPROCESS] Cleaned up script file: {script_path}")
            except Exception as cleanup_error:
                logger.warning(f"[SUBPROCESS] Failed to cleanup script file: {cleanup_error}")
            # Deregister from active process tracking
            self._active_processes.pop(execution_id, None)
            # Ensure subprocess is terminated even on unexpected exceptions
            if process is not None and process.returncode is None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    await process.wait()
                    logger.info(f"[PROCESS_CLEANUP] Killed orphaned process group for execution {execution_id}")
                except (ProcessLookupError, OSError):
                    pass  # Already dead
            # Release concurrency semaphore
            if process is not None:
                semaphore.release()
                logger.info(f"[CONCURRENCY] Semaphore released for {execution_id}")

    def _scan_generated_files(self) -> List[str]:
        """Scan the shared volume for newly generated files."""
        generated_files = []

        try:
            if os.path.exists(self.shared_volume_path):
                for file_path in Path(self.shared_volume_path).glob("*"):
                    if file_path.is_file():
                        # Get file info
                        stat = file_path.stat()
                        # Consider files generated in the last minute as "new"
                        if time.time() - stat.st_mtime < 60:
                            generated_files.append(str(file_path))

        except Exception as e:
            logger.warning(f"[SUBPROCESS] Error scanning generated files: {e}")

        return generated_files

    def _detect_plots(self, generate_plot: bool = False, working_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """Detect and process plot files generated during execution.

        Args:
            generate_plot: Whether plot generation was requested
            working_dir: Working directory where code was executed (plots are in working_dir/plots/)

        Returns:
            List of plot metadata dictionaries with comprehensive telemetry
        """
        plots_data = []

        if not generate_plot:
            return plots_data

        import base64
        # Lazy import to avoid circular dependency
        from .code_execution_tool import _generate_plot_metadata

        # Plot file extensions to scan for (EXPANDED support)
        plot_extensions = (
            '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.gif', '.webp', '.ico',  # Raster
            '.svg', '.eps',  # Vector
            '.pdf',  # Document
            '.html'  # Interactive
        )

        # Use working_dir if provided, otherwise fall back to shared_volume_path
        base_dir = working_dir or self.shared_volume_path

        try:
            # Scan the plots subdirectory within the working directory
            plots_dir = os.path.join(base_dir, "plots")
            search_paths = [plots_dir]

            logger.info(f"[PLOT_DETECT] Scanning for plots in base_dir: {base_dir}")
            logger.info(f"[PLOT_DETECT] Plots directory: {plots_dir}")

            for search_path in search_paths:
                if os.path.exists(search_path):
                    logger.info(f"[PLOT_DETECT] Scanning for plots in: {search_path}")
                    for file_path in Path(search_path).glob("*"):
                        if file_path.is_file() and file_path.suffix.lower() in plot_extensions:
                            # Get file info
                            stat = file_path.stat()
                            # Consider files generated in the last minute as "new"
                            if time.time() - stat.st_mtime < 60:
                                try:
                                    # Copy plot to shared volume for agent_gateway access
                                    shared_plots_dir = "/app/data/uploaded_files/plots"
                                    os.makedirs(shared_plots_dir, exist_ok=True)

                                    # Use original filename to match URL generation
                                    shared_plot_path = os.path.join(shared_plots_dir, file_path.name)
                                    shutil.copy2(str(file_path), shared_plot_path)
                                    logger.info(f"[PLOT] Copied plot to shared volume: {file_path.name} -> {shared_plot_path}")

                                    # Use the shared _generate_plot_metadata() function for consistency
                                    # Pass the shared volume path so URLs point to accessible location
                                    plot_metadata = _generate_plot_metadata(
                                        plot_filepath=shared_plot_path,
                                        mcp_session_id=self.session_id
                                    )

                                    # Add base64 encoding for backward compatibility
                                    with open(file_path, 'rb') as f:
                                        plot_bytes = f.read()
                                    plot_metadata["content_base64"] = base64.b64encode(plot_bytes).decode('utf-8')
                                    plot_metadata["artifact_type"] = "image/plot"

                                    plots_data.append(plot_metadata)
                                    logger.info(f"[PLOT] Detected plot: {plot_metadata['filename']} ({plot_metadata['size_bytes']} bytes, {plot_metadata['format']} format)")

                                except Exception as e:
                                    logger.warning(f"Failed to process plot file {file_path}: {e}")
                                    continue

        except Exception as e:
            logger.warning(f"[SUBPROCESS] Error detecting plots: {e}")

        return plots_data

    async def kill_all_active_processes(self):
        """Kill all tracked active subprocesses and their process groups."""
        for exec_id, proc in list(self._active_processes.items()):
            if proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    await proc.wait()
                    logger.info(f"[PROCESS_CLEANUP] Killed process group for execution {exec_id} (PID {proc.pid})")
                except (ProcessLookupError, OSError) as e:
                    logger.debug(f"[PROCESS_CLEANUP] Process {exec_id} already dead: {e}")
        self._active_processes.clear()


# Enhanced subprocess execution with proper session isolation
async def execute_code_subprocess(
    code: str,
    language: str = "python",
    generate_plot: bool = False,
    execution_timeout: Optional[int] = None,  # Configurable timeout
    base_location: str = "tmpfs",  # NEW: Choose storage location
    workspace_dir: Optional[str] = None,
    outputs_dir: Optional[str] = None,
    session_id: Optional[str] = None,
    mcp_session_id: Optional[str] = None,
    multi_agent_session_id: Optional[str] = None,
    gateway_session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Alternative code execution function using subprocess with session isolation.

    Implements hybrid approach with configurable storage:
    1. Execute in chosen storage location (tmpfs, workspace, or uploaded_files)
    2. Copy outputs to shared volume for persistence
    3. Return file paths accessible to agent_gateway

    Args:
        code: The code to execute
        language: Programming language ("python", "shell", "bash", or "sh")
        generate_plot: Whether to capture plot outputs
        execution_timeout: Timeout in seconds (default: 30, max: 300). For long-running tasks,
                         you can specify up to 5 minutes (300 seconds)
        base_location: Storage location for code execution:
            - "tmpfs" (default): Ephemeral /tmp/sandbox_sessions, cleared on restart
            - "workspace": Persistent /workspace volume, survives container restarts
            - "uploaded_files": Shared /app/data/uploaded_files, accessible across all services
    """
    logger.info(f"[SUBPROCESS_EXEC] \1tarting {language} code execution")
    logger.info(f"[SUBPROCESS] Session hierarchy:")
    logger.info(f"   - session_id: {session_id}")
    logger.info(f"   - mcp_session_id: {mcp_session_id}")
    logger.info(f"   - multi_agent_session_id: {multi_agent_session_id}")
    logger.info(f"   - gateway_session_id: {gateway_session_id}")
    logger.info(f"   - user_id: {user_id}")
    logger.info(f"   - base_location: {base_location}")
    logger.info(f"   - execution_timeout: {execution_timeout}")

    # Process and validate timeout
    if execution_timeout is None:
        # Check if code appears to be downloading large files
        if any(keyword in code.lower() for keyword in ["download", "wget", "curl", "urlretrieve", "requests.get"]):
            execution_timeout = DOWNLOAD_TIMEOUT
            logger.info(f"[TIMEOUT] Detected download operation, using download timeout: {execution_timeout}s")
        else:
            execution_timeout = DEFAULT_TIMEOUT
            logger.info(f"[TIMEOUT] Using default timeout: {execution_timeout}s")
    else:
        # Ensure timeout doesn't exceed maximum
        if execution_timeout > MAX_TIMEOUT:
            logger.warning(f"[WARN] Requested timeout {execution_timeout}s exceeds maximum {MAX_TIMEOUT}s, capping to maximum")
            execution_timeout = MAX_TIMEOUT
        elif execution_timeout < 1:
            logger.warning(f"[WARN] Invalid timeout {execution_timeout}s, using default {DEFAULT_TIMEOUT}s")
            execution_timeout = DEFAULT_TIMEOUT
        else:
            logger.info(f"[TIMEOUT] Using custom timeout: {execution_timeout}s")

    supported_languages = ("python", "shell", "bash", "sh")
    if language.lower() not in supported_languages:
        return {
            "status": "error",
            "message": f"Subprocess execution supports {supported_languages}, got: {language}",
            "stdout": "",
            "stderr": "",
            "exit_code": -1
        }

    # Get or create session with proper hierarchy
    from ..session.session_manager import get_session_manager
    session_manager = get_session_manager()

    # Use the full session ID if provided, otherwise create a prefixed one
    effective_session_id = session_id or f"subprocess_{mcp_session_id or uuid.uuid4().hex[:8]}"

    # Determine workspace path based on base_location
    if base_location == "workspace":
        # Use persistent workspace volume
        workspace_base = os.getenv("SANDBOX_WORKSPACE_PATH", "/workspace")
        session_workspace = os.path.join(workspace_base, "sessions", effective_session_id, "workspace")
        session_outputs = os.path.join(workspace_base, "sessions", effective_session_id, "outputs")
        logger.info(f"[SUBPROCESS] Using persistent workspace volume: {session_workspace}")
    elif base_location == "uploaded_files":
        # Use shared uploaded_files volume
        shared_base = "/app/data/uploaded_files"
        session_workspace = os.path.join(shared_base, mcp_session_id or "default", "workspace")
        session_outputs = os.path.join(shared_base, mcp_session_id or "default", "outputs")
        logger.info(f"[SUBPROCESS] Using shared uploaded_files volume: {session_workspace}")
    else:  # Default to tmpfs
        # Use tmpfs (ephemeral, default behavior)
        session_info = session_manager.get_session(effective_session_id)
        if not session_info:
            session_info = session_manager.create_session(
                session_id=effective_session_id,
                user_id=user_id,
                multi_agent_session_id=multi_agent_session_id,
                gateway_session_id=gateway_session_id
            )
        session_workspace = session_info.workspace_path
        session_outputs = session_info.outputs_path
        logger.info(f"[SUBPROCESS] Using tmpfs (ephemeral) workspace: {session_workspace}")

    # Ensure directories exist and are writable by the subprocess exec user.
    # Server runs as root (for setuid capability) but subprocess switches to
    # SANDBOX_EXEC_UID:SANDBOX_EXEC_GID — directories must be owned accordingly.
    os.makedirs(session_workspace, exist_ok=True)
    os.makedirs(session_outputs, exist_ok=True)

    exec_uid = int(os.getenv("SANDBOX_EXEC_UID", "0") or "0")
    exec_gid = int(os.getenv("SANDBOX_EXEC_GID", "0") or "0")
    if exec_uid and os.getuid() == 0:
        for d in (session_workspace, session_outputs):
            try:
                os.chown(d, exec_uid, exec_gid)
            except OSError:
                pass

    logger.info(f"[SUBPROCESS] Using session workspace: {session_workspace}")
    logger.info(f"[SUBPROCESS] Using session outputs: {session_outputs}")
    
    # Track files before execution to detect new files
    import glob
    before_files = set(glob.glob(os.path.join(session_workspace, "*")))
    
    # Execute code in session-isolated environment
    executor = SubprocessCodeExecutor(
        execution_timeout=execution_timeout,
        shared_volume_path=session_workspace,
        session_id=effective_session_id,
        use_session_isolation=True
    )

    # Handle different languages
    if language.lower() in ['shell', 'bash', 'sh']:
        # Wrap shell commands in Python subprocess for consistent execution
        wrapped_code = f"""import subprocess
import sys

try:
    result = subprocess.run(
        {repr(code)},
        shell=True,
        capture_output=True,
        text=True,
        cwd='{session_workspace}',
        timeout={execution_timeout}
    )
    print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, file=sys.stderr, end='')
    sys.exit(result.returncode)
except subprocess.TimeoutExpired:
    print("Command timed out after {execution_timeout} seconds", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"Error executing shell command: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
        logger.info("[SUBPROCESS] Wrapping shell command in Python subprocess")
        result = await executor.execute_python_code(wrapped_code, generate_plot, working_dir=session_workspace)
    elif language.lower() == 'python':
        result = await executor.execute_python_code(code, generate_plot, working_dir=session_workspace)
    else:
        # Unsupported language
        logger.error(f"[SUBPROCESS] Unsupported language: {language}")
        result = {
            "status": "error",
            "message": f"Subprocess mode only supports Python and shell languages, not '{language}'",
            "stdout": "",
            "stderr": f"Unsupported language: {language}",
            "exit_code": 1,
            "plots": []
        }
    
    # Detect generated files
    after_files = set(glob.glob(os.path.join(session_workspace, "*")))
    generated_files = list(after_files - before_files)
    
    if generated_files:
        logger.info(f"[SUBPROCESS] Generated {len(generated_files)} files/directories")

        # Copy generated files and directories to session outputs (for persistence)
        for src_path in generated_files:
            filename = os.path.basename(src_path)
            dst_path = os.path.join(session_outputs, filename)

            import shutil
            if os.path.isdir(src_path):
                # Copy directory recursively
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                logger.info(f"[SUBPROCESS] Copied directory {filename} to session outputs")
            else:
                # Copy file
                shutil.copy2(src_path, dst_path)
                logger.info(f"[SUBPROCESS] Copied file {filename} to session outputs")
        
        # Publish to shared volume for agent_gateway serving
        shared_volume_base = "/app/data/uploaded_files"
        if session_manager.publish_session_outputs_to_shared_volume(effective_session_id, shared_volume_base=shared_volume_base):
            logger.info("[SUBPROCESS] Published session outputs to shared volume")

        # Return persistent shared-volume paths (not tmpfs workspace paths)
        # so that _register_emsl_remote_files() can convert them to nginx URLs.
        # Pattern: /app/data/uploaded_files/sessions/{sid}/outputs/{filename}
        published_paths = [
            os.path.join(shared_volume_base, "sessions", effective_session_id, "outputs", os.path.basename(f))
            for f in generated_files
        ]
        result["generated_files"] = published_paths
        result["session_id"] = effective_session_id
        result["session_outputs_path"] = os.path.join(shared_volume_base, "sessions", effective_session_id, "outputs")
    
    logger.info(f"[SUBPROCESS_EXEC] \1ompleted with status: {result['status']}")
    return result
