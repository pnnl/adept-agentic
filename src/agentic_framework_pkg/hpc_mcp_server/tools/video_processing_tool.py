"""
This module registers the video processing tools with the HPC MCP server.

It provides a tool for transcribing and summarizing video content by
orchestrating a Nextflow pipeline that uses `yt-dlp` for audio extraction
and `whisper` for transcription. The resulting transcript is then summarized
by an LLM and indexed into a vector store for RAG.
"""
from fastmcp import FastMCP, Context
from ...logger_config import get_logger
from ...core.llm_agnostic_layer import LLMAgnosticClient, LLMServiceError
import asyncio
import subprocess
import tempfile
import os
import shutil
from typing import Dict, Any, Optional, List, Union, Tuple, Callable
import re
import uuid
import json

# Import VectorStoreManager and session context functions
from ...mcp_server.vector_store_manager import VectorStoreManager # Assuming relative path works
from ...core.session_api import get_session_context, update_session_context

logger = get_logger(__name__)

NEXTFLOW_SCRIPT_PATH_ENV_VAR = "NEXTFLOW_TRANSCRIPTION_SCRIPT_PATH" # This matches the Dockerfile.hpc env var for this script
CURR_DIR = os.path.dirname(os.path.abspath(__file__))
# Use the specific env var for this pipeline, falling back to a relative path
NEXTFLOW_SCRIPT_PATH = os.getenv(NEXTFLOW_SCRIPT_PATH_ENV_VAR, "./video_transcription_pipeline.nf")
if not os.path.exists(NEXTFLOW_SCRIPT_PATH):
    # If it's not absolute, make it relative to the current directory (where this tool file is)
    NEXTFLOW_SCRIPT_PATH = os.path.join(CURR_DIR, NEXTFLOW_SCRIPT_PATH)
    # However, Dockerfile.hpc copies it to /app/video_transcription_pipeline.nf and sets NEXTFLOW_TRANSCRIPTION_SCRIPT_PATH
    # So, the os.getenv should ideally pick up the absolute path from the Docker env.
    # This local resolution is more for non-Docker testing if the script is co-located.
    # The Dockerfile sets: ENV NEXTFLOW_TRANSCRIPTION_SCRIPT_PATH="/app/video_transcription_pipeline.nf"
    
# Ensure the script exists at the resolved path
if not os.path.exists(NEXTFLOW_SCRIPT_PATH):
    logger.warning(f"Nextflow transcription script not found at {NEXTFLOW_SCRIPT_PATH} (resolved from env var '{NEXTFLOW_SCRIPT_PATH_ENV_VAR}' or default).")
    

# Text chunking parameters
TEXT_CHUNK_SIZE = 1000
TEXT_CHUNK_OVERLAP = 100

# Global LLM client instance, to be set by register_tools
_llm_agnostic_client_instance: Optional[LLMAgnosticClient] = None

async def _ensure_session_hpc_video(ctx: Context) -> str:
    """Ensures a session is initialized for the video processing tool."""
    logger.debug(f"HPC Video tool called with context: {ctx.request_id}")
    return ctx.request_id or f"hpc_video_session_{uuid.uuid4()}"

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

