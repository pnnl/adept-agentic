#!/bin/bash

# Batch test diagnostics script

TEST_FILES=(
  "tests/unit/agentic_framework_pkg/orchestration_service/test_multi_agent_manager.py"
  "tests/unit/agentic_framework_pkg/orchestration_service/test_multi_agent_tools_structured.py"
  "tests/unit/agentic_framework_pkg/orchestration_service/test_multi_agent_checkpointer_thread_ids.py"
  "tests/unit/agentic_framework_pkg/orchestration_service/test_async_postgres_saver_per_instance_engine.py"
  "tests/unit/agentic_framework_pkg/mcp_server/tools/test_alphafold_tool.py"
  "tests/unit/agentic_framework_pkg/mcp_server/tools/test_file_management_tools.py"
  "tests/unit/agentic_framework_pkg/mcp_server/tools/test_zip_processor_tool.py"
  "tests/unit/agentic_framework_pkg/core/test_document_size_validator.py"
  "tests/unit/agentic_framework_pkg/core/test_ragflow_client_chunking.py"
  "tests/unit/agentic_framework_pkg/streamlit_app_v2/test_app_helpers.py"
  "tests/unit/agentic_framework_pkg/streamlit_app_v2/test_file_upload.py"
  "tests/unit/_old_tests/test_stdio_tool_wrapper.py"
  "tests/unit/langfuse/test_headless_init_logic.py"
  "tests/unit/scripts/langfuse/test_bootstrap_langfuse_credentials.py"
)

LOG_FILE="logs/batch_diagnostic_all_errors_$(date +%Y%m%d_%H%M%S).log"

echo "Starting batch diagnostic at $(date)" > "$LOG_FILE"
echo "======================================" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

for test_file in "${TEST_FILES[@]}"; do
  echo "=== Testing: $test_file ===" | tee -a "$LOG_FILE"

  docker run --rm --user "$(id -u):$(id -g)" --network=agentic_framework_network \
    -v "$(pwd)/src":/app/src \
    -v "$(pwd)/tests":/app/tests \
    -v "$(pwd)/data":/app/data \
    -w /app \
    -e HOME=/tmp \
    -e PYTHONPATH=/app/src:/app/tests \
    agentic-framework-deps-base /app/.venv/bin/pytest "$test_file" -v --tb=short 2>&1 | head -150 >> "$LOG_FILE"

  echo "" >> "$LOG_FILE"
  echo "---" >> "$LOG_FILE"
  echo "" >> "$LOG_FILE"
done

echo "Batch diagnostic completed at $(date)" | tee -a "$LOG_FILE"
echo "Results saved to: $LOG_FILE"
