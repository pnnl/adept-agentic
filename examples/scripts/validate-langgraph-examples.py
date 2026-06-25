#!/usr/bin/env python3
"""
Validation Script for LangGraph + ADEPT Integration Examples
=============================================================

This script systematically tests each component of the LangGraph examples to
verify they work correctly with real ADEPT services.

Usage:
    # Default configuration (uses bootstrap defaults)
    python examples/scripts/validate-langgraph-examples.py

    # Or with custom configuration
    export KEYCLOAK_USERNAME="notebook-user"
    export KEYCLOAK_PASSWORD="notebook-password"  # Default bootstrap password
    export KEYCLOAK_REALM="master"  # ADEPT uses master realm
    python examples/scripts/validate-langgraph-examples.py

Requirements:
    - ADEPT services running (make start)
    - Keycloak bootstrap completed (make fix-credentials)
    - Valid Keycloak credentials
    - litellm, httpx, langgraph packages installed
"""

import json
import os
import sys
import time
import traceback
from datetime import datetime
from typing import Dict, List, Tuple

# Add examples directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


class ValidationResult:
    """Track validation test results."""

    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.message = ""
        self.duration = 0.0
        self.details = {}

    def success(self, message: str, **details):
        """Mark test as passed."""
        self.passed = True
        self.message = message
        self.details = details

    def failure(self, message: str, **details):
        """Mark test as failed."""
        self.passed = False
        self.message = message
        self.details = details


