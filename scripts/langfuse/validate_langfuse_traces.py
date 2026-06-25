#!/usr/bin/env python3
"""
LangFuse Trace Validation Script

Tests the complete LangFuse trace lifecycle:
1. Create traces, spans, events, and generations via SDK
2. Read them back via REST API
3. Verify data integrity
4. Check UI accessibility

Usage:
    python scripts/langfuse/validate_langfuse_traces.py

Environment Variables:
    LANGFUSE_PUBLIC_KEY - LangFuse public key
    LANGFUSE_SECRET_KEY - LangFuse secret key
    LANGFUSE_HOST - LangFuse host URL (default: http://langfuse-web:3000)
"""

import base64
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

try:
    from langfuse import Langfuse
except ImportError:
    print("❌ Error: langfuse package not installed")
    print("   Install with: pip install langfuse")
    sys.exit(1)


class LangFuseValidator:
    """Validates LangFuse trace creation and retrieval."""

    def __init__(self):
        """Initialize validator with credentials from environment."""
        self.public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        self.secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        self.host = os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000")

        if not self.public_key or not self.secret_key:
            print("❌ Error: Missing credentials")
            print("   Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY")
            sys.exit(1)

        print(f"🔑 Using credentials:")
        print(f"   Public Key: {self.public_key}")
        print(f"   Secret Key: {self.secret_key[:15]}... (length: {len(self.secret_key)})")
        print(f"   Host: {self.host}")
        print()

        # Validate credential format
        if len(self.public_key) != 42 or len(self.secret_key) != 42:
            print("⚠️  Warning: Keys should be 42 characters (UUID v4 format)")
            print(f"   Public key length: {len(self.public_key)}")
            print(f"   Secret key length: {len(self.secret_key)}")
            print()

        if "-" not in self.public_key or "-" not in self.secret_key:
            print("⚠️  Warning: Keys should contain hyphens (UUID v4 format)")
            print()

        # Initialize SDK client
        try:
            self.client = Langfuse(
                public_key=self.public_key,
                secret_key=self.secret_key,
                host=self.host,
                debug=True,
            )
            print("✅ LangFuse SDK client initialized")
        except Exception as e:
            print(f"❌ Failed to initialize LangFuse client: {e}")
            sys.exit(1)

        # Initialize REST API session
        self.session = requests.Session()
        self.session.auth = (self.public_key, self.secret_key)
        self.session.headers.update({
            "Content-Type": "application/json",
        })

        # Track created resources for cleanup
        self.created_trace_ids: List[str] = []

    def test_health_endpoint(self) -> bool:
        """Test LangFuse health endpoint."""
        print("\n" + "=" * 80)
        print("TEST 1: Health Endpoint Check")
        print("=" * 80)

        try:
            url = f"{self.host}/api/public/health"
            print(f"📡 GET {url}")

            response = requests.get(url, timeout=10)
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.text[:200]}")

            if response.status_code == 200:
                print("✅ PASS: Health endpoint accessible")
                return True
            else:
                print(f"❌ FAIL: Health endpoint returned {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ FAIL: Health check error: {e}")
            return False

    def test_create_simple_trace(self) -> Optional[str]:
        """Create a simple trace with SDK."""
        print("\n" + "=" * 80)
        print("TEST 2: Create Simple Trace")
        print("=" * 80)

        try:
            trace_name = f"validation_test_{datetime.utcnow().isoformat()}"
            print(f"📝 Creating trace: {trace_name}")

            # Create trace using SDK
            trace = self.client.trace(
                name=trace_name,
                metadata={
                    "test_type": "validation",
                    "timestamp": datetime.utcnow().isoformat(),
                    "purpose": "verify_trace_creation",
                },
                tags=["validation", "test"],
            )

            print(f"   Trace ID: {trace.id}")
            self.created_trace_ids.append(trace.id)

            # Flush to ensure trace is sent
            print("   Flushing SDK...")
            self.client.flush()
            print("   Flush completed")

            # Wait for trace to be processed
            time.sleep(2)

            print("✅ PASS: Trace created successfully")
            return trace.id

        except Exception as e:
            print(f"❌ FAIL: Failed to create trace: {e}")
            import traceback
            traceback.print_exc()
            return None

    def test_retrieve_trace(self, trace_id: str) -> bool:
        """Retrieve trace via REST API."""
        print("\n" + "=" * 80)
        print("TEST 3: Retrieve Trace via REST API")
        print("=" * 80)

        try:
            url = f"{self.host}/api/public/traces/{trace_id}"
            print(f"📡 GET {url}")
            print(f"   Auth: Basic {self.public_key}:***")

            response = self.session.get(url, timeout=10)
            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                trace_data = response.json()
                print(f"   Response: {json.dumps(trace_data, indent=2)[:500]}...")
                print("✅ PASS: Trace retrieved successfully")
                return True
            elif response.status_code == 404:
                print(f"❌ FAIL: Trace not found (404)")
                print(f"   Response: {response.text}")
                return False
            elif response.status_code == 401:
                print(f"❌ FAIL: Authentication failed (401)")
                print(f"   Response: {response.text}")
                return False
            else:
                print(f"❌ FAIL: Unexpected status {response.status_code}")
                print(f"   Response: {response.text}")
                return False

        except Exception as e:
            print(f"❌ FAIL: Failed to retrieve trace: {e}")
            import traceback
            traceback.print_exc()
            return False

    def test_list_traces(self) -> bool:
        """List traces via REST API."""
        print("\n" + "=" * 80)
        print("TEST 4: List Traces via REST API")
        print("=" * 80)

        try:
            url = f"{self.host}/api/public/traces"
            print(f"📡 GET {url}?page=1&limit=10")

            response = self.session.get(
                url,
                params={"page": 1, "limit": 10},
                timeout=10
            )
            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                traces_data = response.json()
                print(f"   Total traces: {len(traces_data.get('data', []))}")

                if traces_data.get('data'):
                    print(f"   First trace ID: {traces_data['data'][0].get('id')}")
                    print(f"   First trace name: {traces_data['data'][0].get('name')}")

                print("✅ PASS: Traces listed successfully")
                return True
            else:
                print(f"❌ FAIL: Failed to list traces (status {response.status_code})")
                print(f"   Response: {response.text}")
                return False

        except Exception as e:
            print(f"❌ FAIL: Failed to list traces: {e}")
            import traceback
            traceback.print_exc()
            return False

    def test_create_trace_with_span(self) -> Optional[str]:
        """Create trace with nested span."""
        print("\n" + "=" * 80)
        print("TEST 5: Create Trace with Span")
        print("=" * 80)

        try:
            trace_name = f"validation_with_span_{datetime.utcnow().isoformat()}"
            print(f"📝 Creating trace with span: {trace_name}")

            # Create trace
            trace = self.client.trace(
                name=trace_name,
                metadata={"test_type": "span_validation"},
            )
            print(f"   Trace ID: {trace.id}")
            self.created_trace_ids.append(trace.id)

            # Create span within trace
            span = trace.span(
                name="test_span",
                metadata={
                    "operation": "validation_test",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                input={"test_input": "sample data"},
                output={"test_output": "sample result"},
            )
            print(f"   Span ID: {span.id}")

            # End span
            span.end()
            print("   Span ended")

            # Flush
            self.client.flush()
            time.sleep(2)

            print("✅ PASS: Trace with span created successfully")
            return trace.id

        except Exception as e:
            print(f"❌ FAIL: Failed to create trace with span: {e}")
            import traceback
            traceback.print_exc()
            return None

    def test_create_trace_with_generation(self) -> Optional[str]:
        """Create trace with generation."""
        print("\n" + "=" * 80)
        print("TEST 6: Create Trace with Generation")
        print("=" * 80)

        try:
            trace_name = f"validation_with_generation_{datetime.utcnow().isoformat()}"
            print(f"📝 Creating trace with generation: {trace_name}")

            # Create trace
            trace = self.client.trace(
                name=trace_name,
                metadata={"test_type": "generation_validation"},
            )
            print(f"   Trace ID: {trace.id}")
            self.created_trace_ids.append(trace.id)

            # Create generation within trace
            generation = trace.generation(
                name="test_generation",
                model="gpt-4",
                input=[{"role": "user", "content": "Test prompt"}],
                output="Test completion response",
                metadata={
                    "temperature": 0.7,
                    "max_tokens": 100,
                },
                usage={
                    "input": 10,
                    "output": 20,
                    "total": 30,
                },
            )
            print(f"   Generation ID: {generation.id}")

            # End generation
            generation.end()
            print("   Generation ended")

            # Flush
            self.client.flush()
            time.sleep(2)

            print("✅ PASS: Trace with generation created successfully")
            return trace.id

        except Exception as e:
            print(f"❌ FAIL: Failed to create trace with generation: {e}")
            import traceback
            traceback.print_exc()
            return None

    def test_create_trace_with_event(self) -> Optional[str]:
        """Create trace with event."""
        print("\n" + "=" * 80)
        print("TEST 7: Create Trace with Event")
        print("=" * 80)

        try:
            trace_name = f"validation_with_event_{datetime.utcnow().isoformat()}"
            print(f"📝 Creating trace with event: {trace_name}")

            # Create trace
            trace = self.client.trace(
                name=trace_name,
                metadata={"test_type": "event_validation"},
            )
            print(f"   Trace ID: {trace.id}")
            self.created_trace_ids.append(trace.id)

            # Create event within trace
            event = trace.event(
                name="test_event",
                metadata={
                    "event_type": "validation",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                input={"event_data": "sample input"},
                output={"event_result": "sample output"},
            )
            print(f"   Event ID: {event.id}")

            # Flush
            self.client.flush()
            time.sleep(2)

            print("✅ PASS: Trace with event created successfully")
            return trace.id

        except Exception as e:
            print(f"❌ FAIL: Failed to create trace with event: {e}")
            import traceback
            traceback.print_exc()
            return None

    def test_database_verification(self) -> bool:
        """Verify traces exist in database."""
        print("\n" + "=" * 80)
        print("TEST 8: Database Verification")
        print("=" * 80)

        if not self.created_trace_ids:
            print("⚠️  SKIP: No traces created to verify")
            return True

        try:
            # Query via API to check if traces exist
            url = f"{self.host}/api/public/traces"
            print(f"📡 GET {url}?page=1&limit=50")

            response = self.session.get(
                url,
                params={"page": 1, "limit": 50},
                timeout=10
            )

            if response.status_code != 200:
                print(f"❌ FAIL: Failed to query traces (status {response.status_code})")
                return False

            traces_data = response.json()
            all_trace_ids = [t["id"] for t in traces_data.get("data", [])]

            print(f"   Total traces in system: {len(all_trace_ids)}")
            print(f"   Created trace IDs: {self.created_trace_ids}")

            found_count = 0
            for trace_id in self.created_trace_ids:
                if trace_id in all_trace_ids:
                    print(f"   ✅ Found trace: {trace_id}")
                    found_count += 1
                else:
                    print(f"   ❌ Missing trace: {trace_id}")

            if found_count == len(self.created_trace_ids):
                print(f"✅ PASS: All {found_count} traces found in database")
                return True
            else:
                print(f"❌ FAIL: Only {found_count}/{len(self.created_trace_ids)} traces found")
                return False

        except Exception as e:
            print(f"❌ FAIL: Database verification error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def test_ui_accessibility(self) -> bool:
        """Test if LangFuse UI is accessible."""
        print("\n" + "=" * 80)
        print("TEST 9: UI Accessibility Check")
        print("=" * 80)

        try:
            ui_url = self.host.replace(":3000", ":3001")  # External port
            print(f"📡 GET {ui_url}")

            response = requests.get(ui_url, timeout=10)
            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                print(f"✅ PASS: UI is accessible at {ui_url}")
                if self.created_trace_ids:
                    trace_url = f"{ui_url}/traces/{self.created_trace_ids[0]}"
                    print(f"\n🔗 View traces in UI:")
                    for trace_id in self.created_trace_ids[:3]:
                        print(f"   {ui_url.replace('langfuse-web:3000', 'localhost:3001')}/traces/{trace_id}")
                return True
            else:
                print(f"⚠️  WARNING: UI returned status {response.status_code}")
                return False

        except Exception as e:
            print(f"⚠️  WARNING: Could not reach UI: {e}")
            print(f"   (This is expected if running inside container)")
            return False

    def run_all_tests(self) -> Dict[str, bool]:
        """Run all validation tests."""
        results = {}

        print("=" * 80)
        print("LangFuse Trace Validation Suite")
        print("=" * 80)
        print(f"Timestamp: {datetime.utcnow().isoformat()}")
        print()

        # Test 1: Health endpoint
        results["health"] = self.test_health_endpoint()

        # Test 2: Create simple trace
        trace_id_simple = self.test_create_simple_trace()
        results["create_trace"] = trace_id_simple is not None

        # Test 3: Retrieve trace
        if trace_id_simple:
            results["retrieve_trace"] = self.test_retrieve_trace(trace_id_simple)
        else:
            results["retrieve_trace"] = False
            print("\n⚠️  SKIP: Test 3 (Retrieve Trace) - No trace ID from Test 2")

        # Test 4: List traces
        results["list_traces"] = self.test_list_traces()

        # Test 5: Trace with span
        trace_id_span = self.test_create_trace_with_span()
        results["create_span"] = trace_id_span is not None

        # Test 6: Trace with generation
        trace_id_gen = self.test_create_trace_with_generation()
        results["create_generation"] = trace_id_gen is not None

        # Test 7: Trace with event
        trace_id_event = self.test_create_trace_with_event()
        results["create_event"] = trace_id_event is not None

        # Test 8: Database verification
        results["database_verification"] = self.test_database_verification()

        # Test 9: UI accessibility
        results["ui_accessibility"] = self.test_ui_accessibility()

        return results

    def print_summary(self, results: Dict[str, bool]):
        """Print test summary."""
        print("\n" + "=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)

        passed = sum(1 for v in results.values() if v)
        total = len(results)

        for test_name, result in results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status}: {test_name}")

        print()
        print(f"Total: {passed}/{total} tests passed")

        if passed == total:
            print("\n🎉 ALL TESTS PASSED!")
            print("\nLangFuse is working correctly:")
            print("  ✅ Traces can be created via SDK")
            print("  ✅ Traces can be retrieved via REST API")
            print("  ✅ Traces are stored in database")
            print("  ✅ Credentials are working")
            return 0
        else:
            print(f"\n⚠️  {total - passed} TEST(S) FAILED")
            print("\nPossible issues:")
            if not results.get("health"):
                print("  ❌ LangFuse service not accessible")
            if not results.get("create_trace"):
                print("  ❌ Cannot create traces (SDK or credentials issue)")
            if not results.get("retrieve_trace"):
                print("  ❌ Cannot retrieve traces (API or database issue)")
            if not results.get("database_verification"):
                print("  ❌ Traces not persisting to database")
            return 1


def main():
    """Main entry point."""
    validator = LangFuseValidator()
    results = validator.run_all_tests()
    exit_code = validator.print_summary(results)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
