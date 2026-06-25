"""
This module provides the core Retrieval-Augmented Generation (RAG) tools for
the MCP server.

It handles the processing of various file types (CSV, Excel, PDF, DOCX, images),
extracts their content, generates embeddings, and stores them in a vector
database for querying.

Architectural Role:
-   **Executor Logic:** Contains the implementation for the `process_uploaded_file`
    and `query_file_content` tools, which are exposed via the MCP server.
-   **Content Extraction:** Implements various parsers (`_read_csv_to_texts`,
    `_read_pdf_to_texts`, etc.) to handle different document formats.
-   **Multi-Modal RAG:** Integrates with the NVIDIA NIM API for advanced document
    and image analysis, using a multi-modal model to extract text from complex
    PDFs and images. It includes a fallback to standard parsing if the NVIDIA
    service is unavailable or fails.
-   **Vector Store Interaction:** It uses the `VectorStoreManager` to abstract
    away the details of the vector database, allowing it to add and query
    documents and their embeddings.
"""
from fastmcp import FastMCP, Context
from ..state_manager import (
    get_session_context,
    update_session_context,
    create_session_if_not_exists,
    #add_embeddings_batch,
    #query_embeddings,
    # delete_embeddings # Import if needed for cleanup later
)
from ...core.llm_agnostic_layer import LLMAgnosticClient, LLMServiceError
import pandas as pd
import json
import uuid
import os
import numpy as np
from typing import List, Dict, Any, Optional
from pathlib import Path
import base64

import openpyxl # For .xlsx
from docx import Document as DocxDocument # For .docx
import fitz # PyMuPDF for .pdf

# Use the centralized logger # Removed TextPart import
from ...logger_config import get_logger
# Import common session helpers
# Import the new VectorStoreManager
from ..vector_store_manager import VectorStoreManager
# Assuming general_tools.py is the source for now, or a future common_utils.py
import openai
from .general_tools import get_stable_session_id, ensure_session_initialized
from .file_type_detector import ContentTypeDetector

logger = get_logger(__name__)

# This global instance will be set by the register_tools function.
# In a larger application, consider dependency injection.
_llm_client_instance: LLMAgnosticClient | None = None

# NVIDIA Configuration
NVIDIA_API_KEY_ENV_VAR = "NVIDIA_API_KEY"
NVIDIA_BASE_URL_ENV_VAR = "NVIDIA_API_BASE_URL"
NVIDIA_MULTI_MODAL_MODEL_ENV_VAR = "NVIDIA_MULTI_MODAL_MODEL_NAME"

_nvidia_api_key: Optional[str] = None
_nvidia_base_url: str = "https://integrate.api.nvidia.com/v1" # Default
_nvidia_model_name: str = "nvidia/llama-3.1-nemotron-nano-vl-8b-v1" # Default
_nvidia_async_client: Optional[openai.AsyncOpenAI] = None

IMAGE_MIME_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp'}


# cosine_similarity function is not used with ChromaDB, can be removed if not used elsewhere.
# def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
#     if np.linalg.norm(v1) == 0 or np.linalg.norm(v2) == 0: # Avoid division by zero
#         return 0.0
#     return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
TEXT_CHUNK_SIZE = 1000  # Characters per chunk for text documents
TEXT_CHUNK_OVERLAP = 100 # Overlap between chunks

def _read_csv_to_texts(file_path: str) -> List[str]:
    """Reads a CSV file and converts its rows to text strings."""
    df = pd.read_csv(file_path)
    texts = []
    for index, row in df.iterrows():
        text_content = ", ".join(f"{col}: {str(val)}" for col, val in row.astype(str).items())
        if text_content.strip():
            texts.append(text_content)
    return texts

def _read_excel_to_texts(file_path: str) -> List[str]:
    """Reads an Excel file (all sheets) and converts its rows to text strings."""
    xls = pd.ExcelFile(file_path)
    texts = []
    for sheet_name in xls.sheet_names:
        df = xls.parse(sheet_name)
        for index, row in df.iterrows():
            text_content = f"Sheet: {sheet_name}, Row: {index+2}, " + ", ".join(f"{col}: {str(val)}" for col, val in row.astype(str).items())
            if text_content.strip():
                texts.append(text_content)
    return texts

