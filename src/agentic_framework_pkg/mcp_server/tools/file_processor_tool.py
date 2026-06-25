"""
File Processing Tool for MCP Server

This tool provides comprehensive file processing capabilities including:
- Automatic file type detection
- RAG processing for documents
- DataFrame conversion for structured data
- SQL transformation for analysis
- Text extraction and cleaning
"""
import os
import json
import pandas as pd
import mimetypes
from pathlib import Path
from typing import Dict, Any, Optional, Literal, List
import tempfile
import shutil
from datetime import datetime

from fastmcp import FastMCP, Context
from ...logger_config import get_logger
from ..state_manager import get_session_context, update_session_context

logger = get_logger(__name__)

# File type mappings
STRUCTURED_TYPES = {'.csv', '.tsv', '.xlsx', '.xls', '.json', '.jsonl', '.parquet'}
DOCUMENT_TYPES = {'.pdf', '.txt', '.md', '.docx', '.doc', '.html', '.xml', '.rtf'}
IMAGE_TYPES = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.svg'}
CODE_TYPES = {'.py', '.js', '.java', '.cpp', '.c', '.h', '.go', '.rs', '.rb', '.php', '.ts'}

class FileProcessor:
    """Handles various file processing operations."""
    
    @staticmethod
    def detect_file_type(file_path: str) -> Dict[str, Any]:
        """Detect file type and suggest processing methods."""
        path = Path(file_path)
        extension = path.suffix.lower()
        mime_type, _ = mimetypes.guess_type(file_path)

        # Determine category and suggested processing
        if extension in STRUCTURED_TYPES:
            category = "structured"
            suggested_processing = ["dataframe", "sql", "rag"]
        elif extension in DOCUMENT_TYPES:
            category = "document"
            suggested_processing = ["rag", "text"]
        elif extension in IMAGE_TYPES:
            category = "image"
            suggested_processing = ["image", "text"]
        elif extension in CODE_TYPES:
            category = "code"
            suggested_processing = ["text", "rag"]
        else:
            category = "unknown"
            suggested_processing = ["text"]

        return {
            "filename": path.name,
            "extension": extension,
            "mime_type": mime_type,
            "category": category,
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "suggested_processing": suggested_processing
        }

    @staticmethod
    def detect_file_type_with_fallback(name_path: str, actual_path: str) -> Dict[str, Any]:
        """
        Detect file type using filename for extension but actual path for stats.

        Args:
            name_path: Path with original filename (for extension detection)
            actual_path: Actual file path on disk (for file stats)

        Returns:
            File type information
        """
        name_path_obj = Path(name_path)
        actual_path_obj = Path(actual_path)
        extension = name_path_obj.suffix.lower()
        mime_type, _ = mimetypes.guess_type(name_path)

        # Determine category and suggested processing
        if extension in STRUCTURED_TYPES:
            category = "structured"
            suggested_processing = ["dataframe", "sql", "rag"]
        elif extension in DOCUMENT_TYPES:
            category = "document"
            suggested_processing = ["rag", "text"]
        elif extension in IMAGE_TYPES:
            category = "image"
            suggested_processing = ["image", "text"]
        elif extension in CODE_TYPES:
            category = "code"
            suggested_processing = ["text", "rag"]
        else:
            category = "unknown"
            suggested_processing = ["text"]

        return {
            "filename": name_path_obj.name,
            "extension": extension,
            "mime_type": mime_type,
            "category": category,
            "size_bytes": actual_path_obj.stat().st_size if actual_path_obj.exists() else 0,
            "suggested_processing": suggested_processing
        }
    
    @staticmethod
    async def process_as_dataframe(file_path: str) -> Dict[str, Any]:
        """Process file as a pandas DataFrame."""
        try:
            extension = Path(file_path).suffix.lower()
            
            # Load based on file type
            if extension in ['.csv', '.tsv']:
                delimiter = '\t' if extension == '.tsv' else ','
                df = pd.read_csv(file_path, delimiter=delimiter)
            elif extension in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path)
            elif extension == '.json':
                df = pd.read_json(file_path)
            elif extension == '.jsonl':
                df = pd.read_json(file_path, lines=True)
            elif extension == '.parquet':
                df = pd.read_parquet(file_path)
            else:
                return {"error": f"Unsupported file type for DataFrame: {extension}"}
            
            # Generate basic statistics
            stats = {
                "shape": df.shape,
                "columns": df.columns.tolist(),
                "dtypes": df.dtypes.astype(str).to_dict(),
                "null_counts": df.isnull().sum().to_dict(),
                "memory_usage": df.memory_usage(deep=True).sum()
            }
            
            # Sample data
            sample = df.head(5).to_dict(orient='records')
            
            # Numeric statistics if applicable
            numeric_stats = {}
            numeric_cols = df.select_dtypes(include=['number']).columns
            if len(numeric_cols) > 0:
                numeric_stats = df[numeric_cols].describe().to_dict()
            
            return {
                "success": True,
                "stats": stats,
                "sample": sample,
                "numeric_stats": numeric_stats
            }
            
        except Exception as e:
            logger.error(f"Error processing file as DataFrame: {e}")
            return {"error": str(e)}
    
    @staticmethod
    async def process_as_text(file_path: str) -> Dict[str, Any]:
        """Extract text content from file."""
        try:
            extension = Path(file_path).suffix.lower()
            
            # Text extraction based on file type
            if extension in ['.txt', '.md', '.csv', '.tsv', '.log']:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            elif extension == '.pdf':
                # Use PyMuPDF for PDF extraction
                import fitz
                doc = fitz.open(file_path)
                content = ""
                for page in doc:
                    content += page.get_text()
            elif extension in ['.docx', '.doc']:
                # Use python-docx for Word documents
                from docx import Document
                doc = Document(file_path)
                content = "\n".join([p.text for p in doc.paragraphs])
            elif extension in ['.html', '.xml']:
                from bs4 import BeautifulSoup
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    soup = BeautifulSoup(f, 'html.parser')
                    content = soup.get_text()
            else:
                # Default text reading
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            
            # Basic text statistics
            lines = content.split('\n')
            words = content.split()
            
            return {
                "success": True,
                "content": content[:10000],  # First 10K chars
                "full_content_available": len(content) > 10000,
                "stats": {
                    "total_chars": len(content),
                    "total_lines": len(lines),
                    "total_words": len(words),
                    "avg_line_length": len(content) / len(lines) if lines else 0
                }
            }
            
        except Exception as e:
            logger.error(f"Error extracting text from file: {e}")
            return {"error": str(e)}
    
    @staticmethod
    async def prepare_for_rag(file_path: str, chunk_size: int = 1000, overlap: int = 200) -> Dict[str, Any]:
        """Prepare file for RAG indexing by chunking text."""
        try:
            # First extract text
            text_result = await FileProcessor.process_as_text(file_path)
            if "error" in text_result:
                return text_result
            
            content = text_result.get("content", "")
            if text_result.get("full_content_available"):
                # Re-read full content if truncated
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            
            # Chunk the text
            chunks = []
            for i in range(0, len(content), chunk_size - overlap):
                chunk = content[i:i + chunk_size]
                if chunk.strip():  # Skip empty chunks
                    chunks.append({
                        "text": chunk,
                        "start": i,
                        "end": min(i + chunk_size, len(content)),
                        "chunk_id": len(chunks)
                    })
            
            return {
                "success": True,
                "chunks": chunks,
                "total_chunks": len(chunks),
                "chunk_size": chunk_size,
                "overlap": overlap
            }
            
        except Exception as e:
            logger.error(f"Error preparing file for RAG: {e}")
            return {"error": str(e)}