def register_tools(mcp: FastMCP, llm_client: Optional[LLMAgnosticClient] = None):
    """Registers the video processing tools with the MCP server."""
    global _llm_agnostic_client_instance
    _llm_agnostic_client_instance = llm_client

    @mcp.tool()
    async def run_video_transcription_pipeline(
        ctx: Context,
        video_input_path_or_url: str,
        whisper_model_size: str = "base",
        mcp_session_id: Optional[str] = None # This is the session ID from the Langchain agent / Streamlit app
    ) -> Dict[str, Any]:
        """
        Runs a Nextflow pipeline to transcribe and summarize a video.
        """
        # session_id_for_log is for this specific tool invocation if mcp_session_id isn't passed or for local logging.
        session_id_for_log = await _ensure_session_hpc_video(ctx)
        # For RAG and consistent session management, use the mcp_session_id passed from the agent.
        # If it's not passed, RAG data might be harder to associate with the user's overall session.
        effective_session_id_for_rag = mcp_session_id or session_id_for_log
        
        await ctx.info(f"Tool Invocation ID {session_id_for_log} (RAG Session ID: {effective_session_id_for_rag}): Received video transcription request for: '{video_input_path_or_url}' using Whisper model '{whisper_model_size}'.")

        if not _llm_agnostic_client_instance:
            await ctx.error("LLM client not initialized for video processing tool.")
            return {"status": "error", "message": "Internal server error: LLM client not available for summarization."}

        # NEXTFLOW_SCRIPT_PATH is resolved at module load time.
        nextflow_script_actual_path = NEXTFLOW_SCRIPT_PATH
        if not os.path.exists(nextflow_script_actual_path):
            logger.error(f"Nextflow transcription script not found at {nextflow_script_actual_path} (resolved from env var '{NEXTFLOW_SCRIPT_PATH_ENV_VAR}' or default).")
            await ctx.error("Server configuration error: Nextflow transcription script not found.")
            return {"status": "error", "message": "Server configuration error: Transcription pipeline script missing."}

        transcript_content = "" 
        transcript_file_id = None 
        transcript_chunks = [] 

        with tempfile.TemporaryDirectory(prefix="nextflow_video_") as temp_work_dir:
            results_dir_path = os.path.join(temp_work_dir, "transcription_pipeline_output")
            os.makedirs(results_dir_path, exist_ok=True)

            nextflow_command = [
                "nextflow", "run", nextflow_script_actual_path,
                "--video_input", video_input_path_or_url,
                "--outdir", results_dir_path, 
                "--whisper_model", whisper_model_size,
                "-profile", "standard", 
                "-work-dir", os.path.join(temp_work_dir, "work"),
                # "-Dnextflow.verbose=true" # Add this for increased Nextflow verbosity
            ]

            await ctx.info(f"Executing Nextflow video transcription: {' '.join(nextflow_command)}")
            logger.info(f"Executing Nextflow video transcription: {' '.join(nextflow_command)}")

            try:
                process = await asyncio.create_subprocess_exec(
                    *nextflow_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    err_msg = f"Nextflow video transcription pipeline failed. RC: {process.returncode}. Stderr: {stderr.decode(errors='ignore')}"
                    await ctx.error(err_msg)
                    logger.error(err_msg)
                    return {"status": "error", "message": "Nextflow video transcription pipeline execution failed.", "details": stderr.decode(errors='ignore'), "log_stdout": stdout.decode(errors='ignore')}

                await ctx.info("Nextflow video transcription pipeline completed successfully.")
                
                transcript_file_path_txt = None
                transcript_dir = os.path.join(results_dir_path, "transcripts") 
                if os.path.exists(transcript_dir):
                    for f_name in os.listdir(transcript_dir):
                        if f_name.endswith(".txt"):
                            transcript_file_path_txt = os.path.join(transcript_dir, f_name)
                            break
                
                if not transcript_file_path_txt or not os.path.exists(transcript_file_path_txt):
                    msg = "Transcription output file (.txt) not found after Nextflow pipeline."
                    await ctx.error(msg)
                    logger.error(f"{msg} Searched in {transcript_dir}. Stdout: {stdout.decode(errors='ignore')}")
                    return {"status": "error", "message": msg, "log_stdout": stdout.decode(errors='ignore'), "log_stderr": stderr.decode(errors='ignore')}

                with open(transcript_file_path_txt, "r", encoding='utf-8') as tf:
                    transcript_content = tf.read()
                
                await ctx.info(f"Transcript successfully retrieved (length: {len(transcript_content)}). Proceeding to summarization and RAG indexing.")

                # --- RAG Indexing of the Transcript ---
                transcript_file_id = str(uuid.uuid4())
                transcript_collection_name = f"{effective_session_id_for_rag}_{transcript_file_id}" 
                
                transcript_chunks = _split_text_into_chunks(transcript_content, TEXT_CHUNK_SIZE, TEXT_CHUNK_OVERLAP)
                if not transcript_chunks:
                    logger.warning(f"Transcript for '{video_input_path_or_url}' resulted in no processable chunks.")
                else:
                    try:
                        chunk_embeddings = await _llm_agnostic_client_instance.acreate_embedding(input_texts=transcript_chunks)
                        
                        ids_for_vsm = [str(uuid.uuid4()) for _ in transcript_chunks]
                        metadatas_for_vsm = [{
                            "file_id": transcript_file_id, 
                            "session_id": effective_session_id_for_rag,
                            "segment_index": i,
                            "original_filename": f"Transcript of: {video_input_path_or_url}" 
                        } for i in range(len(transcript_chunks))]

                        vsm = VectorStoreManager() 
                        vsm.add_documents(
                            collection_name=transcript_collection_name,
                            documents=transcript_chunks,
                            embeddings=chunk_embeddings,
                            metadatas=metadatas_for_vsm,
                            ids=ids_for_vsm
                        )
                        await ctx.info(f"Successfully indexed {len(transcript_chunks)} chunks for video transcript '{video_input_path_or_url}' with file_id '{transcript_file_id}' into collection '{transcript_collection_name}'.")
                        
                        # Warning about session state for list_uploaded_files
                        logger.warning(
                            "RAG data for transcript indexed. For 'list_uploaded_files' on the main MCP server to see this, "
                            "both servers must use a shared VectorStoreManager and session state backend, or the client/agent "
                            "needs to manage this transcript_file_id explicitly."
                        )
                    except Exception as rag_e:
                        logger.error(f"Failed to index transcript for RAG: {rag_e}", exc_info=True)
                        await ctx.warning(f"Transcript summarization will proceed, but RAG indexing failed: {rag_e}")
                # --- End RAG Indexing ---

                summarization_prompt_messages = [{"role": "system", "content": "You are an expert summarizer. Provide a concise summary of the following transcript."}, {"role": "user", "content": f"Please summarize this transcript:\n\n{transcript_content}"}]
                summary_response = await _llm_agnostic_client_instance.agenerate_response(messages=summarization_prompt_messages, llm_purpose="rag") 
                summary_text = summary_response.choices[0].message.content if summary_response.choices and summary_response.choices[0].message else "LLM did not provide a summary."
                
                markdown_output = f"# Video Transcription Summary\n\n**Video Source:** `{video_input_path_or_url}`\n\n## Summary\n{summary_text}\n\n## Full Transcript (first 1000 chars)\n```\n{transcript_content[:1000].strip()}...\n```\n\n**Transcript File ID for RAG:** `{transcript_file_id if transcript_chunks else 'N/A (not indexed)'}`"
                return {"status": "success", "summary_markdown": markdown_output, "transcript_file_id": transcript_file_id if transcript_chunks else None, "full_transcript_preview": transcript_content[:1000].strip()+"..."}

            except LLMServiceError as llm_e:
                logger.error(f"LLM summarization failed: {llm_e}", exc_info=True)
                await ctx.error(f"LLM summarization failed: {llm_e}")
                return {"status": "partial_success", "message": "Transcription successful, but summarization failed.", "transcript_preview": transcript_content[:1000].strip()+"..." if transcript_content else "Transcript not available.", "error_details": str(llm_e)}
            except Exception as e:
                logger.error(f"Error running Nextflow video transcription pipeline: {e}", exc_info=True)
                await ctx.error(f"Failed to execute Nextflow video transcription pipeline: {e}")
                return {"status": "error", "message": f"An unexpected error occurred: {e}"}

    logger.info("HPC Video Transcription tool registered.")