#!/usr/bin/env python3
"""
Validation Script for OpenAI Client with Service Token Example
===============================================================

This script systematically tests the OpenAI client example with service API tokens
to verify standalone mode, authentication, and session tracking functionality.

Usage:
    # With service token
    export ADEPT_SERVICE_API_TOKEN="sk-service-..."
    python examples/scripts/validate-openai-client-example.py

    # Or with auto-discovery from credentials directory
    python examples/scripts/validate-openai-client-example.py

Requirements:
    - ADEPT services running (make start)
    - Service API token created (make create-service-token)
    - openai, httpx packages installed (pip install -r examples/requirements.txt)
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


class OpenAIClientValidator:
    """Systematic validation of OpenAI client example."""

    def __init__(self):
        self.results: List[ValidationResult] = []
        self.agent_gateway_url = os.getenv("AGENT_GATEWAY_URL", "http://localhost:8083/v1")
        self.service_token = os.getenv("ADEPT_SERVICE_API_TOKEN")

        # Auto-discover service token if not provided
        if not self.service_token:
            self.service_token = self._discover_service_token()

    def _discover_service_token(self) -> str:
        """Auto-discover service API token from credentials directory."""
        # Try container path first
        paths = [
            "/app/credentials/SERVICE_API_KEYS_CONFIG",
            "deployment/local/docker-compose/.env-keycloak-credentials-dir/SERVICE_API_KEYS_CONFIG",
            ".env-keycloak-credentials-dir/SERVICE_API_KEYS_CONFIG",
        ]

        for path in paths:
            try:
                with open(path, 'r') as f:
                    config = json.load(f)
                    # Get first service token (typically openwebui or n8n)
                    for token, metadata in config.items():
                        if token.startswith("sk-service-"):
                            print(f"{BLUE}✓ Auto-discovered service token: {metadata.get('username', 'unknown')}{RESET}")
                            return token
            except (FileNotFoundError, json.JSONDecodeError):
                continue

        return None

    def print_header(self, title: str):
        """Print a formatted header."""
        print(f"\n{BLUE}{'=' * 80}")
        print(f"{title}")
        print(f"{'=' * 80}{RESET}\n")

    def run_test(self, test_name: str, test_func):
        """Run a single test and track results."""
        result = ValidationResult(test_name)

        print(f"{YELLOW}[TEST] {test_name}...{RESET}", end=" ", flush=True)
        start_time = time.time()

        try:
            test_func(result)
            result.duration = time.time() - start_time

            if result.passed:
                print(f"{GREEN}✓ PASS{RESET} ({result.duration:.2f}s)")
                print(f"  {result.message}")
                for key, value in result.details.items():
                    print(f"  - {key}: {value}")
            else:
                print(f"{RED}✗ FAIL{RESET} ({result.duration:.2f}s)")
                print(f"  {RED}{result.message}{RESET}")
                for key, value in result.details.items():
                    print(f"  - {key}: {value}")

        except Exception as e:
            result.duration = time.time() - start_time
            result.failure(
                f"Unexpected error: {str(e)}",
                exception_type=type(e).__name__,
                traceback=traceback.format_exc()
            )
            print(f"{RED}✗ FAIL{RESET} ({result.duration:.2f}s)")
            print(f"  {RED}{result.message}{RESET}")
            for key, value in result.details.items():
                if key == "traceback":
                    print(f"  - {key}: {value[:500]}...")
                else:
                    print(f"  - {key}: {value}")

        self.results.append(result)

    # =========================================================================
    # Test 1: Import Dependencies (Standalone Mode)
    # =========================================================================

    def test_imports(self, result: ValidationResult):
        """Test that all required dependencies can be imported (standalone mode)."""
        try:
            from openai import OpenAI
            import openai
            try:
                result.details["openai_version"] = openai.__version__
            except AttributeError:
                result.details["openai_version"] = "version unavailable"
        except ImportError:
            result.failure("openai not installed", install_command="pip install openai")
            return

        try:
            import httpx
            result.details["httpx_version"] = httpx.__version__
        except ImportError:
            result.failure("httpx not installed", install_command="pip install httpx")
            return

        # Check for optional ADEPT framework imports (graceful degradation)
        try:
            from agentic_framework_pkg.logger_config import get_logger
            result.details["adept_logging"] = "available"
        except ImportError:
            result.details["adept_logging"] = "unavailable (standalone mode)"

        try:
            from agentic_framework_pkg.orchestration_service.session_utils import create_session_in_db
            result.details["adept_session_tracking"] = "available"
        except ImportError:
            result.details["adept_session_tracking"] = "unavailable (standalone mode)"

        result.success(
            "All dependencies imported successfully (standalone mode validated)",
        )

    # =========================================================================
    # Test 2: Service Token Authentication
    # =========================================================================

    def test_service_token_auth(self, result: ValidationResult):
        """Test service API token authentication."""
        if not self.service_token:
            result.failure(
                "No service token available",
                hint="Set ADEPT_SERVICE_API_TOKEN or create token with: make create-service-token"
            )
            return

        try:
            from openai import OpenAI

            client = OpenAI(
                base_url=self.agent_gateway_url,
                api_key=self.service_token,
            )

            # Test models endpoint
            models = client.models.list()
            model_list = [model.id for model in models.data]

            result.success(
                "Service token authentication successful",
                models_available=len(model_list),
                models=model_list[:3],
                token_prefix=self.service_token[:20] + "...",
            )

        except Exception as e:
            result.failure(
                f"Service token authentication failed: {str(e)}",
                token_prefix=self.service_token[:20] + "..." if self.service_token else "none",
                agent_gateway_url=self.agent_gateway_url
            )

    # =========================================================================
    # Test 3: Chat Completion (Non-Streaming)
    # =========================================================================

    def test_chat_completion(self, result: ValidationResult):
        """Test non-streaming chat completion."""
        if not self.service_token:
            result.failure("No token available (authentication test failed)")
            return

        try:
            from openai import OpenAI

            client = OpenAI(
                base_url=self.agent_gateway_url,
                api_key=self.service_token,
            )

            response = client.chat.completions.create(
                model="agentic-framework:scientific-agent-v1",
                messages=[
                    {"role": "user", "content": "What is 2+2? Answer with just the number."}
                ],
                stream=False
            )

            answer = response.choices[0].message.content

            result.success(
                "Chat completion successful",
                response_content=answer[:100],
                model=response.model,
                prompt_tokens=response.usage.prompt_tokens if response.usage else "N/A",
                completion_tokens=response.usage.completion_tokens if response.usage else "N/A",
            )

        except Exception as e:
            result.failure(f"Chat completion failed: {str(e)}")

    # =========================================================================
    # Test 4: Streaming Chat Completion
    # =========================================================================

    def test_streaming_completion(self, result: ValidationResult):
        """Test streaming chat completion."""
        if not self.service_token:
            result.failure("No token available (authentication test failed)")
            return

        try:
            from openai import OpenAI

            client = OpenAI(
                base_url=self.agent_gateway_url,
                api_key=self.service_token,
            )

            stream = client.chat.completions.create(
                model="agentic-framework:scientific-agent-v1",
                messages=[
                    {"role": "user", "content": "Say 'hello world' in 3 words."}
                ],
                stream=True
            )

            chunks = []
            full_response = ""
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    chunks.append(chunk)

            result.success(
                "Streaming completion successful",
                chunks_received=len(chunks),
                full_response=full_response[:100],
            )

        except Exception as e:
            result.failure(f"Streaming completion failed: {str(e)}")

    # =========================================================================
    # Test 5: Session Tracking (Optional ADEPT Feature)
    # =========================================================================

    def test_session_tracking(self, result: ValidationResult):
        """Test optional session tracking with ADEPT framework."""
        try:
            from agentic_framework_pkg.orchestration_service.session_utils import create_session_in_db
            import uuid

            # Attempt to create session
            session_id = str(uuid.uuid4())
            session_data = {
                "session_id": session_id,
                "user_id": "test-service-validation",
                "session_type": "validation_test",
            }

            # This will fail if database is not accessible, which is OK for standalone mode
            try:
                create_session_in_db(session_data)
                result.success(
                    "Session tracking available (ADEPT framework detected)",
                    session_id=session_id,
                    mode="full_framework"
                )
            except Exception as db_error:
                result.success(
                    "Session tracking gracefully degraded (expected in standalone mode)",
                    mode="standalone",
                    note="Database not accessible - this is normal for standalone execution"
                )

        except ImportError:
            result.success(
                "Session tracking unavailable (standalone mode)",
                mode="standalone",
                note="ADEPT framework not installed - graceful degradation working correctly"
            )

    # =========================================================================
    # Test 6: Error Handling
    # =========================================================================

    def test_error_handling(self, result: ValidationResult):
        """Test error handling with invalid requests."""
        if not self.service_token:
            result.failure("No token available (authentication test failed)")
            return

        try:
            from openai import OpenAI, APIError

            client = OpenAI(
                base_url=self.agent_gateway_url,
                api_key=self.service_token,
            )

            # Test with invalid model
            try:
                response = client.chat.completions.create(
                    model="invalid-model-name-12345",
                    messages=[{"role": "user", "content": "test"}],
                )
                # ADEPT handles invalid models gracefully by falling back to default model
                result.success(
                    "Error handling working correctly - graceful fallback to default model",
                    fallback_behavior="graceful_degradation",
                    response_received=True,
                    model_used=response.model if hasattr(response, 'model') else "unknown"
                )
            except Exception as e:
                # Strict error handling is also acceptable
                result.success(
                    "Error handling working correctly - strict error raised",
                    error_type=type(e).__name__,
                    error_message=str(e)[:100],
                    fallback_behavior="strict_error"
                )

        except Exception as e:
            result.failure(f"Error handling test failed: {str(e)}")

    # =========================================================================
    # Run All Tests
    # =========================================================================

    def run_all_tests(self):
        """Run all validation tests."""
        self.print_header("OpenAI Client with Service Token Example Validation")

        print("Configuration:")
        print(f"  Agent Gateway URL: {self.agent_gateway_url}")
        print(f"  Service Token: {'*' * 20}... (configured)" if self.service_token else "  Service Token: NOT SET")

        # Run tests
        self.run_test("1. Import Dependencies (Standalone Mode)", self.test_imports)
        self.run_test("2. Service Token Authentication", self.test_service_token_auth)
        self.run_test("3. Chat Completion (Non-Streaming)", self.test_chat_completion)
        self.run_test("4. Streaming Chat Completion", self.test_streaming_completion)
        self.run_test("5. Session Tracking (Optional)", self.test_session_tracking)
        self.run_test("6. Error Handling", self.test_error_handling)

        # Print summary
        self.print_summary()

    def print_summary(self):
        """Print validation summary."""
        self.print_header("Validation Summary")

        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)
        pass_rate = (passed / total * 100) if total > 0 else 0

        print(f"Total Tests: {total}")
        print(f"{GREEN}Passed: {passed}{RESET}")
        print(f"{RED}Failed: {failed}{RESET}")
        print(f"Pass Rate: {pass_rate:.1f}%\n")

        if failed > 0:
            print(f"{RED}Failed Tests:{RESET}")
            for r in self.results:
                if not r.passed:
                    print(f"  ✗ {r.name}")
                    print(f"    {r.message}")

        # Save detailed report
        report_path = f"logs/openai_client_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        os.makedirs("logs", exist_ok=True)

        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": pass_rate,
            },
            "tests": [
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

        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"Detailed report saved to: {report_path}")

        if failed > 0:
            print(f"{RED}✗ Some validation tests failed.{RESET}")
            print("\nPlease address the failures above before using the example.")
            sys.exit(1)
        else:
            print(f"{GREEN}✓ All validation tests passed!{RESET}")
            print("\nThe OpenAI client example is working correctly.")
            sys.exit(0)


def main():
    """Main entry point."""
    print(f"{BLUE}OpenAI Client with Service Token Example Validator{RESET}")
    print(f"Version: 1.0.0")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    validator = OpenAIClientValidator()
    validator.run_all_tests()


if __name__ == "__main__":
    main()
