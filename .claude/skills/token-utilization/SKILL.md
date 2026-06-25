# Token Utilization Analysis

You are assisting an ADEPT developer with querying, aggregating, and analyzing LLM token consumption from observability backends. This skill produces cost reports that classify DAST/red-team probe traffic vs regular agent usage.

Do not use emojis in any output.

## Prerequisites

The token utilization module lives at `examples/adept_asopb/src/asopb/observability/`. It requires:

1. A running Langfuse instance (default: `http://localhost:3001`) OR cloud provider credentials
2. Environment variables for the chosen backend (see Backend Configuration below)
3. Python 3.11+ with `langfuse` package installed

## Step 1: Detect Backend

Auto-detect available backends from environment:

```bash
# Check Langfuse (primary)
echo "LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY:-(not set)}"
echo "LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY:-(not set)}"
echo "LANGFUSE_HOST=${LANGFUSE_HOST:-http://localhost:3001}"

# Check AWS
echo "AWS_REGION_NAME=${AWS_REGION_NAME:-(not set)}"

# Check Azure
echo "AZURE_WORKSPACE_ID=${AZURE_WORKSPACE_ID:-(not set)}"

# Check GCP
echo "GCP_PROJECT_ID=${GCP_PROJECT_ID:-(not set)}"
```

If Langfuse keys are present, use Langfuse. Otherwise ask the developer which backend to use.

## Step 2: Run Aggregation

### Option A: Direct Python (fastest, no CLI dependency)

```python
import sys
sys.path.insert(0, "examples/adept_asopb/src")

from asopb.observability.factory import BackendFactory
from asopb.observability.aggregator import TokenUtilizationAggregator
from asopb.observability.models import AggregationFilters
from asopb.observability.persistence import TokenUtilizationStore

# Configure backend
config = {
    "endpoint": "<LANGFUSE_HOST or http://localhost:3001>",
    "public_key": "<LANGFUSE_PUBLIC_KEY>",
    "secret_key": "<LANGFUSE_SECRET_KEY>",
}

backend = BackendFactory.create("langfuse", config)
aggregator = TokenUtilizationAggregator(backend)

# Aggregate with optional filters
filters = AggregationFilters(
    from_date="2026-05-01",      # ISO date string or None for all
    to_date=None,                 # ISO date string or None
    model=None,                   # Model name substring filter
    dast_fingerprint_threshold=15000,  # Input tokens >= this = DAST probe
)

report = aggregator.aggregate(filters=filters, cost_model="azure-o4-mini")

# Print summary
report.print_summary()

# Persist for trend analysis
store = TokenUtilizationStore()
run_id = store.save_report(report)
print(f"\nPersisted as: {run_id}")
```

### Option B: CLI (if installed)

```bash
cd examples/adept_asopb && pip install -e ".[observability]"

# Run aggregation
asopb token-usage aggregate \
  --backend langfuse \
  --endpoint http://localhost:3001 \
  --public-key "$LANGFUSE_PUBLIC_KEY" \
  --secret-key "$LANGFUSE_SECRET_KEY" \
  --from-date 2026-05-01 \
  --cost-model azure-o4-mini \
  --format text

# View trends
asopb token-usage trends --last 10

# List backends
asopb token-usage backends
```

## Step 3: Interpret Results

The report classifies generations into two buckets:

| Category | Fingerprint | What It Means |
|----------|-------------|---------------|
| DAST Probes | input_tokens >= 15,000 | Promptfoo red-team scans (system prompt + adversarial payload) |
| Regular | input_tokens < 15,000 | Normal agent interactions, tool calls, user queries |

Key metrics to report:
- **Total generations**: How many LLM calls in the time window
- **DAST probe count**: How many were red-team scans
- **DAST cost**: Dollar cost of security scanning
- **Regular cost**: Dollar cost of normal operations
- **Total cost**: Combined spend
- **By-model breakdown**: Which models consumed the most
- **By-date breakdown**: Daily spend pattern

## Step 4: Persist and Trend

Every aggregation run is persisted to SQLite (`~/.asopb/token_utilization.db` or `$ASOPB_TOKEN_DB`).

```python
# Query historical trends
store = TokenUtilizationStore()
trends = store.get_trends(last_n=10)

for t in trends:
    print(f"{t['generated_at'][:10]} | {t['backend']} | "
          f"DAST: ${t['dast_total_cost']:.4f} | "
          f"Regular: ${t['regular_total_cost']:.4f} | "
          f"Total: ${t['total_cost']:.4f}")
```

