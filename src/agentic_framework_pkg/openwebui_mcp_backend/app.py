import os
import uuid
import json
import httpx
from fastapi import FastAPI, Request, HTTPException, UploadFile, File
import shutil
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field, BaseModel
from dotenv import load_dotenv
from typing import Dict, Any, List, Callable, Type, Optional, Union

# --- Load environment variables from .env file at the very beginning ---
current_script_path = os.path.abspath(__file__)
current_dir = os.path.dirname(current_script_path)
src_dir = os.path.join(current_dir, '..', '..', '..')
dotenv_path = os.path.abspath(os.path.join(src_dir, '.env'))
if not os.path.exists(dotenv_path):
    print(f"Warning: .env file not found at {dotenv_path}. Make sure it exists in the root of the agentic-framework directory.")
load_dotenv(dotenv_path=dotenv_path)
# --- End of environment loading ---

from agentic_framework_pkg.logger_config import get_logger # noqa: E402
from agentic_framework_pkg.orchestration_service.scientific_workflow.mcp_langchain_tools import ( # noqa: E402
    get_mcp_query_csv_tool_langchain,
    get_mcp_perform_calculation_tool_langchain,
    get_mcp_store_note_tool_langchain,
    get_mcp_retrieve_notes_tool_langchain,
    get_mcp_query_uniprot_tool_langchain,
    get_mcp_web_search_api_tool_langchain,
    get_mcp_web_search_scraping_tool_langchain,
    get_mcp_blastp_biopython_tool_langchain,
    get_mcp_blastn_biopython_tool_langchain,
    get_mcp_search_pubchem_by_name_tool_langchain,
    get_mcp_get_pubchem_compound_properties_tool_langchain,
    get_mcp_list_uploaded_files_tool_langchain,
    get_mcp_alphafold_prediction_tool_langchain,
    get_mcp_query_stored_alphafold_tool_langchain,
    get_mcp_run_nextflow_blast_tool_langchain,
    get_mcp_run_video_transcription_tool_langchain,
    get_mcp_execute_code_tool_langchain,
    get_mcp_gitxray_scan_tool_langchain,
    get_mcp_create_multi_agent_session_tool_langchain,
    get_mcp_generate_plan_for_multi_agent_task_tool_langchain,
    get_mcp_execute_approved_plan_tool_langchain,
    get_mcp_update_pending_plan_tool_langchain,
    get_mcp_terminate_multi_agent_session_tool_langchain,
    get_mcp_list_active_multi_agent_sessions_tool_langchain,
    get_mcp_search_pubchem_by_query_tool_langchain
)


logger = get_logger(__name__)

app = FastAPI(
    title="OpenWebUI MCP Tool Proxy",
    description="Exposes MCP tools from multiple servers via a single, consolidated, OpenAPI-compatible interface for OpenWebUI.",
    version="1.0.0",
)

# CORS Configuration to allow requests from OpenWebUI
origins = [
    "http://localhost", "http://localhost:3000", "http://localhost:8080",
    "http://localhost:8081", "http://localhost:8083", "http://localhost:8084",
    "http://localhost:8902", "http://127.0.0.1", "http://127.0.0.1:3000",
    "http://127.0.0.1:8080", "http://127.0.0.1:8081", "http://127.0.0.1:8082",
    "http://127.0.0.1:8084", "http://127.0.0.1:8902", "http://host.docker.internal",
    "http://host.docker.internal:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MCP_SERVER_URLS = {
    "mcp_server": os.getenv("MCP_SERVER_URL"),
    "hpc_mcp_server": os.getenv("HPC_MCP_SERVER_URL"),
    "sandbox_mcp_server": os.getenv("SANDBOX_MCP_SERVER_URL"),
}

# Store a mapping from exposed tool name to its server and actual name
TOOL_TO_SERVER_MAP: Dict[str, Dict[str, str]] = {}
ALL_TOOL_SPECS: List[Dict[str, Any]] = []

