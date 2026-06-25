"""
This module is the bridge between the A2A (Agent-to-Agent) protocol server
and the agentic framework's core logic.

It defines the `A2AExecutor`, which is responsible for handling the business
logic of an incoming A2A request after it has been authenticated and authorized.

Architectural Role:
-   **Execution Layer:** Sits behind the A2A server and is responsible for
    executing the delegated task.
-   **Orchestration Proxy:** In the three-tier architecture, it does not execute
    the agent logic directly. Instead, it acts as a secure proxy to the
    `orchestration_service`.
-   **Context Propagation:** Its primary role is to receive the task and the
    original user's JWT from the A2A message, validate the token to establish
    the user's security context, and then forward the entire request to the
    `orchestration_service`'s Response API endpoint, passing the user's JWT in
    the `X-Forwarded-User-Token` header.

Event-based communication (a2a-sdk 0.3.22):
    The executor publishes events to the EventQueue rather than using a
    task_updater (which does not exist on RequestContext in this SDK version).
    Valid event types: Message | Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent.
    The SDK's _run_event_stream() calls queue.close() after execute() returns,
    so the executor must NOT close the queue itself.
"""
import asyncio
import os
import time
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import TaskState, TaskStatus, TaskStatusUpdateEvent
from a2a.utils.message import new_agent_text_message
import httpx
from ....logger_config import get_logger
from ....core.observability.smart_logger import create_trace
# Imported at module level (PEP 8) for user token validation.
# NOTE: Two separate JWT validations occur in the A2A flow:
#   1. KeycloakContextBuilder.build() validates the SERVICE token (gateway-client S2S credential)
#      using synchronous JWKS fetch — this authenticates the calling gateway.
#   2. validate_jwt_multi_stack() below validates the FORWARDED USER token embedded in the
#      A2A message — this authenticates the original end-user whose request is being delegated.
#      Uses multi-stack validation (Phase 0b, Session 80) to accept JWTs from trusted external
#      Keycloak instances in cross-facility A2A deployments (configured via TRUSTED_KEYCLOAK_URLS).
from ....core.auth import validate_jwt_multi_stack, JWTValidationError

ORCHESTRATION_SERVICE_URL = os.getenv("ORCHESTRATION_SERVICE_URL", "http://orchestration_service:8084")

logger = get_logger(__name__)