async def process_file_advanced(
    file_id: str,
    processing_type: Literal["auto", "rag", "sql", "dataframe", "text", "image"] = "auto",
    custom_instructions: Optional[str] = None,
    mcp_session_id: Optional[str] = None
) -> str:
        """
        Process an uploaded file based on its type and user requirements.

        CRITICAL: This is the CORRECT tool for code files (.py, .js, .java, .cpp, .go, etc.)
        ProcessFileAdvanced supports ALL file types including CODE_TYPES that ProcessUploadedFile rejects.

        This tool provides comprehensive file processing with automatic file type detection:
        - Structured data: CSV, Excel, JSON, Parquet → DataFrames or SQL
        - Documents: PDF, DOCX, TXT, HTML, XML → Text extraction or RAG indexing
        - Code files: .py, .js, .java, .cpp, .go, .rs, .rb, .php, .ts → Text extraction or RAG indexing
        - Images: PNG, JPG, GIF, etc. → Metadata extraction (future enhancement)

        Perfect for:
        - Processing code files for documentation or search
        - Converting documents to queryable formats
        - Preparing files for RAG indexing
        - Extracting structured data from various formats

        Args:
            file_id: The ID of the uploaded file to process (REQUIRED)
                     Example: "file-abc123" or "550e8400-e29b-41d4-a716-446655440000"
                     Use ListUploadedFiles to see available file_ids
            processing_type: Type of processing to apply (default: "auto")
                - auto: Automatically detect and apply appropriate processing based on file extension
                - rag: Prepare for RAG indexing (chunk text for embeddings)
                - sql: Convert to SQL-queryable format (for structured data like CSV/Excel)
                - dataframe: Load as pandas DataFrame for analysis (structured data)
                - text: Extract and return text content (all file types)
                - image: Extract image metadata (future implementation)
            custom_instructions: Optional custom processing instructions for specialized handling
                                 Example: "Extract only function definitions" or "Parse as UTF-16"
            mcp_session_id: Session ID for context isolation (auto-injected by framework)

        Returns:
            JSON with processing results including:
            - file_id: The processed file ID
            - filename: Original filename
            - file_type: Detected file type info (category, extension, mime_type)
            - processing_type: Applied processing type
            - Result data based on processing_type:
              * dataframe: DataFrame statistics, sample data, column info
              * text: Extracted text content, character/word/line counts
              * rag: Text chunks prepared for embedding
              * sql: SQL transformation status
              * image: Metadata (future)

        Examples:
            # Auto-process Python file (detects code, extracts text)
            process_file_advanced(
                file_id="file-script-001",
                processing_type="auto"
            )

            # Prepare document for RAG indexing
            process_file_advanced(
                file_id="file-research-paper",
                processing_type="rag"
            )

            # Load CSV as DataFrame for analysis
            process_file_advanced(
                file_id="file-data-csv",
                processing_type="dataframe"
            )

        Related Tools:
            - ListUploadedFiles: Get available file_ids
            - ProcessFilesBatch: Process multiple files in parallel
            - ProcessUploadedFile: Older tool (does NOT support code files)
    """
        # DEBUG LOGGING: Track when process_file_advanced is called (CORRECT tool for .py files)
        logger.info(
            f"[TOOL_SELECTION_DEBUG] process_file_advanced CALLED: "
            f"file_id={file_id}, processing_type={processing_type}, "
            f"session={mcp_session_id}"
        )

        try:
            # Get session context
            session_data = await get_session_context(mcp_session_id) if mcp_session_id else {}
        
            # Check both new and legacy keys for uploaded files
            uploaded_files = session_data.get("uploaded_files", {})
            if not uploaded_files:
                uploaded_files = session_data.get("uploaded_csv_files", {})
        
            if file_id not in uploaded_files:
                return json.dumps({
                    "error": f"File {file_id} not found in session. Use ListUploadedFiles to see available files."
                })
        
            file_info = uploaded_files[file_id]
        
            # Enhanced file path resolution via shared resolver (reads Redis metadata + fallbacks)
            from .file_path_resolver import resolve_file_path
            resolved_path, paths_checked = await resolve_file_path(
                file_id=file_id,
                mcp_session_id=mcp_session_id,
                file_info=file_info,
            )

            if not resolved_path:
                logger.warning(f"File processor: File ID {file_id} not found. Paths checked: {paths_checked}")
                return json.dumps({
                    "error": f"File not found. Searched {len(paths_checked)} locations.",
                    "file_id": file_id,
                    "paths_checked": paths_checked,
                    "suggestions": [
                        "1. Use ListUploadedFiles tool to see available files",
                        "2. Verify the file ID is correct",
                        "3. Check if file was uploaded to current session",
                        "4. For direct paths, ensure file exists in container"
                    ]
                })

            file_path = resolved_path

            # Get original filename for type detection
            original_filename = file_info.get("original_filename") or file_info.get("filename")
            if not original_filename:
                # Fallback to file_id if no original filename
                original_filename = file_id
                logger.warning(f"No original filename found for {file_id}, using file_id for type detection")

            # Detect file type using original filename (for extension) but actual path (for file stats)
            # Create a temporary path with the original filename for extension detection
            temp_path_for_detection = os.path.join(os.path.dirname(file_path), original_filename)
            file_type_info = FileProcessor.detect_file_type_with_fallback(temp_path_for_detection, file_path)

            # Auto-detect processing type if needed
            if processing_type == "auto":
                if file_type_info["category"] == "structured":
                    processing_type = "dataframe"
                elif file_type_info["category"] == "document":
                    processing_type = "rag"
                else:
                    processing_type = "text"

            # Process based on type
            result = {
                "file_id": file_id,
                "filename": original_filename,
                "file_type": file_type_info,
                "processing_type": processing_type,
                "timestamp": datetime.now().isoformat()
            }
        
            if processing_type == "dataframe":
                process_result = await FileProcessor.process_as_dataframe(file_path)
                result["dataframe"] = process_result
            
            elif processing_type == "text":
                process_result = await FileProcessor.process_as_text(file_path)
                result["text"] = process_result
            
            elif processing_type == "rag":
                process_result = await FileProcessor.prepare_for_rag(file_path)
                result["rag"] = process_result
            
            elif processing_type == "sql":
                # For now, process as dataframe (SQL conversion will be added)
                process_result = await FileProcessor.process_as_dataframe(file_path)
                result["sql"] = {
                    "message": "SQL transformation coming soon. Data loaded as DataFrame.",
                    "dataframe": process_result
                }
            
            elif processing_type == "image":
                result["image"] = {
                    "message": "Image processing coming soon",
                    "metadata": file_type_info
                }
        
            # Store processing result in session for later use
            if mcp_session_id and "error" not in result:
                if "processed_files" not in session_data:
                    session_data["processed_files"] = {}
            
                session_data["processed_files"][file_id] = {
                    "processing_type": processing_type,
                    "processed_at": result["timestamp"],
                    "result_summary": {
                        k: v for k, v in result.items() 
                        if k not in ["text", "rag", "dataframe"]  # Don't store full data
                    }
                }
            
                await update_session_context(mcp_session_id, session_data)
        
            return json.dumps(result, indent=2, default=str)
        
        except Exception as e:
            logger.error(f"Error in process_uploaded_file: {e}", exc_info=True)
            return json.dumps({"error": str(e)})


def register_tools(mcp: FastMCP):
    """Register file processing tools with the MCP server."""
    mcp.tool()(process_file_advanced)
    logger.info("File processor tools registered.")