def _split_text_into_chunks(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """Splits a long text into smaller overlapping chunks."""
    if not text:
        return []
    
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - chunk_overlap
        if start >= len(text) and end < len(text): # Ensure last part is captured if loop condition makes it skip
            chunks.append(text[start:])
            break
    return [chunk for chunk in chunks if chunk.strip()]


def _read_docx_to_texts(file_path: str) -> List[str]:
    """Reads a DOCX file and extracts its text content, then splits into chunks."""
    doc = DocxDocument(file_path)
    full_text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
    return _split_text_into_chunks(full_text, TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP)

def _read_pdf_to_texts(file_path: str) -> List[str]:
    """Reads a PDF file, extracts text page by page, and splits into chunks."""
    texts = []
    try:
        with fitz.open(file_path) as doc:
            for page in doc:
                texts.extend(_split_text_into_chunks(page.get_text(), TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP))
    except Exception as e:
        logger.error(f"Error reading PDF file {file_path}: {e}", exc_info=True)
        raise # Re-raise to be caught by the caller
# Placeholder for other readers - you would implement these similarly:

def _read_txt_to_texts(file_path: str) -> List[str]:
    """Reads a plain text file and splits its content into chunks."""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        full_text = f.read()
    return _split_text_into_chunks(full_text, TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP)

def _read_latex_to_texts(file_path: str) -> List[str]:
    """Reads a LaTeX (.tex) file and splits its raw content into chunks.
    Note: This is a basic reader and will include LaTeX commands. More sophisticated parsing may be needed for cleaner text."""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        full_text = f.read()
    # A very basic attempt to remove some common inline math and simple commands - can be expanded
    # full_text = re.sub(r'\\([a-zA-Z]+(\{[^}]*\})?|[$].*?[$])', '', full_text)
    return _split_text_into_chunks(full_text, TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP)

def _read_xml_to_texts(file_path: str) -> List[str]:
    """Reads an XML file and extracts text content from all elements."""
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        # Recursively extract all text content from XML elements
        def extract_text(element, prefix=""):
            texts = []
            # Add element tag and attributes if present
            if element.tag:
                tag_info = f"{prefix}{element.tag}"
                if element.attrib:
                    attrs = ", ".join(f"{k}={v}" for k, v in element.attrib.items())
                    tag_info += f" ({attrs})"
                texts.append(tag_info)

            # Add element text
            if element.text and element.text.strip():
                texts.append(f"{prefix}  {element.text.strip()}")

            # Process children
            for child in element:
                texts.extend(extract_text(child, prefix + "  "))
                # Add tail text (text after child element)
                if child.tail and child.tail.strip():
                    texts.append(f"{prefix}  {child.tail.strip()}")

            return texts

        all_texts = extract_text(root)
        full_text = "\n".join(all_texts)
        return _split_text_into_chunks(full_text, TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP)

    except ET.ParseError as e:
        logger.warning(f"Failed to parse XML file {file_path}: {e}. Falling back to plain text.")
        # Fallback to reading as plain text if XML parsing fails
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            full_text = f.read()
        return _split_text_into_chunks(full_text, TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP)

def _read_json_to_texts(file_path: str) -> List[str]:
    """Reads a JSON file and converts it to readable text format."""
    import json

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Convert JSON to pretty-printed text
        full_text = json.dumps(data, indent=2, ensure_ascii=False)

        # If JSON is an array of objects, also create row-based representation
        if isinstance(data, list) and data and isinstance(data[0], dict):
            # Add a more readable representation for arrays of objects
            full_text += "\n\n=== Structured View ===\n"
            for i, item in enumerate(data):
                full_text += f"\n--- Record {i+1} ---\n"
                for key, value in item.items():
                    full_text += f"{key}: {value}\n"

        return _split_text_into_chunks(full_text, TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP)

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON file {file_path}: {e}. Falling back to plain text.")
        # Fallback to reading as plain text if JSON parsing fails
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            full_text = f.read()
        return _split_text_into_chunks(full_text, TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP)

# def _read_pptx_to_texts(file_path: str) -> List[str]:
#     from pptx import Presentation
#     prs = Presentation(file_path)
#     full_text = ""
#     for slide in prs.slides:
#         for shape in slide.shapes:
#             if hasattr(shape, "text"):
#                 full_text += shape.text + "\n"
#     return _split_text_into_chunks(full_text, TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP)

# def _read_odt_to_texts(file_path: str) -> List[str]:
#     from odf.opendocument import load as load_odf
#     from odf import text as odf_text, teletype as odf_teletype
#     doc = load_odf(file_path)
#     texts = []
#     for element in doc.getElementsByType(odf_text.P):
#         texts.append(odf_teletype.extractText(element))
#     full_text = "\n".join(texts)
#     return _split_text_into_chunks(full_text, TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP)

async def _extract_text_from_image_content_with_nvidia(
    image_bytes: bytes,
    image_mime_type: str, # e.g., "image/png", "image/jpeg"
    prompt_text: str
) -> str:
    """
    Sends image data and a prompt to the configured NVIDIA multi-modal model
    and returns the extracted text.
    """
    if not _nvidia_async_client:
        logger.error("NVIDIA client not initialized. Cannot process image content.")
        raise LLMServiceError("NVIDIA client not initialized.")

    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image_mime_type};base64,{base64_image}"
                    },
                },
            ],
        }
    ]

    try:
        logger.debug(f"Sending request to NVIDIA model {_nvidia_model_name} for image analysis. Prompt: {prompt_text[:50]}...")
        completion = await _nvidia_async_client.chat.completions.create(
            model=_nvidia_model_name,
            messages=messages,
            temperature=0.2, # Lower temp for more factual extraction
            top_p=0.7,
            max_tokens=2048, # Increased for potentially long text from pages
            stream=False
        )
        if completion.choices and completion.choices[0].message and completion.choices[0].message.content:
            extracted_text = completion.choices[0].message.content
            logger.debug(f"NVIDIA model returned content of length {len(extracted_text)} for prompt '{prompt_text[:50]}...'.")
            return extracted_text
        else:
            logger.warning(f"NVIDIA model returned no content or unexpected response structure for prompt '{prompt_text[:50]}...'.")
            return ""
    except Exception as e:
        # Catching general exception from openai client (APIConnectionError, RateLimitError, APIStatusError, etc.)
        logger.error(f"NVIDIA API call failed for prompt '{prompt_text[:50]}...': {type(e).__name__} - {e}", exc_info=True)
        raise LLMServiceError(f"NVIDIA API call failed: {type(e).__name__} - {e}")