class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Union[str, int]

async def execute_mcp_tool(mcp_server_name: str, tool_name: str, tool_args: Dict) -> Any:
    """Executes a tool on the specified MCP server."""
    url = MCP_SERVER_URLS.get(mcp_server_name)
    if not url:
        raise HTTPException(status_code=500, detail=f"Unknown or unconfigured MCP server: {mcp_server_name}")

    logger.info(f"Proxying call for tool '{tool_name}' to '{mcp_server_name}' at {url} with args: {tool_args}")
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            response = await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": tool_args},
                    "id": str(uuid.uuid4()),
                },
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                logger.error(f"Error from upstream MCP tool '{tool_name}': {data['error']}")
                raise HTTPException(status_code=400, detail=data["error"])
            
            result = data.get("result", {}).get("result")
            return result
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error calling MCP tool '{tool_name}': {e.response.text}", exc_info=True)
            raise HTTPException(status_code=e.response.status_code, detail=f"Failed to call upstream MCP tool: {e.response.text}")
        except Exception as e:
            logger.error(f"Failed to execute MCP tool '{tool_name}': {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Internal server error while proxying tool call: {str(e)}")

def create_tool_endpoint_handler(exposed_tool_name: str, model: Type[BaseModel]) -> Callable:
    """Factory to create a handler for a specific tool with a Pydantic model."""
    async def handler(args: model) -> JSONResponse:
        tool_args = args.model_dump(exclude_unset=True)
        tool_info = TOOL_TO_SERVER_MAP.get(exposed_tool_name)
        if not tool_info:
            raise HTTPException(status_code=404, detail=f"Tool '{exposed_tool_name}' not found.")
        
        mcp_server_name = tool_info["server"]
        actual_tool_name = tool_info["actual"]
        
        result = await execute_mcp_tool(mcp_server_name, actual_tool_name, tool_args)
        return JSONResponse(content=result)
    return handler

def get_all_tool_factories() -> List[Callable]:
    """Returns a list of all MCP Langchain tool factory functions."""
    return [
        # Note: Any new tool factory added here should also be added to the list in `fetch_and_register_tools`
        get_mcp_query_csv_tool_langchain,
        get_mcp_perform_calculation_tool_langchain,
        get_mcp_store_note_tool_langchain,
        get_mcp_retrieve_notes_tool_langchain,
        get_mcp_query_uniprot_tool_langchain,
        get_mcp_web_search_api_tool_langchain,
        get_mcp_web_search_scraping_tool_langchain,
        get_mcp_blastp_biopython_tool_langchain,
        get_mcp_blastn_biopython_tool_langchain,
        get_mcp_search_pubchem_by_name_tool_langchain,
        get_mcp_get_pubchem_compound_properties_tool_langchain,
        get_mcp_list_uploaded_files_tool_langchain,
        get_mcp_alphafold_prediction_tool_langchain,
        get_mcp_query_stored_alphafold_tool_langchain,
        get_mcp_run_nextflow_blast_tool_langchain,
        get_mcp_run_video_transcription_tool_langchain,
        get_mcp_execute_code_tool_langchain,
        get_mcp_gitxray_scan_tool_langchain,
        get_mcp_create_multi_agent_session_tool_langchain,
        get_mcp_generate_plan_for_multi_agent_task_tool_langchain,
        get_mcp_execute_approved_plan_tool_langchain,
        get_mcp_update_pending_plan_tool_langchain,
        get_mcp_terminate_multi_agent_session_tool_langchain,
        get_mcp_list_active_multi_agent_sessions_tool_langchain,
        get_mcp_search_pubchem_by_query_tool_langchain
    ]

