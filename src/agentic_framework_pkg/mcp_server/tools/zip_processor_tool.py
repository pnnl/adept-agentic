"""
ZIP Archive Processor Tool for RAGFlow

⚠️ DEPRECATED / NOT REGISTERED ⚠️
This tool is NOT currently registered in mcp_server/main.py and is not active.
It has a broken import (file_id_manager module does not exist).

Status: Preserved for potential future use but not functional.
Issue: Missing file_id_manager.py module dependency.

Handles extraction and bulk processing of ZIP archives containing documents.
Supports automatic file type detection, session isolation, and batch ingestion.
"""

import os
import json
import zipfile
import tempfile
import asyncio
from typing import Dict, List, Any, Optional
from pathlib import Path
import logging

from mcp import Tool
# BROKEN IMPORT: file_id_manager module does not exist (2026-01-21)
# from ..file_id_manager import FileIDManager
from ..file_type_detector import FileTypeDetector
try:
    from agentic_framework_pkg.core.knowledge_bases.ragflow import RAGFlowClient, RAGFlowBackend
except ImportError:
    RAGFlowClient = None
    RAGFlowBackend = None

logger = logging.getLogger(__name__)


class ZipProcessorTool:
    """Tool for processing ZIP archives and bulk document ingestion."""

    def __init__(self, mcp: Tool):
        """Initialize the ZIP processor tool."""
        self.mcp = mcp
        # DISABLED: FileIDManager import is broken (module does not exist)
        # self.file_manager = FileIDManager()
        self.file_manager = None  # Placeholder until file_id_manager.py is created
        self.file_detector = FileTypeDetector()
        self.ragflow_client = None
        self.ragflow_backend = None

        # Supported file extensions for processing
        self.supported_extensions = {
            '.pdf', '.txt', '.md', '.docx', '.doc',
            '.csv', '.tsv', '.json', '.xml',
            '.png', '.jpg', '.jpeg', '.gif', '.bmp',
            '.html', '.htm', '.rtf'
        }

    async def _init_ragflow(self):
        """Lazy initialization of RAGFlow clients."""
        if not self.ragflow_client:
            self.ragflow_client = RAGFlowClient()
        if not self.ragflow_backend:
            self.ragflow_backend = RAGFlowBackend()

    @Tool()
    async def process_zip_archive(
        self,
        file_id: str,
        kb_id: str,
        extract_path: Optional[str] = None,
        batch_size: int = 10,
        process_nested_zips: bool = False,
        file_type_filter: Optional[List[str]] = None,
        auto_create_kb: bool = True,
        session_id: Optional[str] = None
    ) -> str:
        """
        Extract and process all documents from a ZIP archive.

        Args:
            file_id: ID of the uploaded ZIP file
            kb_id: Knowledge base ID to ingest documents into
            extract_path: Optional path to extract files (defaults to temp dir)
            batch_size: Number of files to process in parallel
            process_nested_zips: Whether to recursively process nested ZIP files
            file_type_filter: Optional list of file extensions to process (e.g., ['.pdf', '.txt'])
            auto_create_kb: Automatically create KB if it doesn't exist
            session_id: Optional session ID for isolation

        Returns:
            JSON string with processing summary and results
        """
        try:
            await self._init_ragflow()

            # Check if file_manager is available
            if self.file_manager is None:
                return json.dumps({
                    "success": False,
                    "error": "zip_processor_tool is not functional: file_id_manager module missing"
                })

            # Get the ZIP file path
            zip_path = self.file_manager.get_file_path(file_id)
            if not zip_path or not os.path.exists(zip_path):
                return json.dumps({
                    "success": False,
                    "error": f"ZIP file not found: {file_id}"
                })

            # Verify it's a ZIP file
            if not zipfile.is_zipfile(zip_path):
                return json.dumps({
                    "success": False,
                    "error": f"File {file_id} is not a valid ZIP archive"
                })

            # Create session-isolated extraction directory
            if extract_path:
                extract_dir = Path(extract_path)
            else:
                session_dir = session_id or "default"
                extract_dir = Path(f"/tmp/zip_extract/{session_dir}/{file_id}")

            extract_dir.mkdir(parents=True, exist_ok=True)

            # Extract ZIP contents
            extracted_files = []
            skipped_files = []
            errors = []

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Get list of files in ZIP
                zip_contents = zip_ref.namelist()
                logger.info(f"ZIP contains {len(zip_contents)} files")

                # Extract all files
                zip_ref.extractall(extract_dir)

                # Process extracted files
                for file_name in zip_contents:
                    file_path = extract_dir / file_name

                    # Skip directories
                    if file_path.is_dir():
                        continue

                    # Get file extension
                    file_ext = file_path.suffix.lower()

                    # Apply file type filter if specified
                    if file_type_filter and file_ext not in file_type_filter:
                        skipped_files.append({
                            "file": file_name,
                            "reason": f"File type {file_ext} not in filter"
                        })
                        continue

                    # Skip unsupported file types
                    if file_ext not in self.supported_extensions:
                        skipped_files.append({
                            "file": file_name,
                            "reason": f"Unsupported file type {file_ext}"
                        })
                        continue

                    # Handle nested ZIPs if enabled
                    if file_ext == '.zip' and process_nested_zips:
                        nested_result = await self._process_nested_zip(
                            file_path, kb_id, batch_size, file_type_filter, session_id
                        )
                        extracted_files.append({
                            "file": file_name,
                            "type": "nested_zip",
                            "result": nested_result
                        })
                        continue

                    extracted_files.append({
                        "file": file_name,
                        "path": str(file_path),
                        "size": file_path.stat().st_size,
                        "type": file_ext
                    })

            # Check if KB exists, create if needed
            if auto_create_kb:
                kb_exists = await self._ensure_kb_exists(kb_id)
                if not kb_exists:
                    logger.info(f"Creating knowledge base: {kb_id}")
                    await self.ragflow_backend.create_knowledge_base(
                        name=kb_id,
                        description=f"Auto-created from ZIP: {os.path.basename(zip_path)}"
                    )

            # Process files in batches
            processed_files = []
            failed_files = []

            for i in range(0, len(extracted_files), batch_size):
                batch = extracted_files[i:i + batch_size]

                # Process batch in parallel
                batch_tasks = []
                for file_info in batch:
                    if "path" in file_info:  # Skip nested ZIP results
                        batch_tasks.append(
                            self._ingest_file(
                                file_info["path"],
                                kb_id,
                                file_info
                            )
                        )

                # Wait for batch to complete
                if batch_tasks:
                    batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

                    for file_info, result in zip(batch, batch_results):
                        if isinstance(result, Exception):
                            failed_files.append({
                                "file": file_info["file"],
                                "error": str(result)
                            })
                            errors.append(f"Failed to process {file_info['file']}: {result}")
                        else:
                            processed_files.append({
                                "file": file_info["file"],
                                "doc_id": result,
                                "size": file_info["size"],
                                "type": file_info["type"]
                            })

            # Calculate statistics
            total_size = sum(f["size"] for f in processed_files)
            avg_size = total_size / len(processed_files) if processed_files else 0

            # Clean up extraction directory (optional)
            # import shutil
            # shutil.rmtree(extract_dir)

            # Prepare summary
            summary = {
                "success": True,
                "zip_file": os.path.basename(zip_path),
                "kb_id": kb_id,
                "statistics": {
                    "total_files": len(zip_contents),
                    "processed": len(processed_files),
                    "failed": len(failed_files),
                    "skipped": len(skipped_files),
                    "total_size_bytes": total_size,
                    "average_size_bytes": avg_size
                },
                "processed_files": processed_files,
                "failed_files": failed_files,
                "skipped_files": skipped_files,
                "extraction_path": str(extract_dir)
            }

            if errors:
                summary["errors"] = errors

            logger.info(
                f"ZIP processing complete: {len(processed_files)} processed, "
                f"{len(failed_files)} failed, {len(skipped_files)} skipped"
            )

            return json.dumps(summary, indent=2)

        except Exception as e:
            logger.error(f"Failed to process ZIP archive: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })

    async def _ingest_file(
        self,
        file_path: str,
        kb_id: str,
        metadata: Dict[str, Any]
    ) -> str:
        """
        Ingest a single file into the knowledge base.

        Args:
            file_path: Path to the file
            kb_id: Knowledge base ID
            metadata: File metadata

        Returns:
            Document ID from RAGFlow
        """
        try:
            # Use RAGFlow client with adaptive chunking
            file_size = os.path.getsize(file_path)
            file_type = metadata.get("type", "").lstrip(".")

            # Calculate optimal chunk size
            chunk_size, chunk_overlap = self.ragflow_client.calculate_optimal_chunk_size(
                file_size, file_type
            )

            # Ingest document
            doc_id = await self.ragflow_client.ingest_document(
                kb_id=kb_id,
                file_path=file_path,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                metadata=metadata
            )

            logger.info(f"Ingested {file_path} as document {doc_id}")
            return doc_id

        except Exception as e:
            logger.error(f"Failed to ingest {file_path}: {e}")
            raise

    async def _process_nested_zip(
        self,
        zip_path: Path,
        kb_id: str,
        batch_size: int,
        file_type_filter: Optional[List[str]],
        session_id: Optional[str]
    ) -> Dict[str, Any]:
        """Process a nested ZIP file recursively."""
        # Check if file_manager is available
        if self.file_manager is None:
            return {
                "success": False,
                "error": "zip_processor_tool is not functional: file_id_manager module missing"
            }

        # Register the nested ZIP temporarily
        temp_file_id = f"nested_{zip_path.stem}"
        self.file_manager.register_file(temp_file_id, str(zip_path))

        # Process recursively
        result = await self.process_zip_archive(
            file_id=temp_file_id,
            kb_id=kb_id,
            batch_size=batch_size,
            process_nested_zips=True,
            file_type_filter=file_type_filter,
            session_id=session_id
        )

        return json.loads(result)

    async def _ensure_kb_exists(self, kb_id: str) -> bool:
        """Check if knowledge base exists."""
        try:
            kb = await self.ragflow_backend.get_knowledge_base(kb_id)
            return kb is not None
        except:
            return False


def register_tool(mcp: Tool):
    """Register the ZIP processor tool with MCP."""
    tool = ZipProcessorTool(mcp)

    @mcp.tool()
    async def process_zip_archive(
        file_id: str,
        kb_id: str,
        extract_path: Optional[str] = None,
        batch_size: int = 10,
        process_nested_zips: bool = False,
        file_type_filter: Optional[List[str]] = None,
        auto_create_kb: bool = True,
        session_id: Optional[str] = None
    ) -> str:
        """
        Extract and process all documents from a ZIP archive for RAGFlow ingestion.

        This tool automatically:
        - Extracts ZIP contents to a session-isolated directory
        - Detects file types and filters unsupported formats
        - Uses adaptive chunking based on file size
        - Processes files in batches for efficiency
        - Handles nested ZIP files (if enabled)
        - Creates the knowledge base if it doesn't exist

        Args:
            file_id: ID of the uploaded ZIP file
            kb_id: Knowledge base ID to ingest documents into
            extract_path: Optional custom extraction path
            batch_size: Number of files to process in parallel (default: 10)
            process_nested_zips: Process ZIP files within the archive (default: False)
            file_type_filter: List of extensions to process (e.g., ['.pdf', '.txt'])
            auto_create_kb: Create KB if it doesn't exist (default: True)
            session_id: Session ID for isolation

        Returns:
            JSON summary with processing statistics and results

        Example:
            ```python
            result = await process_zip_archive(
                file_id="file_abc123",
                kb_id="research_papers",
                batch_size=5,
                file_type_filter=['.pdf', '.txt']
            )
            ```
        """
        return await tool.process_zip_archive(
            file_id=file_id,
            kb_id=kb_id,
            extract_path=extract_path,
            batch_size=batch_size,
            process_nested_zips=process_nested_zips,
            file_type_filter=file_type_filter,
            auto_create_kb=auto_create_kb,
            session_id=session_id
        )

    logger.info("ZIP processor tool registered")