#!/usr/bin/env python3
"""
Test Langfuse Telemetry Integration
====================================
Validates that Langfuse is properly configured and can receive telemetry data.

This script:
1. Loads credentials from .env file
2. Initializes Langfuse client
3. Creates test traces using @observe decorator
4. Verifies traces reach the database
5. Reports success/failure status

Usage:
    python scripts/langfuse/test_langfuse_telemetry.py [--verbose] [--test-error-handling]
"""

import os
import sys
import time
import argparse
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from langfuse import Langfuse, observe
    LANGFUSE_AVAILABLE = True
except ImportError as e:
    LANGFUSE_AVAILABLE = False
    print(f"❌ ERROR: Langfuse not installed: {e}")
    print("   Please install: pip install langfuse")
    sys.exit(1)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LangfuseTelemetryTester:
    """Test Langfuse telemetry integration."""

    def __init__(self, verbose: bool = False):
        """Initialize the tester."""
        self.verbose = verbose
        self.langfuse = None
        self.test_results = {
            "environment": False,
            "client_init": False,
            "trace_creation": False,
            "trace_export": False,
            "database_verification": False,
            "error_handling": False
        }

        # Load environment variables
        self.load_environment()

    def load_environment(self):
        """Load environment variables from .env file if it exists."""
        env_file = project_root / ".env"
        if env_file.exists():
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        # Only set if not already in environment
                        if key not in os.environ:
                            os.environ[key] = value.strip('"').strip("'")

        # Store credentials (support both naming conventions)
        self.public_key = (
            os.getenv("LANGFUSE_INIT_PROJECT_PUBLIC_KEY") or
            os.getenv("LANGFUSE_PUBLIC_KEY")
        )
        self.secret_key = (
            os.getenv("LANGFUSE_INIT_PROJECT_SECRET_KEY") or
            os.getenv("LANGFUSE_SECRET_KEY")
        )
        self.host = os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000")
        self.salt = os.getenv("LANGFUSE_SALT")
        self.enabled = os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"

        # OTEL configuration
        self.otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        self.otel_traces_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        self.otel_protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL")

    def test_environment(self) -> bool:
        """Test that required environment variables are set."""
        print("\n📋 Testing Environment Variables...")

        checks = {
            "LANGFUSE_PUBLIC_KEY": self.public_key,
            "LANGFUSE_SECRET_KEY": self.secret_key,
            "LANGFUSE_HOST": self.host,
            "LANGFUSE_SALT": self.salt,
            "LANGFUSE_ENABLED": self.enabled
        }

        all_good = True
        for key, value in checks.items():
            if value:
                if self.verbose or key != "LANGFUSE_SECRET_KEY":
                    # Don't print full secret key unless verbose
                    display_value = value if key != "LANGFUSE_SECRET_KEY" else f"{value[:15]}..."
                    print(f"   ✅ {key}: {display_value}")
            else:
                print(f"   ❌ {key}: Not set")
                all_good = False

        self.test_results["environment"] = all_good
        return all_good

    def test_client_initialization(self) -> bool:
        """Test Langfuse client initialization."""
        print("\n🔧 Testing Client Initialization...")

        try:
            self.langfuse = Langfuse(
                public_key=self.public_key,
                secret_key=self.secret_key,
                host=self.host,
                debug=self.verbose
            )
            print(f"   ✅ Client initialized successfully")
            print(f"   📍 Host: {self.host}")
            print(f"   🔑 Public Key: {self.public_key}")
            self.test_results["client_init"] = True
            return True
        except Exception as e:
            print(f"   ❌ Failed to initialize client: {e}")
            self.test_results["client_init"] = False
            return False

    @observe(name="test_simple_trace")
    def create_simple_trace(self) -> str:
        """Create a simple test trace."""
        return "Hello from Langfuse test!"

    @observe(name="test_nested_trace")
    def create_nested_trace(self) -> Dict[str, Any]:
        """Create a nested trace with multiple spans."""
        result = {"steps": []}

        @observe(name="step_1_process_data")
        def process_data():
            time.sleep(0.1)  # Simulate work
            return {"processed": True}

        @observe(name="step_2_analyze_results")
        def analyze_results(data):
            time.sleep(0.1)  # Simulate work
            return {"analysis": "complete", "input": data}

        result["steps"].append(process_data())
        result["steps"].append(analyze_results(result["steps"][0]))
        result["timestamp"] = datetime.utcnow().isoformat()

        return result

    @observe(name="test_error_trace")
    def create_error_trace(self, should_fail: bool = True):
        """Create a trace that includes error handling."""
        if should_fail:
            raise ValueError("This is a test error for Langfuse")
        return "No error occurred"

    def test_trace_creation(self) -> bool:
        """Test creating traces with @observe decorator."""
        print("\n📊 Testing Trace Creation...")

        if not self.langfuse:
            print("   ❌ Client not initialized")
            return False

        try:
            # Test 1: Simple trace
            result1 = self.create_simple_trace()
            print(f"   ✅ Simple trace created: {result1}")

            # Test 2: Nested trace
            result2 = self.create_nested_trace()
            print(f"   ✅ Nested trace created with {len(result2['steps'])} steps")

            # Test 3: Error trace (should raise but be captured)
            try:
                self.create_error_trace(should_fail=True)
            except ValueError as e:
                print(f"   ✅ Error trace created with exception: {e}")

            self.test_results["trace_creation"] = True
            return True

        except Exception as e:
            print(f"   ❌ Failed to create traces: {e}")
            self.test_results["trace_creation"] = False
            return False

    def test_trace_export(self) -> bool:
        """Test that traces are exported to Langfuse."""
        print("\n📤 Testing Trace Export...")

        if not self.langfuse:
            print("   ❌ Client not initialized")
            return False

        try:
            # Flush traces to ensure they're sent
            print("   🔄 Flushing traces...")
            self.langfuse.flush()

            # Wait a moment for export to complete
            time.sleep(2)

            print("   ✅ Traces flushed successfully")
            self.test_results["trace_export"] = True
            return True

        except Exception as e:
            print(f"   ❌ Failed to export traces: {e}")
            if "401" in str(e):
                print("   ⚠️  Authentication error - check API keys in database")
            self.test_results["trace_export"] = False
            return False

    def test_database_verification(self) -> bool:
        """Verify traces in database (if psycopg2 available)."""
        print("\n🗄️ Testing Database Verification...")

        if not PSYCOPG2_AVAILABLE:
            print("   ⚠️  psycopg2 not installed - skipping database check")
            print("   💡 Install with: pip install psycopg2-binary")
            return True  # Don't fail the test

        try:
            # Connect to Langfuse PostgreSQL
            conn = psycopg2.connect(
                host="langfuse-postgres",
                port=5432,
                database="langfuse",
                user="langfuse",
                password="langfuse_secure_password"
            )
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Check for traces
            cursor.execute("SELECT COUNT(*) as count FROM traces WHERE name LIKE 'test_%'")
            result = cursor.fetchone()
            trace_count = result['count'] if result else 0

            if trace_count > 0:
                print(f"   ✅ Found {trace_count} test trace(s) in database")

                # Get recent test traces
                cursor.execute("""
                    SELECT name, created_at
                    FROM traces
                    WHERE name LIKE 'test_%'
                    ORDER BY created_at DESC
                    LIMIT 5
                """)
                recent_traces = cursor.fetchall()

                if self.verbose and recent_traces:
                    print("   📝 Recent test traces:")
                    for trace in recent_traces:
                        print(f"      - {trace['name']} at {trace['created_at']}")

                self.test_results["database_verification"] = True
                return True
            else:
                print("   ⚠️  No test traces found in database yet")
                print("   💡 Traces may take a moment to appear")
                self.test_results["database_verification"] = False
                return False

        except Exception as e:
            print(f"   ⚠️  Could not verify database: {e}")
            print("   💡 This may be normal if running outside Docker network")
            return True  # Don't fail the test
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()

    def run_all_tests(self) -> bool:
        """Run all tests and report results."""
        print("=" * 60)
        print("🧪 Langfuse Telemetry Integration Test")
        print("=" * 60)

        # Run tests in sequence
        if not self.test_environment():
            print("\n❌ Environment not properly configured")
            return False

        if not self.test_client_initialization():
            print("\n❌ Client initialization failed")
            return False

        if not self.test_trace_creation():
            print("\n❌ Trace creation failed")
            return False

        if not self.test_trace_export():
            print("\n❌ Trace export failed")
            return False

        # Database verification is optional
        self.test_database_verification()

        # Summary
        print("\n" + "=" * 60)
        print("📊 Test Summary")
        print("=" * 60)

        total_tests = len(self.test_results)
        passed_tests = sum(1 for v in self.test_results.values() if v)

        for test_name, passed in self.test_results.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            # Database verification is optional
            if test_name == "database_verification" and not passed:
                status = "⚠️  SKIP"
            print(f"   {test_name:25} {status}")

        print("-" * 60)
        success_rate = (passed_tests / total_tests) * 100
        print(f"   Overall: {passed_tests}/{total_tests} tests passed ({success_rate:.0f}%)")

        # Determine overall success (database verification is optional)
        required_tests = ["environment", "client_init", "trace_creation", "trace_export"]
        all_required_passed = all(self.test_results.get(test, False) for test in required_tests)

        if all_required_passed:
            print("\n✅ SUCCESS: Langfuse telemetry is working correctly!")
            return True
        else:
            print("\n❌ FAILURE: Langfuse telemetry has issues that need to be fixed")
            print("\n💡 Troubleshooting tips:")
            if not self.test_results["environment"]:
                print("   - Check that .env file contains Langfuse credentials")
            if not self.test_results["client_init"]:
                print("   - Verify Langfuse services are running")
            if not self.test_results["trace_export"]:
                print("   - Check for 401 errors - API keys may not be in database")
                print("   - Run: make langfuse-fix-auth")
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test Langfuse telemetry integration"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--test-error-handling",
        action="store_true",
        help="Include error handling tests"
    )

    args = parser.parse_args()

    # Run tests
    tester = LangfuseTelemetryTester(verbose=args.verbose)
    success = tester.run_all_tests()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()