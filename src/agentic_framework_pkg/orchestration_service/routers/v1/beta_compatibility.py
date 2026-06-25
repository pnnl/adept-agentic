"""
Beta API compatibility layer for OpenAI client libraries.

This module provides /v1/beta/* endpoints that alias to the main /v1/* endpoints
to ensure compatibility with OpenAI Python SDK and other client libraries.

Since this is in the orchestration service, we directly call the endpoint functions
rather than proxying like the agent gateway does.
"""
from fastapi import APIRouter, Request, Depends
from ...auth import get_forwarded_user
from ....core.auth import AuthCredentials
from . import assistants, threads, runs, files

router = APIRouter(prefix="/beta")

# Create beta-prefixed versions of all routes that simply redirect to the main routes
# Since we're in the orchestration service, we don't need proxying - just route aliasing

@router.api_route("/assistants", methods=["GET", "POST"])
async def beta_assistants_list_create(request: Request, user: AuthCredentials = Depends(get_forwarded_user)):
    """Beta alias for assistants list/create."""
    if request.method == "POST":
        # Parse the request body for create with proper alias handling
        body = await request.json()
        # Use model_validate to handle field aliases properly
        assistant_request = assistants.AssistantCreateRequest.model_validate(body)
        return await assistants.create_assistant(assistant_request, user)
    else:
        return await assistants.list_assistants(user)

@router.api_route("/assistants/{assistant_id}", methods=["GET", "POST", "DELETE"])
async def beta_assistants_detail(assistant_id: str, request: Request, user: AuthCredentials = Depends(get_forwarded_user)):
    """Beta alias for assistant detail operations."""
    if request.method == "GET":
        return await assistants.get_assistant(assistant_id, user)
    elif request.method == "POST":
        body = await request.json()
        # Use model_validate to handle field aliases properly
        assistant_request = assistants.AssistantUpdateRequest.model_validate(body)
        return await assistants.update_assistant(assistant_id, assistant_request, user)
    elif request.method == "DELETE":
        return await assistants.delete_assistant(assistant_id, user)

@router.api_route("/threads", methods=["GET", "POST"])
async def beta_threads_list_create(request: Request, user: AuthCredentials = Depends(get_forwarded_user)):
    """Beta alias for threads list/create."""
    if request.method == "POST":
        return await threads.create_thread(user)
    else:
        return await threads.list_threads(user)

@router.api_route("/threads/{thread_id}", methods=["GET", "POST", "DELETE"])
async def beta_threads_detail(thread_id: str, request: Request, user: AuthCredentials = Depends(get_forwarded_user)):
    """Beta alias for thread detail operations."""
    if request.method == "GET":
        return await threads.get_thread(thread_id, user)
    elif request.method == "POST":
        body = await request.json()
        return await threads.update_thread(thread_id, threads.ThreadUpdateRequest(**body), user)
    elif request.method == "DELETE":
        return await threads.delete_thread(thread_id, user)

@router.api_route("/threads/{thread_id}/messages", methods=["GET", "POST"])
async def beta_thread_messages(thread_id: str, request: Request, user: AuthCredentials = Depends(get_forwarded_user)):
    """Beta alias for thread messages."""
    if request.method == "POST":
        body = await request.json()
        return await threads.create_message(thread_id, threads.MessageCreateRequest(**body), user)
    else:
        return await threads.list_messages(thread_id, user)

@router.api_route("/threads/{thread_id}/messages/{message_id}", methods=["GET", "POST"])
async def beta_thread_message_detail(thread_id: str, message_id: str, request: Request, user: AuthCredentials = Depends(get_forwarded_user)):
    """Beta alias for thread message detail."""
    if request.method == "GET":
        return await threads.get_message(thread_id, message_id, user)
    elif request.method == "POST":
        body = await request.json()
        return await threads.update_message(thread_id, message_id, threads.MessageUpdateRequest(**body), user)

@router.api_route("/threads/{thread_id}/runs", methods=["GET", "POST"])
async def beta_thread_runs(thread_id: str, request: Request, user: AuthCredentials = Depends(get_forwarded_user)):
    """Beta alias for thread runs."""
    if request.method == "POST":
        body = await request.json()
        return await runs.create_run(thread_id, runs.RunCreateRequest(**body), user)
    else:
        return await runs.list_runs(thread_id, user)

@router.api_route("/threads/{thread_id}/runs/{run_id}", methods=["GET", "POST"])
async def beta_thread_run_detail(thread_id: str, run_id: str, request: Request, user: AuthCredentials = Depends(get_forwarded_user)):
    """Beta alias for thread run detail."""
    if request.method == "GET":
        return await runs.get_run(thread_id, run_id, user)
    elif request.method == "POST":
        body = await request.json()
        return await runs.update_run(thread_id, run_id, runs.RunUpdateRequest(**body), user)

@router.api_route("/threads/{thread_id}/runs/{run_id}/steps", methods=["GET"])
async def beta_thread_run_steps(thread_id: str, run_id: str, user: AuthCredentials = Depends(get_forwarded_user)):
    """Beta alias for thread run steps."""
    return await runs.list_run_steps(thread_id, run_id, user)

@router.api_route("/threads/{thread_id}/runs/{run_id}/steps/{step_id}", methods=["GET"])
async def beta_thread_run_step_detail(thread_id: str, run_id: str, step_id: str, user: AuthCredentials = Depends(get_forwarded_user)):
    """Beta alias for thread run step detail."""
    return await runs.get_run_step(thread_id, run_id, step_id, user)

@router.api_route("/threads/{thread_id}/runs/{run_id}/cancel", methods=["POST"])
async def beta_cancel_run(thread_id: str, run_id: str, user: AuthCredentials = Depends(get_forwarded_user)):
    """Beta alias for canceling runs."""
    return await runs.cancel_run(thread_id, run_id, user)

@router.api_route("/threads/{thread_id}/runs/{run_id}/submit_tool_outputs", methods=["POST"])
async def beta_submit_tool_outputs(thread_id: str, run_id: str, request: Request, user: AuthCredentials = Depends(get_forwarded_user)):
    """Beta alias for submitting tool outputs."""
    body = await request.json()
    return await runs.submit_tool_outputs(thread_id, run_id, runs.ToolOutputsRequest(**body), user)