async def fetch_and_register_tools():
    """Fetches tools from the mcp_langchain_tools registry and registers them as FastAPI endpoints."""
    tool_factories = get_all_tool_factories()
    mcp_session_id = "openwebui-mcp-proxy"  # A dummy session id for creating tool instances

    for tool_factory in tool_factories:
        try:
            tool_instance = tool_factory(mcp_session_id=mcp_session_id)
            
            exposed_name = tool_instance.name
            actual_name = tool_instance.actual_tool_name
            mcp_url = tool_instance.mcp_client_url
            description = tool_instance.description
            args_schema_model = tool_instance.args_schema

            server_name = None
            for s_name, s_url in MCP_SERVER_URLS.items():
                if s_url == mcp_url:
                    server_name = s_name
                    break
            
            if not server_name:
                logger.warning(f"Could not find a configured MCP server for tool '{exposed_name}' with URL '{mcp_url}'. Skipping.")
                continue

            if exposed_name in TOOL_TO_SERVER_MAP:
                logger.warning(f"Tool '{exposed_name}' is already registered. Skipping duplicate.")
                continue

            TOOL_TO_SERVER_MAP[exposed_name] = {"server": server_name, "actual": actual_name}
            
            # Create the tool spec for tools/list
            tool_spec = {
                "name": exposed_name,
                "description": description,
                "parameters": args_schema_model.schema() if args_schema_model else {"type": "object", "properties": {}}
            }
            ALL_TOOL_SPECS.append(tool_spec)
            
            # Create endpoint handler and register route
            handler = create_tool_endpoint_handler(exposed_name, args_schema_model)
            app.add_api_route(
                path=f"/{exposed_name}",
                endpoint=handler,
                methods=["POST"],
                summary=description,
                operation_id=exposed_name,
                tags=[f"MCP Tools ({server_name})"],
                response_model=Any,
            )
            logger.info(f"Registered tool endpoint: POST /{exposed_name} from {server_name}")
        except Exception as e:
            logger.error(f"Failed to register tool from factory {tool_factory.__name__}: {e}", exc_info=True)


@app.post("/mcp", tags=["MCP JSON-RPC"])
async def mcp_rpc_handler(request: JsonRpcRequest):
    """Handles MCP JSON-RPC requests, currently supporting 'tools/list'."""
    # TODO: Add authentication and authorization checks here in the future
    if request.method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "result": {"tools": ALL_TOOL_SPECS},
            "id": request.id
        }
    else:
        raise HTTPException(status_code=400, detail=f"Method '{request.method}' not supported.")

@app.on_event("startup")
async def startup_event():
    """On startup, fetch tools from the tool registry and create API endpoints."""
    await fetch_and_register_tools()
    logger.info("Tool registration complete. The server is ready to accept requests.")

@app.post("/uploadfile", tags=["File Upload"])
async def create_upload_file(file: UploadFile = File(...)):
    """
    Handles file uploads from OpenWebUI. Saves the file to a shared volume
    and returns the path that other MCP tools can use to access it.
    """
    # The directory where files will be saved, accessible by other containers
    upload_dir = "/app/data/uploaded_files"
    os.makedirs(upload_dir, exist_ok=True)

    # Sanitize filename to prevent directory traversal attacks
    safe_filename = os.path.basename(file.filename)
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    
    # Create a unique path to avoid overwriting files
    unique_filename = f"{uuid.uuid4().hex}_{safe_filename}"
    file_path_in_container = os.path.join(upload_dir, unique_filename)

    try:
        with open(file_path_in_container, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"Successfully saved uploaded file to: {file_path_in_container}")
        
        # Return the path inside the container, which is what the RAG tool needs
        return JSONResponse(
            status_code=200,
            content={
                "message": "File uploaded successfully",
                "file_path": file_path_in_container,
                "file_name": safe_filename,
            },
        )
    except Exception as e:
        logger.error(f"Could not save uploaded file '{safe_filename}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not save file: {e}")

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "OpenWebUI MCP Tool Proxy is running. See /docs for the OpenAPI specification of available tools."}