async def process_uploaded_file(
    ctx: Context,
    file_id: Optional[str] = None,
    file_path_on_server: Optional[str] = None,
    original_filename: Optional[str] = None,
    processing_type: str = "auto",
    mcp_session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Processes an uploaded file with intelligent three-layer file type detection.

    DEBUG LOGGING: This function is being called - track if it's the wrong tool for .py files

    IMPORTANT: For best results, always provide the 'original_filename' parameter
    when available. This ensures accurate file type detection.

    File Type Detection Order:
    1. Parameter-based: Uses 'original_filename' if provided (most reliable)
    2. Session metadata: Retrieves from session storage if available
    3. Content-based: Analyzes file content using signatures and patterns (fallback)

    Supported Formats:
    - Documents: PDF, DOCX, TXT, MD, LaTeX
    - Data: CSV, XLSX, XLS, JSON, XML
    - Images: PNG, JPG, GIF, BMP, TIFF (with NVIDIA processing if available)
    - Archives: ZIP, RAR, 7Z (detected but not processed)

    Args:
        ctx: Context object
        file_id: The ID of the uploaded file (optional if file_path_on_server provided)
        file_path_on_server: Direct path to file (optional if file_id provided)
        original_filename: RECOMMENDED - Original filename with extension for accurate type detection
        processing_type: Type of processing (auto, rag, sql, dataframe, text, image)
        mcp_session_id: Session ID for context retrieval

    Returns:
        Dict with processing results or error details with helpful diagnostics

    Examples:
        # Best practice - include original_filename
        await process_uploaded_file(
            file_id="file-123",
            original_filename="report.pdf",
            processing_type="rag"
        )

        # Will use content detection if filename is UUID
        await process_uploaded_file(
            file_id="file-abc-def-ghi",  # No extension
            processing_type="auto"  # Type will be detected from content
        )
    """
    # DEBUG LOGGING: Track when process_uploaded_file is called (may be wrong tool for .py files)
    logger.info(
        f"[TOOL_SELECTION_DEBUG] process_uploaded_file CALLED: "
        f"file_id={file_id}, original_filename={original_filename}, "
        f"processing_type={processing_type}, session={mcp_session_id}"
    )

    # Enhanced file path resolution with comprehensive logging
    paths_checked = []
    resolved_path = None
    base_dir = os.environ.get("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")

    # Strategy 1: Direct path provided and exists
    if file_path_on_server and os.path.exists(file_path_on_server):
        resolved_path = file_path_on_server
        logger.info(f"File resolved via direct path: {resolved_path}")

    # Strategy 2: File ID based resolution
    elif file_id:
        # Build list of potential paths to check
        potential_paths = []

        # Session-specific paths (highest priority)
        if mcp_session_id:
            # Try exact session match
            potential_paths.append(os.path.join(base_dir, "sessions", mcp_session_id, file_id))
            # Try streamlit session format (in case of mismatch)
            if mcp_session_id.startswith("streamlit_"):
                potential_paths.append(os.path.join(base_dir, "sessions", mcp_session_id, file_id))
            else:
                potential_paths.append(os.path.join(base_dir, "sessions", f"streamlit_{mcp_session_id}", file_id))

        # Shared directory path
        potential_paths.append(os.path.join(base_dir, file_id))

        # Try each potential path with retry logic for intermittent file system issues
        import time
        max_retries = 3
        retry_delays = [0.5, 1.0, 2.0]  # Exponential backoff

        for path in potential_paths:
            paths_checked.append(path)

            # Try with retries for each path
            for retry in range(max_retries):
                if os.path.exists(path):
                    resolved_path = path
                    logger.info(f"File resolved at: {resolved_path} (checked {len(paths_checked)} paths, retry {retry})")
                    break
                elif retry < max_retries - 1:
                    # On first retry, try to sync file system
                    if retry == 0:
                        try:
                            os.sync()  # Force file system sync
                            logger.debug(f"Forced file system sync for path: {path}")
                        except Exception as e:
                            logger.debug(f"File system sync failed (non-critical): {e}")

                    delay = retry_delays[retry]
                    logger.debug(f"File not found on attempt {retry + 1}, retrying in {delay}s: {path}")
                    time.sleep(delay)

            if resolved_path:
                break

        if not resolved_path:
            logger.warning(f"File ID {file_id} not found after {max_retries} retries. Paths checked: {paths_checked}")

    # Strategy 3: Direct path provided but doesn't exist - log it
    elif file_path_on_server:
        paths_checked.append(file_path_on_server)
        logger.warning(f"Provided path does not exist: {file_path_on_server}")

    # Use resolved path or fall back to provided path
    file_path_on_server = resolved_path if resolved_path else file_path_on_server

    if not file_path_on_server:
        if file_id:
            # File ID was provided but couldn't be found
            error_msg = f"File with ID '{file_id}' could not be located after {max_retries if 'max_retries' in locals() else 1} attempts"
            detailed_msg = f"Searched in session directory and shared directory. Paths checked: {paths_checked[:3] if paths_checked else 'none'}"
            logger.error(f"{error_msg}. {detailed_msg}")
        else:
            # No file ID or path provided
            error_msg = "Either file_id or file_path_on_server must be provided"

        await ctx.error(error_msg)
        return {
            "error": error_msg,
            "paths_checked": paths_checked[:3] if paths_checked else [],
            "suggestion": "Use ListUploadedFiles tool to see available files, or verify the file was uploaded successfully"
        }

    # Try to retrieve original_filename from session metadata if not provided
    if not original_filename and file_id and mcp_session_id:
        try:
            session_data = await get_session_context(mcp_session_id)

            # Check multiple possible storage locations for file metadata
            # Expanded search to cover more potential storage keys
            search_keys = [
                "uploaded_files",
                "uploaded_csv_files",
                "processed_files",
                "file_registry",
                "files",  # Generic key
                "documents"  # Alternative key
            ]

            # Also check multiple field name variations
            field_names = [
                "original_filename",
                "filename",
                "name",
                "original_name",
                "file_name",
                "originalName"  # camelCase variant
            ]

            for key in search_keys:
                if key in session_data and isinstance(session_data[key], dict):
                    if file_id in session_data[key]:
                        file_info = session_data[key][file_id]
                        for field in field_names:
                            retrieved_filename = file_info.get(field)
                            if retrieved_filename:
                                original_filename = retrieved_filename
                                logger.info(f"Retrieved original filename from session [{key}][{field}]: {original_filename}")
                                break
                        if original_filename:
                            break
        except Exception as e:
            logger.warning(f"Could not retrieve original filename from session: {e}")

    # Infer filename if not provided and not retrieved from session
    if not original_filename:
        original_filename = os.path.basename(file_path_on_server)
        logger.info(f"No original filename found, using path basename: {original_filename}")

    logger.info(f"Received request to process file: {original_filename} at path: {file_path_on_server}")
    if not _llm_client_instance:
        await ctx.error("LLM client not initialized for CSV RAG tool.") # Removed TextPart wrapper
        return {"error": "Internal server error: LLM client not available."}

    logger.debug(f"Processing file: {original_filename} at path: {file_path_on_server}")

    # Use the provided mcp_session_id if available, otherwise get from context
    if mcp_session_id:
        session_id = mcp_session_id
        client_id = ctx.client_id if hasattr(ctx, 'client_id') else None
        await create_session_if_not_exists(session_id, client_id)
    else:
        session_id = await ensure_session_initialized(ctx) # Use common helper

    await ctx.info(f"Session {session_id}: Processing '{original_filename}' from path: {file_path_on_server}")

    logger.debug(f"Ensuring session {session_id} is initialized for file processing")
    if not os.path.exists(file_path_on_server):
        error_msg = f"File not found at server path: {file_path_on_server}"
        await ctx.error(error_msg)

        # Provide detailed error information with suggestions
        return {
            "error": error_msg,
            "file_id": file_id,
            "attempted_path": file_path_on_server,
            "paths_checked": paths_checked if paths_checked else [file_path_on_server],
            "suggestions": [
                "1. Use ListUploadedFiles tool to see available files in your session",
                "2. Verify the file ID is correct",
                "3. Check if the file was uploaded to the current session",
                "4. If using a direct path, ensure it's accessible from the container"
            ],
            "help": f"Files are typically stored in: {base_dir}/{{file_id}} or {base_dir}/sessions/{{session_id}}/{{file_id}}"
        }

    file_extension = Path(original_filename).suffix.lower()

    # Layer 3: Content-based detection if no extension found
    if not file_extension and os.path.exists(file_path_on_server):
        logger.info(f"No file extension found for '{original_filename}', attempting content-based detection")
        try:
            detector = ContentTypeDetector()
            detected_ext, detected_mime = await detector.detect_from_content(file_path_on_server)
            if detected_ext:
                file_extension = detected_ext
                logger.info(f"Successfully detected file type from content: {detected_ext} (MIME: {detected_mime})")
                # Update original_filename for logging purposes
                if original_filename and not Path(original_filename).suffix:
                    original_filename = f"{original_filename}{detected_ext}"
            else:
                logger.warning(f"Content-based detection failed for file: {file_path_on_server}")
        except Exception as e:
            logger.error(f"Error during content-based file type detection: {e}", exc_info=True)

    # Final check - if still no extension, provide helpful error
    if not file_extension:
        error_msg = f"Unable to determine file type for: {original_filename or file_id}"
        await ctx.error(error_msg)
        return {
            "error": error_msg,
            "file_id": file_id,
            "path": file_path_on_server,
            "suggestions": [
                "1. Provide the 'original_filename' parameter with the correct file extension",
                "2. Ensure the file is in a supported format (PDF, CSV, XLSX, DOCX, TXT, JSON, etc.)",
                "3. Check if the file content is corrupted or empty",
                "4. Use ListUploadedFiles tool to verify file metadata"
            ],
            "supported_formats": ["PDF", "CSV", "XLSX", "XLS", "DOCX", "TXT", "JSON", "MD", "PNG", "JPG", "GIF"],
            "help": "The system uses three methods to detect file type: parameter, session metadata, and content analysis"
        }

    texts_to_embed: List[str] = []
    nvidia_processing_attempted = False
    nvidia_processing_successful = False

    try:
        if file_extension == ".csv":
            texts_to_embed = _read_csv_to_texts(file_path_on_server)
        elif file_extension == ".xlsx":
            texts_to_embed = _read_excel_to_texts(file_path_on_server)
        elif file_extension == ".pdf" and _nvidia_async_client:
            nvidia_processing_attempted = True
            all_pdf_text_from_nvidia = ""
            num_pages_processed_successfully = 0
            try:
                pdf_doc = fitz.open(file_path_on_server)
                for page_num in range(len(pdf_doc)):
                    page = pdf_doc.load_page(page_num)
                    # Render page to PNG image bytes
                    pix = page.get_pixmap(dpi=150) # Use a reasonable DPI
                    img_bytes = pix.tobytes("png")
                    prompt = "Extract all text content from this document page."
                    try:
                        page_text = await _extract_text_from_image_content_with_nvidia(img_bytes, "image/png", prompt)
                        all_pdf_text_from_nvidia += page_text + "\n"
                        num_pages_processed_successfully +=1
                    except LLMServiceError as e: # Catch errors from NVIDIA call
                        logger.warning(f"NVIDIA model failed to process page {page_num + 1} of PDF '{original_filename}': {e}")
                    except Exception as e: # Catch other unexpected errors during page processing
                        logger.error(f"Unexpected error processing page {page_num + 1} of PDF '{original_filename}' with NVIDIA: {e}", exc_info=True)
                
                if num_pages_processed_successfully > 0:
                    texts_to_embed = _split_text_into_chunks(all_pdf_text_from_nvidia, TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP)
                    nvidia_processing_successful = True
                    logger.info(f"Successfully processed {num_pages_processed_successfully}/{len(pdf_doc)} pages of PDF '{original_filename}' using NVIDIA model.")
                else: # NVIDIA failed for all pages or PDF was empty
                    logger.warning(f"NVIDIA processing yielded no text for PDF '{original_filename}'.")

            except Exception as e: # Catch errors opening PDF or during loop
                logger.error(f"Error during NVIDIA-based PDF processing for '{original_filename}': {e}", exc_info=True)
            
            if not nvidia_processing_successful: # Fallback if NVIDIA processing failed or yielded no text
                logger.info(f"Falling back to standard PyMuPDF text extraction for PDF '{original_filename}'.")
                texts_to_embed = _read_pdf_to_texts(file_path_on_server)

        elif file_extension == ".pdf": # Standard PDF processing if NVIDIA client not available
            texts_to_embed = _read_pdf_to_texts(file_path_on_server)
        elif file_extension in IMAGE_MIME_TYPES and _nvidia_async_client:
            nvidia_processing_attempted = True
            try:
                with open(file_path_on_server, "rb") as f:
                    img_bytes = f.read()
                mime_type = IMAGE_MIME_TYPES[file_extension]
                prompt = "Describe this image and extract all text content visible in it."
                extracted_text = await _extract_text_from_image_content_with_nvidia(img_bytes, mime_type, prompt)
                texts_to_embed = _split_text_into_chunks(extracted_text, TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP)
                nvidia_processing_successful = True
                logger.info(f"Successfully processed image '{original_filename}' using NVIDIA model.")
            except LLMServiceError as e:
                logger.error(f"NVIDIA model failed to process image '{original_filename}': {e}. No text extracted.")
            except Exception as e:
                logger.error(f"Unexpected error processing image '{original_filename}' with NVIDIA: {e}", exc_info=True)

        elif file_extension == ".docx":
            texts_to_embed = _read_docx_to_texts(file_path_on_server)
        elif file_extension == ".txt":
            texts_to_embed = _read_txt_to_texts(file_path_on_server)
        elif file_extension == ".md":
            texts_to_embed = _read_txt_to_texts(file_path_on_server)
        elif file_extension == ".tex":
            texts_to_embed = _read_latex_to_texts(file_path_on_server)
        elif file_extension == ".xml":
            texts_to_embed = _read_xml_to_texts(file_path_on_server)
        elif file_extension == ".json":
            texts_to_embed = _read_json_to_texts(file_path_on_server)
        else:
            # DEBUG LOGGING: Identify which tool rejected .py files
            logger.warning(
                f"[TOOL_SELECTION_DEBUG] process_uploaded_file REJECTED file: "
                f"filename={original_filename}, extension={file_extension}. "
                f"NOTE: .py files should use ProcessFileAdvanced, not ProcessUploadedFile"
            )
            await ctx.warning(f"Unsupported file type: {original_filename}")
            return {"error": f"Unsupported file type: {file_extension}. Supported types: .csv, .xlsx, .docx, .pdf, .txt, .md, .tex, .xml, .json, {', '.join(IMAGE_MIME_TYPES.keys())}"}
    except Exception as e: # Catch exceptions from the reading functions
        logger.error(f"Failed to read/process file {original_filename}: {e}", exc_info=True)
        await ctx.error(f"Failed to read or process file '{original_filename}': {e}")
        return {"error": f"Failed to read or process file: {e}"}

    if not texts_to_embed:
        logger.info(f"No text content extracted from {original_filename}.")
        await ctx.info(f"No text content extracted from '{original_filename}'. File might be empty or not parsable.")
        return {"error": f"No text content could be extracted from {original_filename}."}

    logger.debug(f"File {original_filename} read successfully, extracted {len(texts_to_embed)} text segments for embedding.")
    # Use the existing file_id if provided, otherwise generate a new one
    # This preserves the original file_id from upload
    if not file_id:
        file_id = str(uuid.uuid4())
        logger.info(f"No file_id provided, generated new one: {file_id}")
    else:
        logger.info(f"Using existing file_id: {file_id}")
    total_segments = len(texts_to_embed)
    processed_segments = 0
    # For FastMCP, ctx.report_progress is not standard. Use ctx.info or similar.

    # Batch texts for embedding to be more efficient
    vsm = VectorStoreManager() # Get the singleton instance of VectorStoreManager

    # Collection name for ChromaDB, unique per file and session
    # This file_id is generated for this specific processing instance.
    collection_name = f"{session_id}_{file_id}"

    current_batch_texts: List[str] = []
    # original_indices for tabular data might need adjustment if mixing with chunked text.
    # For now, metadata will just store segment index.
    
    logger.debug(f"Processing {total_segments} text segments from {original_filename} for embedding")
    processing_method = "NVIDIA" if nvidia_processing_attempted and nvidia_processing_successful else "standard"
    await ctx.info(
        f"Session {session_id}: Starting embedding for '{original_filename}' "
        f"({total_segments} text segments, processed via {processing_method} method)."
    )

    for i, text_segment in enumerate(texts_to_embed):
        current_batch_texts.append(text_segment)
        
        # Embed in batches of 50 or if it's the last segment
        if len(current_batch_texts) >= 50 or (i == total_segments - 1 and current_batch_texts):
            try:
                # Let LLMAgnosticClient use its default embedding model
                logger.debug(f"Embedding chunk for {original_filename}: {len(current_batch_texts)} segments")
                chunk_embeddings = await _llm_client_instance.acreate_embedding( 
                    input_texts=current_batch_texts
                )

                # Prepare data for VectorStoreManager.add_documents
                ids_for_vsm = []
                docs_for_vsm = []
                embeddings_for_vsm = []
                metadatas_for_vsm = []
                
                for batch_idx, emb_vector in enumerate(chunk_embeddings):
                    doc_id = str(uuid.uuid4())
                    ids_for_vsm.append(doc_id)
                    docs_for_vsm.append(current_batch_texts[batch_idx])
                    embeddings_for_vsm.append(emb_vector)
                    metadatas_for_vsm.append({
                        "file_id": file_id,
                        "session_id": session_id,
                        "segment_index": processed_segments + batch_idx, # Overall segment index
                        "original_filename": original_filename
                    })
                # Use VectorStoreManager to add documents
                vsm.add_documents(collection_name=collection_name, documents=docs_for_vsm, embeddings=embeddings_for_vsm, metadatas=metadatas_for_vsm, ids=ids_for_vsm)
                logger.debug(f"Successfully embedded {len(current_batch_texts)} segments for {original_filename}.")
                # Update processed segments count
                processed_segments += len(current_batch_texts)
                await ctx.info(f"Session {session_id}: Embedded {processed_segments}/{total_segments} segments for '{original_filename}'.")
            except LLMServiceError as e:
                logger.error(f"Failed to embed chunk for {original_filename}: {e}", exc_info=True)
                await ctx.error(f"Failed to embed a chunk of segments for '{original_filename}': {e}. Skipping chunk.")
            except Exception as e: # Catch any other unexpected error during embedding
                logger.error(f"Unexpected error embedding chunk for {original_filename}: {e}", exc_info=True)
                await ctx.warning(f"Unexpected error embedding a chunk for '{original_filename}': {e}. Skipping chunk.")
            finally:
                current_batch_texts = []

    logger.info(f"Total segments processed for {original_filename}: {processed_segments} out of {total_segments}")

    logger.info(f"Successfully stored embeddings for {original_filename} with file_id: {file_id}")
    session_context = await get_session_context(session_id)
    uploaded_files_info = session_context.get("uploaded_csv_files", {})
    uploaded_files_info[file_id] = {
        "original_filename": original_filename,
        "segment_count": processed_segments, # Store actual processed segments
        "collection_name": collection_name, # Store the ChromaDB collection name
        "status": "indexed"
    }
    session_context["uploaded_csv_files"] = uploaded_files_info
    await update_session_context(session_id, session_context)

    logger.debug(f"Updated session context for session {session_id} with file_id: {file_id} (processed via {processing_method})")

    try:
        os.remove(file_path_on_server) # Clean up the file from shared volume
        await ctx.info(f"Removed temporary file from shared volume: {file_path_on_server}")
    except OSError as e:
        logger.warning(f"Could not remove file {file_path_on_server} from shared volume: {e}")

    logger.info(f"File {original_filename} processed and indexed successfully with file_id: {file_id}")
    await ctx.info(
        f"Session {session_id}: Successfully processed and indexed '{original_filename}' "
        f"(using {processing_method} method) as file_id: {file_id}"
    ) 
    # Return collection_name as well, might be useful for direct VSM queries if needed
    return {"file_id": file_id, 
            "original_filename": original_filename, 
            "collection_name": collection_name,
            "message": "File processed and indexed."}
    

async def query_file_content(user_query: str, file_id: str, ctx: Context, top_k: int = 3, mcp_session_id: str = None) -> str:
    """
    Queries the indexed content of a previously processed file using RAG.
    """
    logger.info(f"Received query for file content: file_id={file_id}, query='{user_query}', mcp_session_id={mcp_session_id}")
    if not _llm_client_instance:
        await ctx.error("LLM client not initialized for RAG tool.")
        return "Error: Internal server error - LLM client not available."

    # Use the provided mcp_session_id if available, otherwise get from context
    if mcp_session_id:
        session_id = mcp_session_id
        client_id = ctx.client_id if hasattr(ctx, 'client_id') else None
        await create_session_if_not_exists(session_id, client_id)
    else:
        session_id = await ensure_session_initialized(ctx) # Use common helper

    await ctx.info(f"Session {session_id}: Querying file (file_id: {file_id}) with query: '{user_query}'")

    session_context = await get_session_context(session_id)
    uploaded_file_info = session_context.get("uploaded_csv_files", {}).get(file_id)

    # If file_id not in session metadata, check if file exists on disk and process it
    if not uploaded_file_info:
        # Check if file exists on disk (could be uploaded but not yet indexed)
        base_dir = os.environ.get("SHARED_UPLOAD_DIR", "/app/data/uploaded_files")
        potential_paths = []

        # Check session-specific paths
        if mcp_session_id:
            potential_paths.append(os.path.join(base_dir, "sessions", mcp_session_id, file_id))
            if not mcp_session_id.startswith("streamlit_"):
                potential_paths.append(os.path.join(base_dir, "sessions", f"streamlit_{mcp_session_id}", file_id))

        # Check shared directory
        potential_paths.append(os.path.join(base_dir, file_id))

        file_found = False
        file_path = None
        for path in potential_paths:
            if os.path.exists(path):
                file_found = True
                file_path = path
                logger.info(f"File {file_id} found on disk at {path} but not in session metadata. Attempting to process it.")
                break

        if file_found:
            # File exists but hasn't been processed - process it now
            await ctx.info(f"File {file_id} exists but hasn't been indexed. Processing it now...")

            try:
                # Process the file for RAG indexing
                process_result = await process_uploaded_file(
                    ctx=ctx,
                    file_id=file_id,
                    file_path_on_server=file_path,
                    processing_type="auto",
                    mcp_session_id=mcp_session_id
                )

                if isinstance(process_result, dict) and "error" not in process_result:
                    # File processed successfully, now get the updated session context
                    session_context = await get_session_context(session_id)
                    uploaded_file_info = session_context.get("uploaded_csv_files", {}).get(file_id)

                    if not uploaded_file_info:
                        await ctx.error(f"File {file_id} was processed but session metadata wasn't updated properly.")
                        return f"Error: File processing completed but metadata update failed for {file_id}."
                else:
                    error_msg = process_result.get("error", "Unknown error") if isinstance(process_result, dict) else str(process_result)
                    await ctx.error(f"Failed to process file {file_id}: {error_msg}")
                    return f"Error: Failed to process file {file_id} for RAG indexing: {error_msg}"

            except Exception as e:
                logger.error(f"Error processing file {file_id} for RAG indexing: {e}", exc_info=True)
                await ctx.error(f"Failed to process file {file_id}: {e}")
                return f"Error: Failed to process file {file_id} for RAG indexing: {e}"
        else:
            # File doesn't exist on disk either
            await ctx.error(f"Invalid or unknown file_id: {file_id} for this session.")
            return f"Error: File ID {file_id} not found or not associated with this session."

    collection_name = uploaded_file_info.get("collection_name")
    if not collection_name:
        return f"Error: Collection name not found for file_id {file_id}. The file might not have been processed correctly with the new vector store."
    
    await ctx.info(f"Session {session_id}: Generating query embedding for: '{user_query}'")
    try:
        # Let LLMAgnosticClient use its default embedding model
        query_embedding_list = await _llm_client_instance.acreate_embedding( 
            input_texts=[user_query]
        )
        if not query_embedding_list:
            logger.error(f"Embedding service returned no embedding for query: {user_query}")
            await ctx.error("Failed to get embedding for the user query.")
            return "Error: Could not process query due to embedding failure (empty result)."
        query_vector = query_embedding_list[0] # This is List[float]
    except LLMServiceError as e:
        logger.error(f"Failed to embed user query '{user_query}': {e}", exc_info=True)
        await ctx.error(f"Failed to embed user query: {e}")
        return f"Error: Could not process query due to embedding failure: {e}."
    
    await ctx.info(f"Session {session_id}: Searching relevant chunks for file_id {file_id}")
    relevant_chunks_texts: List[str] = []

    vsm = VectorStoreManager()

    try:
        # Query using VectorStoreManager
        chroma_results = vsm.query_collection(
            collection_name=collection_name,
            query_embeddings=[query_vector], # Corrected keyword argument
            n_results=top_k,
            #include=["documents"] # We only need the document text for the context
        )
        if chroma_results and chroma_results.get('documents') and chroma_results['documents'][0]:
            relevant_chunks_texts = chroma_results['documents'][0]
        else:
            logger.info(f"No relevant chunks found in ChromaDB for file_id {file_id}, session {session_id} and query.")
    except Exception as e:
        logger.error(f"Error querying ChromaDB for file_id {file_id}, session {session_id}: {e}", exc_info=True)
        await ctx.error(f"Error retrieving data from vector store for collection '{collection_name}': {e}")
        return f"Error: Could not retrieve relevant data: {e}."

    if not relevant_chunks_texts:
        await ctx.info("No relevant chunks found for the query after similarity search.")
        return "Could not find sufficiently relevant information in the indexed file to answer your query."
    
    await ctx.info(f"Session {session_id}: Constructing prompt for LLM with {len(relevant_chunks_texts)} chunks.")

    context_str = "\n\n".join(relevant_chunks_texts)

    # Limit RAG context size to prevent token explosions
    MAX_RAG_CONTEXT_CHARS = int(os.getenv("MAX_RAG_CONTEXT_CHARS", "10000"))
    if len(context_str) > MAX_RAG_CONTEXT_CHARS:
        # Keep beginning and end for context continuity
        context_str = (
            context_str[:MAX_RAG_CONTEXT_CHARS//2] +
            f"\n\n... [Additional context truncated - {len(context_str) - MAX_RAG_CONTEXT_CHARS} chars omitted] ...\n\n" +
            context_str[-MAX_RAG_CONTEXT_CHARS//2:]
        )
        original_length = len('\n\n'.join(relevant_chunks_texts))
        logger.info(f"Truncated RAG context from {original_length} to {len(context_str)} chars")

    system_prompt = (
        "You are a helpful AI assistant. Based on the following context from a processed file, "
        "answer the user's query. If the context does not contain the answer, "
        "say that you cannot find the answer in the provided data."
    )
    user_prompt_content = f"Context from processed file:\n{context_str}\n\nUser Query: {user_query}"

    prompt_messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_content}
    ]
    
    await ctx.info(f"Session {session_id}: Generating answer with LLM.")
    try:
        llm_response = await _llm_client_instance.agenerate_response(
            llm_purpose="coding_agent", # Use coding_agent (AWS Bedrock Claude Opus) - faster and more reliable than Azure RAG endpoint
            messages=prompt_messages,
            stream=False # Get full response for RAG,
            # Consider adding temperature or other params if needed
        )
        answer = llm_response.choices[0].message.content if llm_response.choices and llm_response.choices[0].message else "LLM did not provide an answer."
    except LLMServiceError as e:
        logger.error(f"LLM failed to generate RAG answer: {e}", exc_info=True)
        await ctx.error(f"LLM failed to generate answer: {e}")
        return f"Error: LLM failed to generate an answer: {e}."
    
    await ctx.info(f"Session {session_id}: Successfully generated RAG answer for file_id: {file_id}")
    return str(answer)

def _initialize_nvidia_client():
    """Initializes the NVIDIA AsyncOpenAI client from environment variables."""
    global _nvidia_api_key, _nvidia_base_url, _nvidia_model_name, _nvidia_async_client
    _nvidia_api_key = os.getenv(NVIDIA_API_KEY_ENV_VAR)
    _nvidia_base_url = os.getenv(NVIDIA_BASE_URL_ENV_VAR, _nvidia_base_url) # Use default if not set
    _nvidia_model_name = os.getenv(NVIDIA_MULTI_MODAL_MODEL_ENV_VAR, _nvidia_model_name) # Use default if not set

    if _nvidia_api_key:
        try:
            _nvidia_async_client = openai.AsyncOpenAI(
                base_url=_nvidia_base_url,
                api_key=_nvidia_api_key,
            )
            logger.info(f"NVIDIA AsyncOpenAI client initialized for model '{_nvidia_model_name}' at base URL '{_nvidia_base_url}'.")
        except Exception as e:
            logger.error(f"Failed to initialize NVIDIA AsyncOpenAI client: {e}", exc_info=True)
            _nvidia_async_client = None # Ensure it's None if init fails
    else:
        logger.info(f"'{NVIDIA_API_KEY_ENV_VAR}' not set. NVIDIA multi-modal document analysis will be unavailable.")

def register_tools(mcp: FastMCP, llm_client: LLMAgnosticClient):
    """Registers the File RAG tools with the FastMCP instance."""
    global _llm_client_instance
    _llm_client_instance = llm_client
    _initialize_nvidia_client() # Initialize NVIDIA client

    logger.info("File RAG Tool configured to use LLMAgnosticClient defaults for embedding and RAG.")
    mcp.tool()(process_uploaded_file)
    mcp.tool()(query_file_content)

    logger.info("File RAG MCP tools registered.")
