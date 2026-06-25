#!/bin/bash
# correlate_logs_traces.sh - Correlate Docker service logs with Langfuse traces
# Usage: ./scripts/correlate_logs_traces.sh <session_id> [options]

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
LANGFUSE_HOST="${LANGFUSE_HOST:-http://localhost:3000}"
CREDENTIALS_FILE=".env-keycloak-credentials-dir/.env-keycloak-credentials"

# Help message
show_help() {
    cat << EOF
Usage: $0 <session_id> [options]

Correlate Docker service logs with Langfuse traces for a given session ID.

Arguments:
  session_id          The session/thread ID to search for

Options:
  -h, --help         Show this help message
  -w, --wait SECONDS Wait N seconds before querying (default: 0)
  -l, --log-lines N  Show N lines of logs (default: 20)
  -s, --service NAME Service to check logs (default: orchestration_service)
  -v, --verbose      Show verbose output including full trace details
  -j, --json         Output traces as JSON
  --no-logs          Skip Docker logs, only show traces
  --no-traces        Skip Langfuse traces, only show logs

Examples:
  # Basic usage
  $0 integration-test-1768937967

  # Wait 15 seconds before querying (for OTEL ingestion)
  $0 integration-test-1768937967 --wait 15

  # Show 50 log lines
  $0 integration-test-1768937967 --log-lines 50

  # Check different service
  $0 integration-test-1768937967 --service agent_gateway

  # Verbose output with full trace details
  $0 integration-test-1768937967 --verbose

  # JSON output for scripting
  $0 integration-test-1768937967 --json

Documentation:
  See docs/observability/DOCKER_LOGS_AND_LANGFUSE_TRACE_CORRELATION.md

EOF
}

# Parse arguments
SESSION_ID=""
WAIT_SECONDS=0
LOG_LINES=20
SERVICE="orchestration_service"
VERBOSE=false
JSON_OUTPUT=false
SHOW_LOGS=true
SHOW_TRACES=true

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -w|--wait)
            WAIT_SECONDS="$2"
            shift 2
            ;;
        -l|--log-lines)
            LOG_LINES="$2"
            shift 2
            ;;
        -s|--service)
            SERVICE="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -j|--json)
            JSON_OUTPUT=true
            shift
            ;;
        --no-logs)
            SHOW_LOGS=false
            shift
            ;;
        --no-traces)
            SHOW_TRACES=false
            shift
            ;;
        -*)
            echo -e "${RED}Error: Unknown option $1${NC}" >&2
            show_help
            exit 1
            ;;
        *)
            if [ -z "$SESSION_ID" ]; then
                SESSION_ID="$1"
                shift
            else
                echo -e "${RED}Error: Multiple session IDs specified${NC}" >&2
                show_help
                exit 1
            fi
            ;;
    esac
done

# Validate session ID
if [ -z "$SESSION_ID" ]; then
    echo -e "${RED}Error: Session ID is required${NC}" >&2
    show_help
    exit 1
fi

# Load credentials
if [ ! -f "$CREDENTIALS_FILE" ]; then
    echo -e "${RED}Error: Credentials file not found: $CREDENTIALS_FILE${NC}" >&2
    echo "Run 'make sync-credentials' to sync credentials from deployment directory" >&2
    exit 1
fi