class A2AExecutor(AgentExecutor):
    """
    The bridge between the A2A server and the ScientificWorkflowAgent.

    This executor handles incoming A2A requests by securely proxying them to the
    central orchestration_service, ensuring that the original user's identity
    is maintained throughout the multi-gateway workflow.

    Events are published to the EventQueue (not via task_updater):
    - TaskStatusUpdateEvent with state=working  → signals work has started
    - Message (agent text)                      → the actual response
    - TaskStatusUpdateEvent with state=completed/failed → signals completion
    """

    def __init__(self):
        self.active_tasks = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """
        Executes the agent's logic for a given A2A request context.

        Args:
            context: The A2A request context containing the message, task ID, etc.
            event_queue: The queue to publish events to. Closed by the SDK after return.
        """
        task_id = context.task_id
        context_id = context.context_id
        logger.info(f"[A2A_EXECUTOR] Starting execution for task_id: {task_id}")

        with create_trace(logger, "a2a_executor", metadata={"task_id": task_id, "context_id": context_id}) as t:
            try:
                # 1. Extract custom parameters from the incoming message
                with t.span("task_extraction", input={"task_id": task_id}) as s:
                    incoming_message = context.message
                    if not incoming_message or not incoming_message.parts:
                        raise ValueError("Incoming A2A message is missing content.")

                    task_params = {}
                    for part in incoming_message.parts:
                        if part.root.kind == "data":
                            task_params = part.root.data
                            break

                    task_content = task_params.get("task")
                    user_token = task_params.get("user_token")
                    multi_gateway_session_id = task_params.get("multi_gateway_session_id")

                    if not all([task_content, user_token, multi_gateway_session_id]):
                        raise ValueError("Missing required parameters in A2A message: task, user_token, multi_gateway_session_id")

                    extract_ms = s.end(output={"session_id": multi_gateway_session_id, "task_length": len(task_content) if task_content else 0})

                # Correlate trace with shared session_id
                t.update_session_id(multi_gateway_session_id)

                logger.info(
                    f"[A2A_EXECUTOR] task_extraction: session={multi_gateway_session_id}, "
                    f"task_length={len(task_content) if task_content else 0}, extract_ms={extract_ms:.1f}"
                )

                # 2. Validate the forwarded user token (multi-stack aware, Phase 0b)
                # Uses validate_jwt_multi_stack() to accept JWTs from trusted external
                # Keycloak instances (configured via TRUSTED_KEYCLOAK_URLS env var).
                with t.span("user_token_validation") as s:
                    try:
                        credentials = await validate_jwt_multi_stack(user_token)
                        logger.info(
                            f"[A2A_EXECUTOR] Validated user token: "
                            f"user={credentials.username}, groups={credentials.groups}"
                        )
                    except JWTValidationError as e:
                        raise ValueError(f"Invalid user token forwarded from calling gateway: {e}") from e
                    validation_ms = s.end()

                logger.info(f"[A2A_EXECUTOR] user_token_validation: validation_ms={validation_ms:.1f}")

                # 3. Signal that work has started
                await event_queue.enqueue_event(TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(state=TaskState.working),
                    final=False,
                ))

                # 4. Proxy the request to the orchestration service using Response API
                with t.span("orchestration_proxy", input={"url": f"{ORCHESTRATION_SERVICE_URL}/v1/responses/completions"}) as s:
                    request_payload = {
                        "model": "agentic-framework:scientific-agent-v1",
                        "messages": [
                            {
                                "role": "user",
                                "content": task_content
                            }
                        ],
                        "stream": False,
                        "session_id": multi_gateway_session_id,
                        "mcp_session_id": multi_gateway_session_id,
                        "gateway_session_id": multi_gateway_session_id,
                        "api_type": "response"
                    }

                    async with httpx.AsyncClient() as client:
                        http_task = asyncio.create_task(client.post(
                            f"{ORCHESTRATION_SERVICE_URL}/v1/responses/completions",
                            json=request_payload,
                            headers={"X-Forwarded-User-Token": user_token},
                            timeout=300.0,
                        ))
                        self.active_tasks[task_id] = http_task
                        response = await http_task

                        if response.status_code >= 400:
                            error_body = response.text[:500]
                            raise ValueError(
                                f"Orchestration service returned {response.status_code}: {error_body}"
                            )
                        result = response.json()

                        # Extract content from Response API format
                        if "choices" in result and len(result["choices"]) > 0:
                            choice = result["choices"][0]
                            if "message" in choice and "content" in choice["message"]:
                                final_output = choice["message"]["content"]
                            else:
                                final_output = "Response API returned message without content."
                        else:
                            final_output = "Response API returned no choices."

                    proxy_ms = s.end(output={"status_code": response.status_code, "output_length": len(final_output)})

                logger.info(
                    f"[A2A_EXECUTOR] orchestration_proxy: status={response.status_code}, "
                    f"output_length={len(final_output)}, proxy_ms={proxy_ms:.1f}"
                )

                # 5. Publish the final result as an agent message
                with t.span("response_publish") as s:
                    final_message = new_agent_text_message(
                        text=final_output,
                        context_id=context_id,
                        task_id=task_id,
                    )
                    await event_queue.enqueue_event(final_message)

                    # 6. Signal task completion
                    await event_queue.enqueue_event(TaskStatusUpdateEvent(
                        task_id=task_id,
                        context_id=context_id,
                        status=TaskStatus(state=TaskState.completed),
                        final=True,
                    ))
                    publish_ms = s.end()

                total_ms = extract_ms + validation_ms + proxy_ms + publish_ms
                logger.info(
                    f"[A2A_EXECUTOR] Completed: session={multi_gateway_session_id}, "
                    f"total_ms={total_ms:.1f}, extract_ms={extract_ms:.1f}, "
                    f"validation_ms={validation_ms:.1f}, proxy_ms={proxy_ms:.1f}, publish_ms={publish_ms:.1f}"
                )

            except Exception as e:
                logger.error(f"[A2A_EXECUTOR] Error: {e}", exc_info=True)
                # Publish failure status with error details
                error_message = new_agent_text_message(
                    text=f"An internal error occurred: {e}",
                    context_id=context_id,
                    task_id=task_id,
                )
                await event_queue.enqueue_event(error_message)
                await event_queue.enqueue_event(TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(
                        state=TaskState.failed,
                        message=error_message,
                    ),
                    final=True,
                ))
            finally:
                if task_id in self.active_tasks:
                    del self.active_tasks[task_id]
                # NOTE: Do NOT close the queue here. The SDK's _run_event_stream()
                # calls queue.close() after execute() returns.

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """
        Handles a request to cancel an ongoing task.
        """
        task_id = context.task_id
        context_id = context.context_id
        logger.info(f"Cancellation requested for task {task_id}.")
        if task_id in self.active_tasks:
            try:
                self.active_tasks[task_id].cancel()
                logger.info(f"Task {task_id} cancelled successfully.")
            except Exception as e:
                logger.error(f"Error cancelling task {task_id}: {e}", exc_info=True)
        else:
            logger.warning(f"Task {task_id} not found for cancellation.")
        await event_queue.enqueue_event(TaskStatusUpdateEvent(
            task_id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.canceled),
            final=True,
        ))
        # NOTE: Do NOT close the queue here. The SDK handles it.