## Step 5: Export Report

```python
# JSON (machine-readable)
json_output = report.to_json()
from pathlib import Path
Path("logs/token_utilization_report.json").write_text(json_output)

# Text (human-readable)
text_output = report.format_text()
Path(f"logs/token_utilization_report_{report.generated_at.strftime('%Y%m%d')}.txt").write_text(text_output)
```

## Backend Configuration

### Langfuse (Recommended)

| Variable | Purpose | Default |
|----------|---------|---------|
| `LANGFUSE_PUBLIC_KEY` | API public key | (required) |
| `LANGFUSE_SECRET_KEY` | API secret key | (required) |
| `LANGFUSE_HOST` | Langfuse endpoint URL | `http://localhost:3001` |

### AWS CloudWatch (Stub)

| Variable | Purpose | Default |
|----------|---------|---------|
| `AWS_REGION_NAME` | AWS region | (required) |
| `AWS_LOG_GROUP` | CloudWatch log group for Bedrock | (required) |
| `AWS_ACCESS_KEY_ID` | AWS credentials | From profile |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials | From profile |

### Azure Monitor (Stub)

| Variable | Purpose | Default |
|----------|---------|---------|
| `AZURE_WORKSPACE_ID` | Log Analytics workspace ID | (required) |

### GCP Cloud Logging (Stub)

| Variable | Purpose | Default |
|----------|---------|---------|
| `GCP_PROJECT_ID` | GCP project ID | (required) |

## Cost Models

Available built-in pricing models:

| Name | Input ($/1M tokens) | Output ($/1M tokens) | Use Case |
|------|---------------------|----------------------|----------|
| `azure-o4-mini` | $1.10 | $4.40 | Azure OpenAI o4-mini |
| `azure-gpt-4o` | $2.50 | $10.00 | Azure GPT-4o |
| `bedrock-claude-sonnet-4` | $3.00 | $15.00 | AWS Bedrock Claude Sonnet |
| `bedrock-claude-opus` | $15.00 | $75.00 | AWS Bedrock Claude Opus |
| `bedrock-claude-haiku` | $0.25 | $1.25 | AWS Bedrock Claude Haiku |

## DAST Fingerprinting Rationale

Promptfoo red-team probes inject a large system prompt (~10-15K tokens) alongside adversarial payloads. The default threshold of 15,000 input tokens reliably separates these from regular agent calls (typically 500-5,000 input tokens).

Adjust the threshold if:
- Your system prompts are unusually large (raise threshold)
- Your DAST tool uses smaller payloads (lower threshold)
- You want to include RAG-augmented calls in the regular bucket (raise threshold)

## Example Output

```
=== Token Utilization Report ===
Generated: 2026-05-28 14:30:00
Backend: Langfuse (http://localhost:3001)
Cost Model: azure-o4-mini

--- Summary ---
Total Generations: 1,096
  DAST Probes: 992 (90.5%)
  Regular Calls: 104 (9.5%)

--- Token Usage ---
DAST:    Input: 18,432,100 | Output: 1,205,300 | Total: 19,637,400
Regular: Input: 312,500    | Output: 89,200    | Total: 401,700

--- Cost Breakdown ---
DAST Cost:    $25.58 (Input: $20.28 + Output: $5.30)
Regular Cost: $0.74 (Input: $0.34 + Output: $0.39)
Total Cost:   $26.32

--- By Model ---
o4-mini:       980 calls | $24.10
gpt-4o:         72 calls | $1.85
claude-sonnet:  44 calls | $0.37
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ConnectionError: Cannot reach Langfuse` | Verify `LANGFUSE_HOST` and that Docker is running (`docker ps \| grep langfuse`) |
| `401 Unauthorized` | Check `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are correct |
| `0 generations found` | Expand date range or remove model filter; check Langfuse UI has data |
| `All classified as DAST` | Lower `--dast-threshold` (your probes may use fewer tokens) |
| `None classified as DAST` | Raise threshold or verify promptfoo scans actually ran in the time window |

## Related Documentation

- Implementation plan: `docs/implementation-plans/TOKEN_UTILIZATION_AGGREGATION_MODULE.md`
- Module source: `examples/adept_asopb/src/asopb/observability/`
- Test suite: `examples/adept_asopb/tests/observability/`
- GitHub issue: #105