PUBLIC_KEY=$(grep LANGFUSE_PUBLIC_KEY "$CREDENTIALS_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d ' ')
SECRET_KEY=$(grep LANGFUSE_SECRET_KEY "$CREDENTIALS_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d ' ')

if [ -z "$PUBLIC_KEY" ] || [ -z "$SECRET_KEY" ]; then
    echo -e "${RED}Error: Could not load Langfuse credentials from $CREDENTIALS_FILE${NC}" >&2
    exit 1
fi

# Print header
if [ "$JSON_OUTPUT" = false ]; then
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Docker Logs & Langfuse Trace Correlation${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo -e "${GREEN}Session ID:${NC} $SESSION_ID"
    echo -e "${GREEN}Service:${NC} $SERVICE"
    echo -e "${GREEN}Log Lines:${NC} $LOG_LINES"
    if [ "$WAIT_SECONDS" -gt 0 ]; then
        echo -e "${GREEN}Wait Time:${NC} ${WAIT_SECONDS}s (for OTEL ingestion)"
    fi
    echo ""
fi

# Wait if requested
if [ "$WAIT_SECONDS" -gt 0 ]; then
    if [ "$JSON_OUTPUT" = false ]; then
        echo -e "${YELLOW}Waiting ${WAIT_SECONDS} seconds for OTEL ingestion...${NC}"
    fi
    sleep "$WAIT_SECONDS"
fi

# Show Docker logs
if [ "$SHOW_LOGS" = true ]; then
    if [ "$JSON_OUTPUT" = false ]; then
        echo -e "${BLUE}=== Docker Logs ($SERVICE) ===${NC}"
        echo ""
    fi

    # Check if service exists
    if ! docker ps --format '{{.Names}}' | grep -q "^${SERVICE}$"; then
        echo -e "${RED}Error: Service '$SERVICE' not found${NC}" >&2
        echo "Available services:" >&2
        docker ps --format '{{.Names}}' | grep -E "(orchestration|gateway|langfuse)" >&2
        exit 1
    fi

    # Get logs
    LOGS=$(docker logs "$SERVICE" 2>&1 | grep "$SESSION_ID" | tail -n "$LOG_LINES")

    if [ -z "$LOGS" ]; then
        if [ "$JSON_OUTPUT" = false ]; then
            echo -e "${YELLOW}No logs found for session ID: $SESSION_ID${NC}"
        fi
    else
        if [ "$JSON_OUTPUT" = false ]; then
            echo "$LOGS"
        fi

        # Extract key information
        PROPAGATED_COUNT=$(echo "$LOGS" | grep -c "Propagated.*attributes" || true)
        TRACE_IDS=$(echo "$LOGS" | grep -oP "trace_id['\"]:\s*['\"]?\K[a-f0-9]{32}" | head -3)

        if [ "$JSON_OUTPUT" = false ]; then
            echo ""
            echo -e "${GREEN}Log Summary:${NC}"
            echo -e "  Spans propagated: ${PROPAGATED_COUNT}"
            if [ -n "$TRACE_IDS" ]; then
                echo -e "  Trace IDs found:"
                echo "$TRACE_IDS" | while read -r trace_id; do
                    echo -e "    - ${trace_id}"
                done
            fi
        fi
    fi

    if [ "$JSON_OUTPUT" = false ]; then
        echo ""
    fi
fi

# Show Langfuse traces
if [ "$SHOW_TRACES" = true ]; then
    if [ "$JSON_OUTPUT" = false ]; then
        echo -e "${BLUE}=== Langfuse Traces ===${NC}"
        echo ""
    fi

    # Query Langfuse API
    RESPONSE=$(curl -s -u "$PUBLIC_KEY:$SECRET_KEY" \
        "$LANGFUSE_HOST/api/public/traces?sessionId=$SESSION_ID" 2>&1)

    # Check for errors
    if echo "$RESPONSE" | grep -q "error\|Error\|Unauthorized"; then
        if [ "$JSON_OUTPUT" = false ]; then
            echo -e "${RED}Error querying Langfuse API:${NC}"
            echo "$RESPONSE" | head -5
        else
            echo '{"error": "Failed to query Langfuse API"}'
        fi
        exit 1
    fi

    # Parse response
    TRACE_COUNT=$(echo "$RESPONSE" | jq -r '.data | length' 2>/dev/null || echo "0")

    if [ "$TRACE_COUNT" -eq 0 ]; then
        if [ "$JSON_OUTPUT" = false ]; then
            echo -e "${YELLOW}No traces found in Langfuse for session ID: $SESSION_ID${NC}"
            echo ""
            echo -e "${YELLOW}Possible reasons:${NC}"
            echo "  1. OTEL ingestion latency (wait 15-30 seconds)"
            echo "  2. Trace not created (check logs for errors)"
            echo "  3. Wrong session ID"
            echo ""
            echo "Try: $0 $SESSION_ID --wait 15"
        else
            echo '{"traces": [], "count": 0}'
        fi
    else
        if [ "$JSON_OUTPUT" = true ]; then
            echo "$RESPONSE" | jq -c '{session_id: "'$SESSION_ID'", trace_count: .data | length, traces: .data}'
        else
            echo -e "${GREEN}Found $TRACE_COUNT trace(s)${NC}"
            echo ""

            if [ "$VERBOSE" = true ]; then
                # Verbose output
                echo "$RESPONSE" | jq -C '.data[]'
            else
                # Summary output
                echo "$RESPONSE" | jq -r '.data[] |
                    "Trace ID: \(.id)",
                    "  SessionID: \(.sessionId)",
                    "  Name: \(.name)",
                    "  Timestamp: \(.timestamp)",
                    "  Model: \(.metadata.model // "N/A")",
                    "  Purpose: \(.metadata.purpose // "N/A")",
                    "  Metadata: \(.metadata | keys | join(", "))",
                    ""'
            fi
        fi
    fi

    if [ "$JSON_OUTPUT" = false ]; then
        echo ""
    fi
fi

# Show correlation summary
if [ "$JSON_OUTPUT" = false ] && [ "$SHOW_LOGS" = true ] && [ "$SHOW_TRACES" = true ]; then
    echo -e "${BLUE}=== Correlation Summary ===${NC}"
    echo ""

    if [ -n "$LOGS" ] && [ "$TRACE_COUNT" -gt 0 ]; then
        echo -e "${GREEN}✅ Correlation successful!${NC}"
        echo "  Docker logs show $PROPAGATED_COUNT span(s) propagated"
        echo "  Langfuse shows $TRACE_COUNT trace(s) indexed"

        if [ "$PROPAGATED_COUNT" -gt "$TRACE_COUNT" ]; then
            echo ""
            echo -e "${YELLOW}⚠️  Warning: More spans propagated than traces indexed${NC}"
            echo "  This may indicate OTEL ingestion lag or indexing issues"
            echo "  Try waiting longer: $0 $SESSION_ID --wait 30"
        fi
    elif [ -n "$LOGS" ] && [ "$TRACE_COUNT" -eq 0 ]; then
        echo -e "${YELLOW}⚠️  Partial correlation${NC}"
        echo "  Docker logs found ($PROPAGATED_COUNT spans)"
        echo "  Langfuse traces not found (0 traces)"
        echo ""
        echo "  Likely cause: OTEL ingestion latency (10-30 seconds)"
        echo "  Action: Wait and retry: $0 $SESSION_ID --wait 15"
    elif [ -z "$LOGS" ] && [ "$TRACE_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}⚠️  Partial correlation${NC}"
        echo "  Docker logs not found"
        echo "  Langfuse traces found ($TRACE_COUNT traces)"
        echo ""
        echo "  Possible causes:"
        echo "  1. Logs rotated/cleared"
        echo "  2. Wrong service (try: --service agent_gateway)"
        echo "  3. Session ID mismatch"
    else
        echo -e "${RED}❌ No correlation found${NC}"
        echo "  Docker logs: Not found"
        echo "  Langfuse traces: Not found"
        echo ""
        echo "  Troubleshooting:"
        echo "  1. Verify session ID is correct"
        echo "  2. Check if trace was created: docker logs $SERVICE 2>&1 | grep track_token"
        echo "  3. Check Langfuse service: docker ps | grep langfuse"
    fi

    echo ""
    echo -e "${BLUE}Documentation:${NC} docs/observability/DOCKER_LOGS_AND_LANGFUSE_TRACE_CORRELATION.md"
fi

exit 0
