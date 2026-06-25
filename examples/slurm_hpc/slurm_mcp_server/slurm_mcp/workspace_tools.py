"""Cluster-agnostic workspace management tools for remote HPC clusters.

Provides MCP tools for listing, uploading, downloading, and reading files
in the remote $HOME/adept-workspace/{session_id}/ directory on any SSH-accessible
cluster (Deception, Tahoma, etc.).

These tools reuse the same FabricSSHTransport connection that job submission
uses, ensuring consistent authentication and host-key handling.
"""

import io
import logging
import os
import posixpath
from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .app import app
from .transport import SlurmTransport

logger = logging.getLogger(__name__)

SHARED_UPLOAD_DIR = os.getenv("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
CONTAINERS_DIR = os.getenv("CONTAINERS_DIR", "/app/containers")
DEMOS_DIR = os.getenv("DEMOS_DIR", "/app/demos")
UPLOAD_SEARCH_PATHS = [SHARED_UPLOAD_DIR, CONTAINERS_DIR, DEMOS_DIR]

SUPPORTED_CLUSTERS = ("deception", "tahoma")


async def _get_transport_for_cluster(cluster: str) -> SlurmTransport:
    """Resolve the SSH transport for a named cluster.

    Raises ValueError if the cluster is unknown or transport unavailable.
    """
    cluster = cluster.lower().strip()
    if cluster == "deception":
        from .deception.tools import _get_transport

        return await _get_transport()
    elif cluster == "tahoma":
        from .tahoma.tools import _get_transport

        return await _get_transport()
    else:
        raise ValueError(
            f"Unknown cluster '{cluster}'. Supported: {', '.join(SUPPORTED_CLUSTERS)}"
        )


def _require_ssh_transport(transport: SlurmTransport):
    """Ensure the transport supports SSH file operations."""
    from .fabric_transport import FabricSSHTransport

    if not isinstance(transport, FabricSSHTransport):
        raise ValueError(
            "Workspace file operations require SSH transport. "
            "The active transport for this cluster is REST-only."
        )
    return transport


class WorkspaceListRequest(BaseModel):
    """Request to list files in a remote workspace."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "cluster": "deception",
                    "session_id": "mcp_abc123",
                },
                {
                    "cluster": "deception",
                    "session_id": "mcp_abc123",
                    "subpath": "output",
                },
            ]
        }
    )

    cluster: str = Field(
        ..., description="Target cluster name: 'deception' or 'tahoma'"
    )
    session_id: Optional[str] = Field(
        None,
        description=(
            "MCP session ID identifying the workspace. "
            "Use your MCP Session ID from system prompt."
        ),
    )
    subpath: Optional[str] = Field(
        None,
        description=(
            "Optional subdirectory within the workspace to list "
            "(e.g., 'output', 'input'). Defaults to listing the workspace root."
        ),
    )
    workspace_path: Optional[str] = Field(
        None,
        description=(
            "Explicit absolute path to use as workspace root instead of the "
            "default $HOME/adept-workspace/{session_id}/. When provided, "
            "session_id is ignored for path resolution. The directory must "
            "exist on the cluster. Example: '/scratch/rigo160/results'"
        ),
    )
    timeout_seconds: Optional[int] = Field(
        None,
        ge=1,
        le=300,
        description=(
            "SSH command timeout in seconds. Overrides the cluster default "
            "(30 seconds). Use for directories with many files. "
            "Range: 1-300 seconds. Example: 60 for a large listing."
        ),
    )


class WorkspaceUploadRequest(BaseModel):
    """Request to upload a file from shared_uploads to a remote workspace."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "cluster": "deception",
                    "session_id": "mcp_abc123",
                    "local_path": "mcp_abc123/input_data.csv",
                }
            ]
        }
    )

    cluster: str = Field(
        ..., description="Target cluster name: 'deception' or 'tahoma'"
    )
    session_id: Optional[str] = Field(
        None,
        description=(
            "MCP session ID identifying the workspace. "
            "Use your MCP Session ID from system prompt."
        ),
    )
    local_path: str = Field(
        ...,
        description=(
            "Path to the source file relative to the shared uploads directory "
            "(e.g., 'mcp_abc123/input_data.csv'). The file must exist in "
            "the shared_uploads volume."
        ),
    )
    remote_filename: Optional[str] = Field(
        None,
        description=(
            "Override filename on the remote cluster. "
            "Defaults to the basename of local_path."
        ),
    )
    subpath: Optional[str] = Field(
        None,
        description=(
            "Optional subdirectory within the workspace to upload into "
            "(e.g., 'input'). Created if it doesn't exist."
        ),
    )
    workspace_path: Optional[str] = Field(
        None,
        description=(
            "Explicit absolute path to use as workspace root instead of the "
            "default $HOME/adept-workspace/{session_id}/. When provided, "
            "session_id is ignored for path resolution. The directory must "
            "exist on the cluster. Example: '/scratch/rigo160/containers'"
        ),
    )
    timeout_seconds: Optional[int] = Field(
        None,
        ge=1,
        le=300,
        description=(
            "SSH command timeout in seconds. Overrides the cluster default "
            "(30 seconds). Use for large file transfers that may exceed "
            "the default timeout. Range: 1-300 seconds. Example: 120 for "
            "a multi-MB upload."
        ),
    )


