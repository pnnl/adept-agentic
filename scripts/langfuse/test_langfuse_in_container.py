#!/usr/bin/env python3
"""
Lightweight Langfuse test designed to run inside containers
that already have Langfuse installed (e.g., orchestration_service).
"""

import os
import time
from datetime import datetime

def test_langfuse_trace():
    """Test Langfuse trace creation from within a container."""

    # Support both naming conventions
    public_key = (
        os.getenv("LANGFUSE_INIT_PROJECT_PUBLIC_KEY") or
        os.getenv("LANGFUSE_PUBLIC_KEY")
    )
    secret_key = (
        os.getenv("LANGFUSE_INIT_PROJECT_SECRET_KEY") or
        os.getenv("LANGFUSE_SECRET_KEY")
    )

    print("🧪 Testing Langfuse from within container...")
    print(f"📍 Host: {os.getenv('LANGFUSE_HOST', 'not set')}")
    print(f"🔑 Public Key: {public_key[:20] if public_key else 'not set'}...")
    print(f"🔧 OTEL Endpoint: {os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'not set')}")

    try:
        from langfuse import Langfuse, observe

        # Initialize client
        langfuse = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000"),
            debug=True
        )

        print("✅ Langfuse client initialized")

        # Create a test trace
        @observe(name="container_test_trace")
        def test_function():
            return f"Test from container at {datetime.utcnow().isoformat()}"

        # Execute the traced function
        result = test_function()
        print(f"✅ Test function executed: {result}")

        # Flush traces
        langfuse.flush()
        print("✅ Traces flushed to Langfuse")

        # Wait a moment for processing
        time.sleep(2)

        print("✅ Test completed successfully!")
        return 0

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(test_langfuse_trace())