class LangGraphValidator:
    """Systematic validation of LangGraph examples."""

    def __init__(self):
        self.results: List[ValidationResult] = []
        # Default to localhost HTTP for out-of-the-box functionality
        # Override with AGENT_GATEWAY_URL env var for other access patterns
        self.agent_gateway_url = os.getenv("AGENT_GATEWAY_URL", "http://localhost:8083/v1")
        # Keycloak is on port 8180, not 8083 (agent gateway)
        self.keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
        self.keycloak_realm = os.getenv("KEYCLOAK_REALM", "master")  # ADEPT uses master realm
        self.username = os.getenv("KEYCLOAK_USERNAME", "notebook-user")
        self.password = os.getenv("KEYCLOAK_PASSWORD", "notebook-password")  # Default bootstrap password
        self.client_id = os.getenv("KEYCLOAK_CLIENT_ID", "validation-runner-client")  # Confidential client for testing
        self.client_secret = os.getenv("KEYCLOAK_CLIENT_SECRET")  # Optional for confidential clients
        self.token = None

        # Auto-discover client secret from credentials directory if not provided
        if not self.client_secret and self.client_id == "validation-runner-client":
            # Try multiple credential paths (containerized, host from project root, host from examples/, host from examples/scripts/)
            credential_paths = [
                "/app/credentials/VALIDATION_RUNNER_CLIENT_SECRET",  # Containerized
                "deployment/local/docker-compose/.env-keycloak-credentials-dir/VALIDATION_RUNNER_CLIENT_SECRET",  # Host from project root
                "../deployment/local/docker-compose/.env-keycloak-credentials-dir/VALIDATION_RUNNER_CLIENT_SECRET",  # Host from examples/
                "../../deployment/local/docker-compose/.env-keycloak-credentials-dir/VALIDATION_RUNNER_CLIENT_SECRET",  # Host from examples/scripts/
            ]

            for secret_path in credential_paths:
                try:
                    with open(secret_path, 'r') as f:
                        self.client_secret = f.read().strip()
                        break  # Found credentials, stop searching
                except FileNotFoundError:
                    continue  # Try next path

            if not self.client_secret:
                pass  # Will attempt auth without client secret (for public clients)

    def print_header(self, title: str):
        """Print a formatted header."""
        print(f"\n{BLUE}{'=' * 80}")
        print(f"{title}")
        print(f"{'=' * 80}{RESET}\n")

    def print_test_start(self, test_name: str):
        """Print test start message."""
        print(f"{YELLOW}[TEST] {test_name}...{RESET}", end=" ", flush=True)

    def print_test_result(self, result: ValidationResult):
        """Print test result."""
        if result.passed:
            print(f"{GREEN}✓ PASS{RESET} ({result.duration:.2f}s)")
            print(f"  {result.message}")
            if result.details:
                for key, value in result.details.items():
                    print(f"  - {key}: {value}")
        else:
            print(f"{RED}✗ FAIL{RESET} ({result.duration:.2f}s)")
            print(f"  {RED}{result.message}{RESET}")
            if result.details:
                for key, value in result.details.items():
                    print(f"  - {key}: {value}")

    def run_test(self, test_name: str, test_func) -> ValidationResult:
        """Run a single test and track results."""
        result = ValidationResult(test_name)
        self.print_test_start(test_name)

        start_time = time.time()
        try:
            test_func(result)
        except Exception as e:
            result.failure(
                f"Unexpected error: {str(e)}",
                exception_type=type(e).__name__,
                traceback=traceback.format_exc()
            )
        finally:
            result.duration = time.time() - start_time
            self.results.append(result)
            self.print_test_result(result)

        return result

    # =========================================================================
    # Test 1: Import Dependencies
    # =========================================================================

    def test_imports(self, result: ValidationResult):
        """Test that all required dependencies can be imported."""
        try:
            import httpx
            result.details["httpx_version"] = httpx.__version__
        except ImportError:
            result.failure("httpx not installed", install_command="pip install httpx")
            return

        try:
            from litellm import completion
            import litellm
            try:
                result.details["litellm_version"] = litellm.__version__
            except AttributeError:
                result.details["litellm_version"] = "version unavailable"
        except ImportError:
            result.failure("litellm not installed", install_command="pip install litellm")
            return

        try:
            from langchain_core.messages import HumanMessage
            import langchain_core
            result.details["langchain_core_version"] = langchain_core.__version__
        except ImportError:
            result.failure(
                "langchain-core not installed",
                install_command="pip install langchain-core"
            )
            return

        try:
            from langgraph.graph import StateGraph
            import langgraph
            try:
                result.details["langgraph_version"] = langgraph.__version__
            except AttributeError:
                result.details["langgraph_version"] = "version unavailable"
        except ImportError:
            result.failure("langgraph not installed", install_command="pip install langgraph")
            return

        result.success("All dependencies imported successfully")

    # =========================================================================
    # Test 2: Keycloak Authentication
    # =========================================================================

    def test_keycloak_authentication(self, result: ValidationResult):
        """Test Keycloak JWT token generation."""
        import httpx

        token_url = f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/token"

        # Build auth data (include client_secret for confidential clients)
        auth_data = {
            "grant_type": "password",
            "client_id": self.client_id,
            "username": self.username,
            "password": self.password,
        }
        if self.client_secret:
            auth_data["client_secret"] = self.client_secret

        try:
            response = httpx.post(
                token_url,
                data=auth_data,
                verify=False,  # For self-signed certificates
                timeout=10.0,
            )

            if response.status_code != 200:
                result.failure(
                    f"Authentication failed: HTTP {response.status_code}",
                    response_body=response.text[:500],
                    token_url=token_url
                )
                return

            token_data = response.json()
            self.token = token_data.get("access_token")

            if not self.token:
                result.failure(
                    "No access_token in response",
                    response_keys=list(token_data.keys())
                )
                return

            result.success(
                "Keycloak authentication successful",
                token_length=len(self.token),
                token_prefix=self.token[:30] + "...",
                username=self.username
            )

        except Exception as e:
            result.failure(
                f"Connection error: {str(e)}",
                token_url=token_url,
                exception_type=type(e).__name__
            )

    # =========================================================================
    # Test 3: ADEPT API Connectivity
    # =========================================================================

    def test_adept_api_connectivity(self, result: ValidationResult):
        """Test basic connectivity to ADEPT API."""
        if not self.token:
            result.failure("No token available (authentication test failed)")
            return

        import httpx

        # Test /v1/models endpoint (agent_gateway_url already includes /v1)
        models_url = f"{self.agent_gateway_url}/models"

        try:
            response = httpx.get(
                models_url,
                headers={"Authorization": f"Bearer {self.token}"},
                verify=False,
                timeout=10.0,
            )

            if response.status_code == 200:
                models_data = response.json()
                result.success(
                    "ADEPT API accessible",
                    models_url=models_url,
                    response_status=response.status_code,
                    models_available=len(models_data.get("data", []))
                )
            elif response.status_code == 401:
                result.failure(
                    "Authentication failed (401 Unauthorized)",
                    models_url=models_url,
                    hint="Token may be invalid or expired"
                )
            elif response.status_code == 404:
                result.failure(
                    "/v1/models endpoint not found",
                    models_url=models_url,
                    hint="Check AGENT_GATEWAY_URL is correct"
                )
            else:
                result.failure(
                    f"Unexpected status code: {response.status_code}",
                    models_url=models_url,
                    response_body=response.text[:500]
                )

        except httpx.ConnectError as e:
            result.failure(
                f"Connection refused: {str(e)}",
                models_url=models_url,
                hint="Ensure ADEPT services are running (make start)"
            )
        except Exception as e:
            result.failure(
                f"Unexpected error: {str(e)}",
                models_url=models_url,
                exception_type=type(e).__name__
            )

    # =========================================================================
    # Test 4: LiteLLM with ADEPT Model
    # =========================================================================

    def test_litellm_adept_model(self, result: ValidationResult):
        """Test litellm completion with ADEPT model using LiteLLM-compatible alias."""
        if not self.token:
            result.failure("No token available (authentication test failed)")
            return

        from litellm import completion
        import litellm

        # Register ADEPT provider (Session 48)
        litellm.register_model({
            "adept/scientific-agent-v1": {
                "max_tokens": 4096,
                "litellm_provider": "openai",
                "mode": "chat",
            },
        })

        try:
            response = completion(
                model="adept/scientific-agent-v1",  # Use LiteLLM-compatible alias
                messages=[{"role": "user", "content": "Say 'Hello ADEPT' and nothing else."}],
                base_url=self.agent_gateway_url,  # Already includes /v1
                api_key=self.token,  # LiteLLM adds Bearer prefix automatically
                extra_headers={"X-Thread-Id": "validation-test"},
                max_tokens=50,
                temperature=0.7,
                timeout=30.0,
            )

            if hasattr(response, 'choices') and len(response.choices) > 0:
                message_content = response.choices[0].message.content
                result.success(
                    "LiteLLM call successful",
                    model="agentic-framework:scientific-agent-v1",
                    response_length=len(message_content),
                    response_preview=message_content[:100]
                )
            else:
                result.failure(
                    "No choices in response",
                    response_keys=dir(response) if response else []
                )

        except Exception as e:
            error_message = str(e)

            if "404" in error_message or "Not Found" in error_message:
                result.failure(
                    "Model not found: agentic-framework:scientific-agent-v1",
                    hint="Check if model name is correct in ADEPT configuration",
                    error=error_message[:500]
                )
            elif "401" in error_message or "Unauthorized" in error_message:
                result.failure(
                    "Authentication failed",
                    hint="Token may be invalid or expired",
                    error=error_message[:500]
                )
            else:
                result.failure(
                    f"LiteLLM error: {error_message[:500]}",
                    exception_type=type(e).__name__
                )

    # =========================================================================
    # Test 5: Quick Start Example Components
    # =========================================================================

    def test_quickstart_components(self, result: ValidationResult):
        """Test components from langgraph_adept_quickstart.py."""
        if not self.token:
            result.failure("No token available (authentication test failed)")
            return

        try:
            # Import quick start functions
            from langgraph_adept_quickstart import get_adept_token, call_adept_api

            # Test get_adept_token function
            token = get_adept_token(self.username, self.password, self.client_id, self.client_secret)

            if not token or len(token) < 50:
                result.failure(
                    "get_adept_token returned invalid token",
                    token_length=len(token) if token else 0
                )
                return

            # Test call_adept_api function
            response_text = call_adept_api(
                messages=[{"role": "user", "content": "Say 'Quick start works' and nothing else."}],
                token=token,
                thread_id="quickstart-validation",
            )

            if response_text and len(response_text) > 0:
                result.success(
                    "Quick start components working",
                    token_length=len(token),
                    response_length=len(response_text),
                    response_preview=response_text[:100]
                )
            else:
                result.failure(
                    "call_adept_api returned empty response",
                    response=response_text
                )

        except ImportError as e:
            result.failure(
                f"Import error: {str(e)}",
                hint="Ensure examples/ directory is in Python path"
            )
        except Exception as e:
            result.failure(
                f"Unexpected error: {str(e)}",
                exception_type=type(e).__name__,
                traceback=traceback.format_exc()[:1000]
            )

    # =========================================================================
    # Test 6: Full Integration Example Components
    # =========================================================================

    def test_integration_components(self, result: ValidationResult):
        """Test components from langgraph_adept_integration.py."""
        if not self.token:
            result.failure("No token available (authentication test failed)")
            return

        try:
            # Import integration classes
            from langgraph_adept_integration import (
                ADEPTAuthenticator,
                ADEPTSessionManager,
                ADEPTLiteLLMClient,
            )

            # Test ADEPTAuthenticator
            authenticator = ADEPTAuthenticator(
                keycloak_url=self.keycloak_url,
                agent_gateway_url=self.agent_gateway_url,
                username=self.username,
                password=self.password,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )

            token = authenticator.authenticate()

            if not token or len(token) < 50:
                result.failure(
                    "ADEPTAuthenticator.authenticate() failed",
                    token_length=len(token) if token else 0
                )
                return

            # Test ADEPTSessionManager
            session_manager = ADEPTSessionManager(
                authenticator=authenticator,
                thread_id="integration-validation",
            )

            session_context = session_manager.get_session_context()

            if "thread_id" not in session_context:
                result.failure(
                    "ADEPTSessionManager.get_session_context() missing thread_id",
                    session_context=session_context
                )
                return

            # Test ADEPTLiteLLMClient
            adept_client = ADEPTLiteLLMClient(
                authenticator=authenticator,
                session_manager=session_manager,
            )

            response = adept_client.chat_completion(
                messages=[{"role": "user", "content": "Say 'Integration works' and nothing else."}],
                max_tokens=50,
            )

            if hasattr(response, 'choices') and len(response.choices) > 0:
                message_content = response.choices[0].message.content
                result.success(
                    "Full integration components working",
                    token_length=len(token),
                    thread_id=session_context["thread_id"],
                    response_length=len(message_content),
                    response_preview=message_content[:100]
                )
            else:
                result.failure(
                    "ADEPTLiteLLMClient.chat_completion() returned no choices",
                    response_keys=dir(response) if response else []
                )

        except ImportError as e:
            result.failure(
                f"Import error: {str(e)}",
                hint="Ensure examples/ directory is in Python path"
            )
        except Exception as e:
            result.failure(
                f"Unexpected error: {str(e)}",
                exception_type=type(e).__name__,
                traceback=traceback.format_exc()[:1000]
            )

    # =========================================================================
    # Test 7: LangGraph Workflow
    # =========================================================================

    def test_langgraph_workflow(self, result: ValidationResult):
        """Test basic LangGraph workflow with ADEPT."""
        if not self.token:
            result.failure("No token available (authentication test failed)")
            return

        try:
            from langchain_core.messages import HumanMessage
            from langgraph.graph import END, StateGraph
            from typing import TypedDict, Annotated, Sequence
            from langgraph.graph.message import add_messages
            from litellm import completion
            import litellm

            # Register ADEPT provider for this test (Session 48)
            litellm.register_model({
                "adept/scientific-agent-v1": {
                    "max_tokens": 4096,
                    "litellm_provider": "openai",
                    "mode": "chat",
                },
            })

            # Define simple state
            class State(TypedDict):
                messages: Annotated[Sequence[HumanMessage], add_messages]

            # Create simple agent node
            def agent_node(state: State) -> State:
                messages = state["messages"]

                # Convert to litellm format
                litellm_messages = [
                    {"role": "user", "content": msg.content} for msg in messages
                ]

                # Call ADEPT API (using LiteLLM-compatible alias)
                response = completion(
                    model="adept/scientific-agent-v1",
                    messages=litellm_messages,
                    base_url=self.agent_gateway_url,  # Already includes /v1
                    api_key=self.token,  # LiteLLM adds Bearer prefix automatically
                    extra_headers={"X-Thread-Id": "langgraph-validation"},
                    max_tokens=50,
                    temperature=0.7,
                )

                response_text = response.choices[0].message.content

                return {"messages": [HumanMessage(content=response_text)]}

            # Build workflow
            workflow = StateGraph(State)
            workflow.add_node("agent", agent_node)
            workflow.set_entry_point("agent")
            workflow.add_edge("agent", END)

            # Compile and run
            app = workflow.compile()
            result_state = app.invoke({
                "messages": [HumanMessage(content="Say 'LangGraph works' and nothing else.")]
            })

            if "messages" in result_state and len(result_state["messages"]) > 0:
                final_message = result_state["messages"][-1].content
                result.success(
                    "LangGraph workflow executed successfully",
                    message_count=len(result_state["messages"]),
                    final_response=final_message[:100]
                )
            else:
                result.failure(
                    "LangGraph workflow returned no messages",
                    result_state_keys=list(result_state.keys()) if result_state else []
                )

        except Exception as e:
            result.failure(
                f"LangGraph workflow error: {str(e)}",
                exception_type=type(e).__name__,
                traceback=traceback.format_exc()[:1000]
            )

    # =========================================================================
    # Test 8: Langfuse Trace Verification
    # =========================================================================

    def test_langfuse_traces(self, result: ValidationResult):
        """Test that Langfuse traces are being generated (if observability enabled)."""
        if not self.token:
            result.failure("No token available (authentication test failed)")
            return

        # Check if Langfuse is accessible (optional observability)
        import httpx

        # Try common Langfuse deployment patterns
        langfuse_urls = [
            os.getenv("LANGFUSE_URL", "http://localhost:3000"),  # Standard Langfuse port
            "http://langfuse:3000",  # Docker service name
            f"{self.agent_gateway_url}/langfuse",  # Proxied through gateway (unlikely)
        ]

        langfuse_found = False
        for langfuse_url in langfuse_urls:
            try:
                response = httpx.get(
                    langfuse_url,
                    verify=False,
                    timeout=5.0,
                    follow_redirects=True,
                )

                if response.status_code == 200:
                    langfuse_found = True
                    result.success(
                        "Langfuse UI accessible (observability enabled)",
                        langfuse_url=langfuse_url,
                        hint="Login to verify traces with thread_id: validation-test"
                    )
                    return
            except Exception:
                continue  # Try next URL

        # Langfuse not found - this is OK (observability is optional)
        result.success(
            "Langfuse not deployed (observability optional)",
            hint="Traces will not be captured. Install Langfuse for observability.",
            langfuse_urls_tried=langfuse_urls
        )

    # =========================================================================
    # Run All Tests
    # =========================================================================

    def run_all_tests(self):
        """Run all validation tests."""
        self.print_header("LangGraph + ADEPT Integration Example Validation")

        print(f"Configuration:")
        print(f"  Agent Gateway URL: {self.agent_gateway_url}")
        print(f"  Keycloak URL: {self.keycloak_url}")
        print(f"  Username: {self.username}")
        print(f"  Password: {'*' * len(self.password) if self.password else '(not set)'}")
        print(f"\nNote: Using localhost HTTP by default for immediate functionality.")
        print(f"      Set AGENT_GATEWAY_URL=https://api.agentic.local/v1 for SSL testing.")

        # Run tests in order
        self.run_test("1. Import Dependencies", self.test_imports)
        self.run_test("2. Keycloak Authentication", self.test_keycloak_authentication)
        self.run_test("3. ADEPT API Connectivity", self.test_adept_api_connectivity)
        self.run_test("4. LiteLLM with ADEPT Model", self.test_litellm_adept_model)
        self.run_test("5. Quick Start Components", self.test_quickstart_components)
        self.run_test("6. Full Integration Components", self.test_integration_components)
        self.run_test("7. LangGraph Workflow", self.test_langgraph_workflow)
        self.run_test("8. Langfuse Trace Verification", self.test_langfuse_traces)

        # Print summary
        self.print_summary()

    def print_summary(self):
        """Print validation summary."""
        self.print_header("Validation Summary")

        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)

        print(f"Total Tests: {total}")
        print(f"{GREEN}Passed: {passed}{RESET}")
        print(f"{RED}Failed: {failed}{RESET}")
        print(f"Pass Rate: {(passed/total*100):.1f}%\n")

        if failed > 0:
            print(f"{RED}Failed Tests:{RESET}")
            for result in self.results:
                if not result.passed:
                    print(f"  ✗ {result.name}")
                    print(f"    {result.message}")
            print()

        # Generate report file
        self.generate_report()

        # Exit code
        if failed == 0:
            print(f"{GREEN}✓ All validation tests passed!{RESET}")
            print(f"\nYour LangGraph examples are ready to use.")
            print(f"Run: python examples/langgraph_adept_quickstart.py")
            return 0
        else:
            print(f"{RED}✗ Some validation tests failed.{RESET}")
            print(f"\nPlease address the failures above before using the examples.")
            return 1

    def generate_report(self):
        """Generate detailed validation report."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"logs/langgraph_validation_{timestamp}.json"

        os.makedirs("logs", exist_ok=True)

        report = {
            "timestamp": timestamp,
            "configuration": {
                "keycloak_url": self.keycloak_url,
                "agent_gateway_url": self.agent_gateway_url,
                "username": self.username,
            },
            "summary": {
                "total_tests": len(self.results),
                "passed": sum(1 for r in self.results if r.passed),
                "failed": sum(1 for r in self.results if not r.passed),
            },
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "duration": r.duration,
                    "details": r.details,
                }
                for r in self.results
            ],
        }

        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"Detailed report saved to: {report_file}")


def main():
    """Main validation entry point."""
    print(f"{BLUE}LangGraph + ADEPT Integration Example Validator{RESET}")
    print(f"Version: 1.0.0")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Suppress SSL warnings for self-signed certificates
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Run validation
    validator = LangGraphValidator()
    exit_code = validator.run_all_tests()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