class WorkspaceDownloadRequest(BaseModel):
    """Request to download a file from a remote workspace to shared_uploads."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "cluster": "deception",
                    "session_id": "mcp_abc123",
                    "remote_filename": "slurm-1234567.out",
                }
            ]
        }
    )

    cluster: str = Field(
        ..., description="Target cluster name: 'deception' or 'tahoma'"
    )
    session_id: Optional[str] = Field(
        None,
        description=(
            "MCP session ID identifying the workspace. "
            "Use your MCP Session ID from system prompt."
        ),
    )
    remote_filename: str = Field(
        ...,
        description=(
            "Filename (or relative path) within the workspace to download "
            "(e.g., 'slurm-12345.out' or 'output/results.csv')"
        ),
    )
    local_filename: Optional[str] = Field(
        None,
        description=(
            "Override filename for the local copy. "
            "Defaults to the basename of remote_filename."
        ),
    )
    workspace_path: Optional[str] = Field(
        None,
        description=(
            "Explicit absolute path to use as workspace root instead of the "
            "default $HOME/adept-workspace/{session_id}/. When provided, "
            "session_id is ignored for path resolution."
        ),
    )
    timeout_seconds: Optional[int] = Field(
        None,
        ge=1,
        le=300,
        description=(
            "SSH command timeout in seconds. Overrides the cluster default "
            "(30 seconds). Use for large file downloads that may exceed "
            "the default timeout. Range: 1-300 seconds. Example: 120 for "
            "a multi-MB download."
        ),
    )


class WorkspaceReadFileRequest(BaseModel):
    """Request to read file content from a remote workspace."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "cluster": "deception",
                    "session_id": "mcp_abc123",
                    "remote_filename": "slurm-1234567.out",
                    "max_lines": 50,
                }
            ]
        }
    )

    cluster: str = Field(
        ..., description="Target cluster name: 'deception' or 'tahoma'"
    )
    session_id: Optional[str] = Field(
        None,
        description=(
            "MCP session ID identifying the workspace. "
            "Use your MCP Session ID from system prompt."
        ),
    )
    remote_filename: str = Field(
        ...,
        description=(
            "Filename (or relative path) within the workspace to read "
            "(e.g., 'slurm-12345.out' or 'hello_world_abc123.sh')"
        ),
    )
    max_lines: Optional[int] = Field(
        None,
        description=(
            "Maximum number of lines to return (from the end of file, like tail). "
            "Defaults to returning the entire file (up to 10000 lines)."
        ),
    )
    offset_lines: Optional[int] = Field(
        None,
        description="Number of lines to skip from the beginning (like tail -n +N).",
    )
    workspace_path: Optional[str] = Field(
        None,
        description=(
            "Explicit absolute path to use as workspace root instead of the "
            "default $HOME/adept-workspace/{session_id}/. When provided, "
            "session_id is ignored for path resolution. Use this to read "
            "files from a known absolute location on the cluster."
        ),
    )
    timeout_seconds: Optional[int] = Field(
        None,
        ge=1,
        le=300,
        description=(
            "SSH command timeout in seconds. Overrides the cluster default "
            "(30 seconds). Use for large output files that take longer to "
            "read. Range: 1-300 seconds. Example: 60 for a multi-MB log."
        ),
    )


