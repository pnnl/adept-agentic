"""
File Execution Tool for Sandbox MCP Server

This tool enables code execution with direct access to uploaded files.
Files are mounted read-only into the sandbox environment for processing.
"""
import os
import json
import tempfile
import shutil
from typing import Optional, Dict, Any, List
from pathlib import Path
import asyncio

from fastmcp import FastMCP, Context
from ...logger_config import get_logger
from ...core.session_api import get_session_context
from ..executor import get_process_pool

logger = get_logger(__name__)

# Base directory for uploaded files
SHARED_UPLOAD_DIR = os.environ.get("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")

# Check if llm-sandbox is available for enhanced file execution
try:
    from llm_sandbox import ArtifactSandboxSession
    LLM_SANDBOX_AVAILABLE = True
except ImportError:
    LLM_SANDBOX_AVAILABLE = False
    logger.warning("llm-sandbox not available for file execution")

class FileExecutionManager:
    """Manages code execution with file access in sandbox."""
    
    @staticmethod
    async def prepare_file_mounts(
        session_data: Dict[str, Any],
        file_ids: List[str],
        mcp_session_id: Optional[str] = None
    ) -> Dict[str, Dict[str, str]]:
        """
        Prepare file mounts for sandbox execution.
        
        Returns mapping of file_id to mount info.
        """
        mounts = {}
        
        # Get uploaded files from session
        uploaded_files = session_data.get("uploaded_files", {})
        if not uploaded_files:
            # Fallback to legacy key
            uploaded_files = session_data.get("uploaded_csv_files", {})
        
        for file_id in file_ids:
            if file_id not in uploaded_files:
                logger.warning(f"File {file_id} not found in session")
                continue
            
            # Determine source file path
            if mcp_session_id:
                source_path = os.path.join(SHARED_UPLOAD_DIR, "sessions", mcp_session_id, file_id)
            else:
                source_path = os.path.join(SHARED_UPLOAD_DIR, file_id)
            
            if not os.path.exists(source_path):
                logger.warning(f"File not found at {source_path}")
                continue
            
            # Mount path in sandbox (read-only)
            file_info = uploaded_files[file_id]
            original_name = file_info.get("original_filename", file_id)
            mount_path = f"/data/{original_name}"
            
            mounts[file_id] = {
                "source": source_path,
                "target": mount_path,
                "original_name": original_name
            }
        
        return mounts
    
    @staticmethod
    async def execute_with_files(
        code: str,
        language: str,
        file_mounts: Dict[str, Dict[str, str]],
        mcp_session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute code with mounted files in sandbox.

        Uses ProcessPoolExecutor to avoid blocking the event loop during
        sandbox session creation and code execution.
        """
        try:
            if not LLM_SANDBOX_AVAILABLE:
                return {
                    "success": False,
                    "error": "llm-sandbox not available for file execution",
                    "execution_type": "with_files"
                }

            session_params = {
                "lang": language,
                "keep_template": True,
                "verbose": True,
            }

            # Prepare code with file paths
            file_paths_comment = "# Available files:\n"
            for file_id, mount_info in file_mounts.items():
                file_paths_comment += f"# - {mount_info['original_name']}: {mount_info['target']}\n"

            if language == "python":
                full_code = f"{file_paths_comment}\n{code}"
            else:
                full_code = code

            # Prepare file copy operations as picklable tuples
            file_copies = [
                (mount_info["source"], "data", mount_info["original_name"])
                for mount_info in file_mounts.values()
            ]

            # Execute in ProcessPoolExecutor to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            worker_result = await loop.run_in_executor(
                get_process_pool(),
                _execute_file_in_process,
                session_params,
                full_code,
                file_copies,
            )

            if worker_result.get("success"):
                return {
                    "success": True,
                    "output": worker_result.get("output", ""),
                    "files_used": list(file_mounts.keys()),
                    "execution_type": "with_files",
                }
            else:
                return {
                    "success": False,
                    "error": worker_result.get("error", "Unknown error"),
                    "execution_type": "with_files",
                }

        except Exception as e:
            logger.error(f"Error executing code with files: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "execution_type": "with_files"
            }

def _execute_file_in_process(
    session_params: dict, full_code: str, file_copies: list
) -> dict:
    """
    Runs in a ProcessPoolExecutor worker. Creates sandbox session,
    copies files to temp directory, executes code, and returns result.

    Only picklable arguments (dict, str, list) cross the process boundary.

    Args:
        session_params: kwargs for ArtifactSandboxSession constructor
        full_code: Code string to execute
        file_copies: List of (source_path, target_subdir, target_name) tuples

    Returns:
        dict with keys: success (bool), output (str), error (str or None)
    """
    import tempfile
    import shutil
    from llm_sandbox import ArtifactSandboxSession

    session = ArtifactSandboxSession(**session_params)
    temp_dir = tempfile.mkdtemp(prefix="sandbox_files_")
    try:
        for source, target_subdir, target_name in file_copies:
            target_dir = os.path.join(temp_dir, target_subdir)
            os.makedirs(target_dir, exist_ok=True)
            shutil.copy2(source, os.path.join(target_dir, target_name))

        result = session.run(full_code)

        return {
            "success": True,
            "output": result.text if hasattr(result, "text") else str(result),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def register_tools(mcp: FastMCP):
    """Register file execution tools with the FastMCP server."""
    
    @mcp.tool()
    async def execute_code_with_file(
        ctx: Context,
        code: str,
        file_ids: str,  # Comma-separated list of file IDs
        language: str = "python",
        description: Optional[str] = None,
        mcp_session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute code in sandbox with direct access to uploaded files.
        
        This tool mounts uploaded files into the sandbox environment, allowing
        code to read and process them directly without manual file operations.
        
        Args:
            code: The code to execute
            file_ids: Comma-separated list of file IDs to make available
            language: Programming language (python, javascript, bash, etc.)
            description: Optional description of what the code does
            mcp_session_id: Session ID for file access
        
        Returns:
            Execution results including output and any errors
        
        Example:
            code = '''
            import pandas as pd
            df = pd.read_csv('/data/sales_data.csv')
            print(df.describe())
            print(f"Total sales: ${df['amount'].sum():,.2f}")
            '''
            result = await execute_code_with_file(
                ctx=ctx,
                code=code,
                file_ids="file-uuid-123",
                language="python"
            )
        """
        try:
            # Parse file IDs
            file_id_list = [fid.strip() for fid in file_ids.split(",") if fid.strip()]
            
            if not file_id_list:
                return {
                    "error": "No file IDs provided. Please specify at least one file."
                }
            
            # Get session context
            session_data = await get_session_context(mcp_session_id) if mcp_session_id else {}
            
            # Prepare file mounts
            file_mounts = await FileExecutionManager.prepare_file_mounts(
                session_data, file_id_list, mcp_session_id
            )
            
            if not file_mounts:
                return {
                    "error": f"No valid files found for IDs: {file_ids}",
                    "hint": "Use ListUploadedFiles to see available files"
                }
            
            # Execute code with mounted files
            result = await FileExecutionManager.execute_with_files(
                code, language, file_mounts, mcp_session_id
            )
            
            # Add execution metadata
            result["metadata"] = {
                "language": language,
                "file_count": len(file_mounts),
                "files": [
                    {
                        "id": fid,
                        "name": info["original_name"],
                        "path": info["target"]
                    }
                    for fid, info in file_mounts.items()
                ]
            }
            
            if description:
                result["description"] = description
            
            await ctx.info(f"Executed {language} code with {len(file_mounts)} file(s)")
            return result
            
        except Exception as e:
            logger.error(f"Error in execute_code_with_file: {e}", exc_info=True)
            await ctx.error(f"Failed to execute code with files: {e}")
            return {"error": str(e)}
    
    @mcp.tool()
    async def analyze_data_file(
        ctx: Context,
        file_id: str,
        analysis_type: str = "summary",
        custom_code: Optional[str] = None,
        mcp_session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze an uploaded data file using predefined or custom analysis.
        
        Args:
            file_id: The ID of the file to analyze
            analysis_type: Type of analysis (summary, correlation, visualization, custom)
            custom_code: Custom analysis code (required if analysis_type is "custom")
            mcp_session_id: Session ID for context
        
        Returns:
            Analysis results including statistics, insights, or visualizations
        
        Predefined Analysis Types:
            - summary: Basic statistics and data overview
            - correlation: Correlation matrix for numeric columns
            - visualization: Generate basic plots (histogram, scatter)
            - custom: Run custom analysis code
        """
        try:
            # Get session context
            session_data = await get_session_context(mcp_session_id) if mcp_session_id else {}
            
            # Get file info
            uploaded_files = session_data.get("uploaded_files", {})
            if not uploaded_files:
                uploaded_files = session_data.get("uploaded_csv_files", {})
            
            if file_id not in uploaded_files:
                return {
                    "error": f"File {file_id} not found. Use ListUploadedFiles to see available files."
                }
            
            file_info = uploaded_files[file_id]
            filename = file_info.get("original_filename", "data.csv")
            
            # Generate analysis code based on type
            if analysis_type == "summary":
                code = f'''
import pandas as pd
import numpy as np

# Load the data
df = pd.read_csv('/data/{filename}')

print("=== Data Summary ===")
print(f"Shape: {{df.shape}}")
print(f"Columns: {{list(df.columns)}}")
print()

print("=== Data Types ===")
print(df.dtypes)
print()

print("=== Basic Statistics ===")
print(df.describe())
print()

print("=== Missing Values ===")
print(df.isnull().sum())
print()

print("=== First 5 Rows ===")
print(df.head())
'''
            
            elif analysis_type == "correlation":
                code = f'''
import pandas as pd
import numpy as np

df = pd.read_csv('/data/{filename}')

# Select numeric columns
numeric_cols = df.select_dtypes(include=[np.number]).columns

if len(numeric_cols) > 1:
    print("=== Correlation Matrix ===")
    corr_matrix = df[numeric_cols].corr()
    print(corr_matrix)
    
    print("\\n=== Highly Correlated Pairs (|r| > 0.7) ===")
    high_corr = []
    for i in range(len(corr_matrix.columns)):
        for j in range(i+1, len(corr_matrix.columns)):
            if abs(corr_matrix.iloc[i, j]) > 0.7:
                high_corr.append((
                    corr_matrix.columns[i],
                    corr_matrix.columns[j],
                    corr_matrix.iloc[i, j]
                ))
    
    if high_corr:
        for col1, col2, corr in high_corr:
            print(f"{{col1}} <-> {{col2}}: {{corr:.3f}}")
    else:
        print("No highly correlated pairs found")
else:
    print("Not enough numeric columns for correlation analysis")
'''
            
            elif analysis_type == "visualization":
                code = f'''
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

df = pd.read_csv('/data/{filename}')

# Create figure with subplots
fig, axes = plt.subplots(2, 2, figsize=(12, 10))
fig.suptitle('Data Visualization: {filename}')

# 1. Numeric distributions
numeric_cols = df.select_dtypes(include=[np.number]).columns
if len(numeric_cols) > 0:
    col = numeric_cols[0]
    axes[0, 0].hist(df[col].dropna(), bins=20, edgecolor='black')
    axes[0, 0].set_title(f'Distribution of {{col}}')
    axes[0, 0].set_xlabel(col)
    axes[0, 0].set_ylabel('Frequency')

# 2. Missing data pattern  
missing = df.isnull().sum()
if missing.sum() > 0:
    missing_pct = (missing / len(df)) * 100
    missing_pct = missing_pct[missing_pct > 0]
    axes[0, 1].bar(range(len(missing_pct)), missing_pct.values)
    axes[0, 1].set_xticks(range(len(missing_pct)))
    axes[0, 1].set_xticklabels(missing_pct.index, rotation=45, ha='right')
    axes[0, 1].set_title('Missing Data (%)')
    axes[0, 1].set_ylabel('Percentage')

# 3. Correlation heatmap (if applicable)
if len(numeric_cols) > 1:
    corr = df[numeric_cols].corr()
    im = axes[1, 0].imshow(corr, cmap='coolwarm', vmin=-1, vmax=1)
    axes[1, 0].set_xticks(range(len(corr.columns)))
    axes[1, 0].set_yticks(range(len(corr.columns)))
    axes[1, 0].set_xticklabels(corr.columns, rotation=45, ha='right')
    axes[1, 0].set_yticklabels(corr.columns)
    axes[1, 0].set_title('Correlation Heatmap')
    plt.colorbar(im, ax=axes[1, 0])

# 4. Data types distribution
dtype_counts = df.dtypes.value_counts()
axes[1, 1].pie(dtype_counts.values, labels=dtype_counts.index.astype(str), autopct='%1.1f%%')
axes[1, 1].set_title('Data Types Distribution')

plt.tight_layout()
plt.savefig('/tmp/analysis.png', dpi=100, bbox_inches='tight')
print("Visualization saved to /tmp/analysis.png")

# Also print summary
print(f"\\nDataset: {filename}")
print(f"Rows: {{len(df)}}, Columns: {{len(df.columns)}}")
print(f"Numeric columns: {{list(numeric_cols)}}")
'''
            
            elif analysis_type == "custom":
                if not custom_code:
                    return {
                        "error": "Custom code is required for custom analysis type"
                    }
                code = custom_code
            
            else:
                return {
                    "error": f"Unknown analysis type: {analysis_type}",
                    "valid_types": ["summary", "correlation", "visualization", "custom"]
                }
            
            # Execute analysis
            result = await execute_code_with_file(
                ctx=ctx,
                code=code,
                file_ids=file_id,
                language="python",
                description=f"{analysis_type} analysis of {filename}",
                mcp_session_id=mcp_session_id
            )
            
            await ctx.info(f"Completed {analysis_type} analysis of {filename}")
            return result
            
        except Exception as e:
            logger.error(f"Error in analyze_data_file: {e}", exc_info=True)
            await ctx.error(f"Failed to analyze file: {e}")
            return {"error": str(e)}
    
    logger.info("File execution tools registered with sandbox MCP server")