async def _resolve_workspace_dir(ssh, session_id: str, subpath: Optional[str] = None) -> str:
    """Resolve canonical absolute workspace path.

    Uses readlink -f to resolve symlinks (e.g., /people/user -> /qfs/people/user
    on Deception). Never uses tilde — sbatch doesn't expand it.
    Rejects subpath containing '..' to prevent workspace escape.
    """
    home_result = ssh._run("readlink -f $HOME || echo $HOME", warn=True)
    home_dir = home_result.stdout.strip() or "/tmp"
    workspace_dir = f"{home_dir}/adept-workspace/{session_id}"
    if subpath:
        if ".." in subpath:
            raise ValueError(
                f"subpath cannot contain '..' (got: '{subpath}'). "
                "Use deception_execute_command to create directories outside "
                "the workspace, then upload to the workspace and copy."
            )
        resolved = posixpath.normpath(f"{workspace_dir}/{subpath}")
        logger.debug("Resolved workspace: %s (subpath=%s)", resolved, subpath)
        return resolved
    logger.debug("Resolved workspace: %s", workspace_dir)
    return workspace_dir


@app.tool
async def workspace_list_files(
    request: WorkspaceListRequest,
    mcp_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """List files in a remote HPC workspace directory.

    Lists the contents of $HOME/adept-workspace/{session_id}/ (or a subdirectory
    within it) on the specified cluster. Returns file names, sizes, and
    modification times.

    Use this to check what scripts were submitted, what output files exist
    after a job completes, or what input files have been uploaded.

    Args:
        request: WorkspaceListRequest with cluster, session_id, and optional subpath.

    Returns:
        dict with:
            - status: 'success' or 'error'
            - cluster: cluster name
            - workspace: remote workspace path (absolute)
            - files: list of dicts with name, size_bytes, modified fields
            - file_count: total number of files found

    Example:
        >>> workspace_list_files(request=WorkspaceListRequest(
        ...     cluster="deception", session_id="mcp_abc123"
        ... ))
        {"status": "success", "cluster": "deception",
         "workspace": "/qfs/people/user/adept-workspace/mcp_abc123",
         "file_count": 3, "files": [
             {"name": "hello_world_a1b2c3d4.sh", "size_bytes": 156, "modified": "2026-06-10 08:30"},
             {"name": "slurm-1234567.out", "size_bytes": 42, "modified": "2026-06-10 08:31"},
         ]}
    """
    try:
        if not request.session_id and mcp_session_id:
            request.session_id = mcp_session_id
        if not request.session_id and not request.workspace_path:
            logger.warning("workspace_list_files called without session_id or workspace_path")
            return {
                "status": "error",
                "message": "session_id or workspace_path is required",
            }

        logger.info(
            "workspace_list_files: cluster=%s session_id=%s subpath=%s workspace_path=%s",
            request.cluster, request.session_id, request.subpath, request.workspace_path,
        )
        transport = await _get_transport_for_cluster(request.cluster)
        ssh = _require_ssh_transport(transport)

        if request.workspace_path:
            workspace_dir = request.workspace_path
        else:
            workspace_dir = await _resolve_workspace_dir(ssh, request.session_id)
        target_dir = f"{workspace_dir}/{request.subpath}" if request.subpath else workspace_dir
        logger.info("Listing directory: %s", target_dir)

        result = ssh._run(
            f"ls -la --time-style=long-iso {target_dir} 2>/dev/null || echo '__NOTFOUND__'",
            warn=True,
            timeout=request.timeout_seconds,
        )

        if "__NOTFOUND__" in result.stdout or result.failed:
            logger.warning("Workspace directory does not exist: %s", target_dir)
            return {
                "status": "empty",
                "cluster": request.cluster,
                "workspace": workspace_dir,
                "file_count": 0,
                "files": [],
                "message": f"Workspace directory does not exist: {target_dir}",
            }

        files: List[Dict[str, Any]] = []
        for line in result.stdout.strip().splitlines():
            if line.startswith("total ") or not line.strip():
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            # -rw-r--r-- 1 user group SIZE DATE TIME NAME
            perms = parts[0]
            if perms.startswith("d"):
                continue
            size = int(parts[4]) if parts[4].isdigit() else 0
            date_str = f"{parts[5]} {parts[6]}"
            name = " ".join(parts[7:])
            files.append(
                {"name": name, "size_bytes": size, "modified": date_str}
            )

        logger.info("workspace_list_files: found %d files in %s", len(files), target_dir)
        return {
            "status": "success",
            "cluster": request.cluster,
            "workspace": workspace_dir,
            "file_count": len(files),
            "files": files,
        }

    except Exception as e:
        logger.error("workspace_list_files failed: %s", e, exc_info=True)
        return {
            "status": "error",
            "cluster": request.cluster,
            "message": str(e),
        }


@app.tool
async def workspace_upload_file(
    request: WorkspaceUploadRequest,
    mcp_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Upload a file from the shared uploads volume to a remote HPC workspace.

    Transfers a file from the local shared_uploads directory (populated by
    the orchestration_service or sandbox) to $HOME/adept-workspace/{session_id}/
    on the specified cluster via SFTP/SCP.

    Use this to stage input data files on the cluster before submitting a job
    that needs them. The workspace directory is created if it doesn't exist.

    Args:
        request: WorkspaceUploadRequest with cluster, session_id, local_path,
            and optional remote_filename/subpath.

    Returns:
        dict with:
            - status: 'uploaded' or 'error'
            - cluster: cluster name
            - remote_path: full path where the file was placed on the cluster
            - size_bytes: size of the uploaded file

    Example:
        >>> workspace_upload_file(request=WorkspaceUploadRequest(
        ...     cluster="deception", session_id="mcp_abc123",
        ...     local_path="mcp_abc123/input_data.csv"
        ... ))
        {"status": "uploaded", "cluster": "deception",
         "remote_path": "/qfs/people/user/adept-workspace/mcp_abc123/input_data.csv",
         "size_bytes": 4096}
    """
    try:
        if not request.session_id and mcp_session_id:
            request.session_id = mcp_session_id
        if not request.session_id and not request.workspace_path:
            logger.warning("workspace_upload_file called without session_id or workspace_path")
            return {
                "status": "error",
                "message": "session_id or workspace_path is required",
            }

        logger.info(
            "workspace_upload_file: cluster=%s session_id=%s local_path=%s remote_filename=%s workspace_path=%s",
            request.cluster, request.session_id, request.local_path, request.remote_filename,
            request.workspace_path,
        )
        transport = await _get_transport_for_cluster(request.cluster)
        ssh = _require_ssh_transport(transport)

        # Resolve local file — search shared_uploads, containers, demos
        local_file = None
        for search_dir in UPLOAD_SEARCH_PATHS:
            candidate = os.path.join(search_dir, request.local_path)
            if os.path.isfile(candidate):
                local_file = candidate
                break
        if local_file is None:
            searched = ", ".join(UPLOAD_SEARCH_PATHS)
            logger.error("Source file not found: %s (searched: %s)", request.local_path, searched)
            return {
                "status": "error",
                "cluster": request.cluster,
                "message": f"Source file not found: {request.local_path} "
                f"(searched: {searched})",
            }

        file_size = os.path.getsize(local_file)
        filename = request.remote_filename or os.path.basename(request.local_path)

        # Build remote path — absolute, never tilde
        if request.workspace_path:
            base_dir = request.workspace_path
            target_dir = f"{base_dir}/{request.subpath}" if request.subpath else base_dir
        else:
            target_dir = await _resolve_workspace_dir(ssh, request.session_id, request.subpath)

        # Ensure remote directory exists (check first, then create)
        check_result = ssh._run(f"test -d {target_dir} && echo EXISTS", warn=True)
        if "EXISTS" not in (check_result.stdout or ""):
            logger.info("Remote directory does not exist, creating: %s", target_dir)
            mkdir_result = ssh._run(f"mkdir -p {target_dir}", warn=True)
            if mkdir_result.return_code != 0:
                return {
                    "status": "error",
                    "cluster": request.cluster,
                    "message": f"Failed to create remote directory: {target_dir} "
                    f"(stderr: {mkdir_result.stderr.strip()})",
                }

        abs_remote_path = f"{target_dir}/{filename}"
        logger.info("Uploading %s (%d bytes) -> %s", local_file, file_size, abs_remote_path)

        # Upload via Fabric's put()
        conn = ssh._get_connection()
        conn.put(local_file, abs_remote_path)

        logger.info("Upload complete: %s (%d bytes)", abs_remote_path, file_size)
        return {
            "status": "uploaded",
            "cluster": request.cluster,
            "remote_path": abs_remote_path,
            "size_bytes": file_size,
        }

    except Exception as e:
        logger.error("workspace_upload_file failed: %s", e, exc_info=True)
        return {
            "status": "error",
            "cluster": request.cluster,
            "message": str(e),
        }


@app.tool
async def workspace_download_file(
    request: WorkspaceDownloadRequest,
    mcp_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Download a file from a remote HPC workspace to the shared uploads volume.

    Transfers a file from $HOME/adept-workspace/{session_id}/ on the specified
    cluster back to the local shared_uploads directory via SFTP/SCP. The
    downloaded file is placed in shared_uploads/{session_id}/ for access
    by the orchestration_service.

    Use this to retrieve job output files (slurm-*.out), generated results,
    or any intermediate artifacts from the remote workspace.

    Args:
        request: WorkspaceDownloadRequest with cluster, session_id,
            remote_filename, and optional local_filename.

    Returns:
        dict with:
            - status: 'downloaded' or 'error'
            - cluster: cluster name
            - local_path: path where the file was saved (relative to shared_uploads)
            - remote_path: source path on the cluster
            - size_bytes: size of the downloaded file

    Example:
        >>> workspace_download_file(request=WorkspaceDownloadRequest(
        ...     cluster="deception", session_id="mcp_abc123",
        ...     remote_filename="slurm-1234567.out"
        ... ))
        {"status": "downloaded", "cluster": "deception",
         "local_path": "mcp_abc123/slurm-1234567.out",
         "remote_path": "/qfs/people/user/adept-workspace/mcp_abc123/slurm-1234567.out",
         "size_bytes": 256}
    """
    try:
        if not request.session_id and mcp_session_id:
            request.session_id = mcp_session_id
        if not request.session_id and not request.workspace_path:
            logger.warning("workspace_download_file called without session_id or workspace_path")
            return {
                "status": "error",
                "message": "session_id or workspace_path is required",
            }

        logger.info(
            "workspace_download_file: cluster=%s session_id=%s remote_filename=%s workspace_path=%s",
            request.cluster, request.session_id, request.remote_filename, request.workspace_path,
        )
        transport = await _get_transport_for_cluster(request.cluster)
        ssh = _require_ssh_transport(transport)

        # Build remote path — absolute, never tilde
        if request.workspace_path:
            workspace_dir = request.workspace_path
        else:
            workspace_dir = await _resolve_workspace_dir(ssh, request.session_id)
        abs_remote_path = f"{workspace_dir}/{request.remote_filename}"

        # Check remote file exists
        check = ssh._run(f"test -f {abs_remote_path} && echo EXISTS", warn=True)
        if "EXISTS" not in check.stdout:
            logger.warning("Remote file not found: %s", abs_remote_path)
            return {
                "status": "error",
                "cluster": request.cluster,
                "message": f"Remote file not found: {abs_remote_path}",
            }

        # Prepare local destination
        local_dir = os.path.join(SHARED_UPLOAD_DIR, request.session_id)
        os.makedirs(local_dir, exist_ok=True)

        filename = request.local_filename or os.path.basename(
            request.remote_filename
        )
        local_file = os.path.join(local_dir, filename)

        # Download via Fabric's get()
        logger.info("Downloading %s -> %s", abs_remote_path, local_file)
        conn = ssh._get_connection()
        conn.get(abs_remote_path, local_file)

        file_size = os.path.getsize(local_file)
        relative_path = f"{request.session_id}/{filename}"

        logger.info("Download complete: %s (%d bytes)", abs_remote_path, file_size)
        return {
            "status": "downloaded",
            "cluster": request.cluster,
            "local_path": relative_path,
            "remote_path": abs_remote_path,
            "size_bytes": file_size,
        }

    except Exception as e:
        logger.error("workspace_download_file failed: %s", e, exc_info=True)
        return {
            "status": "error",
            "cluster": request.cluster,
            "message": str(e),
        }


@app.tool
async def workspace_read_file(
    request: WorkspaceReadFileRequest,
    mcp_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Read the content of a file in a remote HPC workspace.

    Retrieves the text content of a file from $HOME/adept-workspace/{session_id}/
    on the specified cluster. Useful for inspecting job output logs
    (slurm-*.out), checking script content, or reading small result files
    without downloading them.

    For large files, use max_lines to limit output (reads from end of file
    like tail) or offset_lines to skip the beginning.

    Args:
        request: WorkspaceReadFileRequest with cluster, session_id,
            remote_filename, and optional max_lines/offset_lines.

    Returns:
        dict with:
            - status: 'success' or 'error'
            - cluster: cluster name
            - filename: the file that was read
            - content: file content as a string
            - line_count: number of lines returned
            - truncated: whether output was truncated by max_lines

    Example:
        >>> workspace_read_file(request=WorkspaceReadFileRequest(
        ...     cluster="deception", session_id="mcp_abc123",
        ...     remote_filename="slurm-1234567.out", max_lines=50
        ... ))
        {"status": "success", "cluster": "deception",
         "filename": "slurm-1234567.out",
         "content": "Hello from node001\\nJob completed successfully\\n",
         "line_count": 2, "truncated": false}
    """
    try:
        if not request.session_id and mcp_session_id:
            request.session_id = mcp_session_id
        if not request.session_id and not request.workspace_path:
            logger.warning("workspace_read_file called without session_id or workspace_path")
            return {
                "status": "error",
                "message": "session_id or workspace_path is required",
            }

        logger.info(
            "workspace_read_file: cluster=%s session_id=%s filename=%s max_lines=%s workspace_path=%s",
            request.cluster, request.session_id, request.remote_filename, request.max_lines,
            request.workspace_path,
        )
        transport = await _get_transport_for_cluster(request.cluster)
        ssh = _require_ssh_transport(transport)

        if request.workspace_path:
            workspace_dir = request.workspace_path
        else:
            workspace_dir = await _resolve_workspace_dir(ssh, request.session_id)
        remote_path = f"{workspace_dir}/{request.remote_filename}"

        # Build the read command
        if request.max_lines and request.offset_lines:
            cmd = f"tail -n +{request.offset_lines} {remote_path} | head -n {request.max_lines}"
        elif request.max_lines:
            cmd = f"tail -n {request.max_lines} {remote_path}"
        elif request.offset_lines:
            cmd = f"tail -n +{request.offset_lines} {remote_path}"
        else:
            cmd = f"head -n 10000 {remote_path}"

        logger.debug("Read command: %s", cmd)
        result = ssh._run(cmd, warn=True, timeout=request.timeout_seconds)

        if result.failed:
            logger.warning(
                "workspace_read_file failed: %s stderr=%s",
                remote_path, result.stderr.strip()[:200],
            )
            return {
                "status": "error",
                "cluster": request.cluster,
                "filename": request.remote_filename,
                "message": result.stderr.strip() or "File not found or not readable",
            }

        content = result.stdout
        line_count = content.count("\n")
        truncated = request.max_lines is not None and line_count >= request.max_lines

        logger.info(
            "workspace_read_file: %s — %d lines read (truncated=%s)",
            remote_path, line_count, truncated,
        )
        return {
            "status": "success",
            "cluster": request.cluster,
            "filename": request.remote_filename,
            "content": content,
            "line_count": line_count,
            "truncated": truncated,
        }

    except Exception as e:
        logger.error("workspace_read_file failed: %s", e, exc_info=True)
        return {
            "status": "error",
            "cluster": request.cluster,
            "filename": request.remote_filename,
            "message": str(e),
        }
