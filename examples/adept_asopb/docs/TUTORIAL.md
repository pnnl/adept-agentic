# ASOPB Tutorial: Agentic Security & Operations Performance Benchmark

This tutorial provides a comprehensive guide to the ASOPB framework, the release scanning pipeline, and the associated Claude Code skills for security evaluation of agentic AI systems.

---

## Table of Contents

1. [What is ASOPB?](#what-is-asopb)
2. [The 8-Domain Security Model](#the-8-domain-security-model)
3. [Evidence Tiers (T1, T2, T3)](#evidence-tiers)
4. [ASPI Scoring](#aspi-scoring)
5. [The Scan Pipeline](#the-scan-pipeline)
6. [Running Scans Locally](#running-scans-locally)
7. [Gate Checks and Release Decisions](#gate-checks-and-release-decisions)
8. [Triaging Findings](#triaging-findings)
9. [CI Integration](#ci-integration)
10. [Token Utilization and Cost Analysis](#token-utilization-and-cost-analysis)
11. [Claude Code Skills Reference](#claude-code-skills-reference)
12. [Using ASOPB for Generic Codebases](#using-asopb-for-generic-codebases)

---

## What is ASOPB?

ASOPB (Agentic Security & Operations Performance Benchmark) is a security evaluation framework purpose-built for AI agent systems. It addresses a gap in traditional security benchmarks: existing tools (SAST, SCA, DAST) measure individual attack surfaces, but agentic systems introduce novel risks around tool use, multi-agent coordination, identity delegation, and model integrity that span multiple DevSecOps categories simultaneously.

ASOPB provides:

- An **8-domain security model** (D1-D8) covering the full attack surface of agentic platforms
- A **three-tier evidence rubric** (T1 Design, T2 Implementation, T3 Adversarial) for graduated assurance
- The **ASPI score** (Agentic Security Posture Index, 0-100) as a single composite metric
- A **stage classification** (S1 Minimal through S4 Hardened) for maturity signaling
- Integration with standard DevSecOps tooling (Grype, TruffleHog, Promptfoo, Semgrep)

The framework is distributed as a Python package (`asopb`) and a Docker-based scanner image that bundles all scanning tools and ML models for air-gapped execution.

---

## The 8-Domain Security Model

ASOPB evaluates systems across eight security domains, each addressing a distinct attack surface of agentic AI platforms:

| Domain | Name | Weight | Scope |
|--------|------|--------|-------|
| D1 | Foundation Model Integrity | 1.5 | Model provenance, version pinning, output sanitization, injection resistance |
| D2 | Orchestration Security | 1.0 | State isolation, input validation, instruction integrity, multi-agent scoping |
| D3 | Tool and MCP Security | 1.2 | Tool registration, ACL enforcement, sandbox isolation, schema enforcement |
| D4 | Identity and Authentication | 1.3 | Agent identity attestation, token lifecycle, JWKS/JWT federation, RBAC |
| D5 | Federation and Trust | 1.2 | A2A mesh, IdP federation, token exchange, data sovereignty |
| D6 | Observability and Audit | 1.0 | Structured logging, trace collection, audit trail, cost tracking |
| D7 | IT/OT Convergence | 1.5 | HPC security, instrument data, network segmentation, OT bridge security |
| D8 | Ecosystem and Supply Chain | 1.2 | Dependency pinning, hash verification, container security, SBOM, CI/CD |

Each domain contains 6 controls (44 total across the framework). Controls are evaluated independently and scored on the three-tier evidence scale.

### Domain Weights

Weights reflect relative risk severity. D1 (Foundation Model Integrity) and D7 (IT/OT Convergence) carry weight 1.5 because compromise in these domains has cascading impact across the entire system. The weights are configurable via profiles for different deployment contexts.

---

## Evidence Tiers

ASOPB uses a three-tier evidence rubric inspired by NIST RMF and STIG validation levels:

| Tier | Name | Method | What It Proves |
|------|------|--------|---------------|
| T1 | Design | Deterministic pattern scanning | "Architecture patterns exist in code" |
| T2 | Implementation | LLM-graded evidence assessment | "Patterns are correctly implemented" |
| T3 | Adversarial | Red-team probing (Promptfoo) | "System resists attacks" |

**T1 (Design)** uses regex scanners, file presence checks, and structural analysis to detect whether security controls exist at all. A codebase with JWT validation imports, Keycloak configuration, and RBAC decorators has T1 evidence for D4.

**T2 (Implementation)** uses LLM-as-judge to assess whether the detected patterns represent correct, complete implementations. An LLM grades source files against evaluation criteria defined in domain skill prompts. This tier requires API access to an LLM provider.

**T3 (Adversarial)** ingests results from Promptfoo red-team probing against a live endpoint. A system that resists prompt injection, maintains authorization boundaries under adversarial pressure, and refuses harmful content has T3 evidence.

The composite domain score combines all three tiers. T1 provides the baseline, T2 validates implementation quality, and T3 proves operational resilience.

---

## ASPI Scoring

The Agentic Security Posture Index (ASPI) is the top-level composite metric. There are two scoring modes:

### Pipeline ASPI (Release Gate)

Used by the scan pipeline (`scan_pipeline.py`) for release decisions. This is a **penalty-based** model:

```
Per domain:  domain_score = max(0, 100 - SUM(weight_i * ln(1 + count_i)))
Composite:   ASPI = D5 * 0.4 + D8 * 0.4 + D7 * 0.2
```

The Pipeline ASPI evaluates three domains (D5, D7, D8) based on negative findings from the scan pipeline. Penalty weights by finding type:

| Domain | Finding Type | Penalty Weight | Rationale |
|--------|-------------|---------------|-----------|
| D5 | Verified credentials | 40 | Confirmed live secrets -- catastrophic |
| D5 | Internal infrastructure | 15 | Hostnames/IPs not meant to be public |
| D5 | Real PII | 8 | High-confidence person names, emails |
| D5 | Unverified credentials | 1.5 | Pattern match, high FP rate |
| D8 | Verified secrets (TruffleHog) | 40 | API-verified -- catastrophic |
| D8 | Unverified secrets | 2.5 | Pattern match, moderate FP rate |
| D7 | Toxicity | 8 | Content safety findings |

The logarithmic scaling ensures that one verified secret is devastating (ln(2) * 40 = 27.7 point penalty) but 100 pattern-match false positives are manageable (ln(101) * 1.5 = 6.9 points).

### Full ASPI (8-Domain Evaluation)

Used by the evaluator (`asopb evaluate`) for comprehensive assessment:

```
ASPI = SUM(weight_i * domain_score_i) / SUM(weight_i)
```

Where each domain score is a composite of T1, T2, and T3 control scores. This mode requires LLM access for T2 grading.

### Stage Classification

| Stage | ASPI Range | Meaning |
|-------|-----------|---------|
| S4 (Hardened) | >= 90 | Release-ready, verified security controls |
| S3 (Monitored) | 70-89 | Acceptable with monitoring, some gaps |
| S2 (Managed) | 50-69 | Basic controls present, significant gaps |
| S1 (Minimal) | < 50 | Insufficient security posture |

The release gate threshold is **ASPI >= 95** for public release (Pipeline ASPI mode).

---

## The Scan Pipeline

The scan pipeline (`scripts/release/scan_pipeline.py`) orchestrates multiple scanning passes in parallel groups, applying false-positive filtering and producing an ASPI score.

### Pipeline Passes

| Pass | Tool | Speed | What It Detects |
|------|------|-------|-----------------|
| 0 (regex) | Custom regex patterns | ~1ms/file | Credentials, internal infra, sensitive keywords |
| 1 (secrets) | detect-secrets | ~1ms/file | API keys, passwords, tokens via entropy and plugins |
| 1.5 (trufflehog) | TruffleHog v3 | ~10ms/file | Deep secrets with 882 detectors, API verification |
| 2 (ner_pii) | BERT NER + DeBERTa PII | ~100ms/chunk | Person names, emails, passwords, IBANs (54 entity types) |
| 3 (toxicity) | Detoxify (toxic-bert) | ~50ms/chunk | Harmful content, profanity, threats |
| 4 (grype) | Anchore Grype | ~30s total | CVE/vulnerability scanning against dependency manifests |
| 4L (trivy) | Aquasecurity Trivy | ~30s total | Legacy CVE scanner (backward compatibility) |
| 5 (promptfoo) | Promptfoo | varies | LLM red-team adversarial probing (requires live endpoint) |

Additional passes: `vulture` (dead code), `dockerfile_deps` (Dockerfile dependency extraction + Grype scan), `egress` (network egress pattern detection).

### Execution Groups

Passes are organized into groups that execute in sequence, with parallelism within each group:

1. **fast** (parallel): regex, secrets
2. **io_bound** (parallel): trufflehog, grype, dockerfile_deps, vulture, egress
3. **ml** (sequential, due to GPU/RAM sharing): ner_pii, toxicity
4. **dynamic** (requires network): promptfoo

### Pass Group Presets

| Preset | Passes Included | Duration | Use Case |
|--------|----------------|----------|----------|
| `lightweight` | regex, secrets | ~2s | Fast credential check |
| `enhanced` | regex, secrets, trufflehog, grype, dockerfile_deps, vulture, egress | ~5-10s | Security posture without ML |
| `all` | All static passes (no promptfoo) | 30-75 min | Full pre-release coverage |
| `redteam` | promptfoo only | varies | LLM adversarial probing |

### False Positive Suppression Stack

The pipeline applies a four-layer FP suppression stack (evaluated in order):

1. **Layer 1 (fp_patterns.py)**: Inline heuristic rules (attribution contexts, reserved domains, DevOps vocabulary)
2. **Layer 2 (.asopb-allowlist.yaml)**: Declarative YAML rules for category-level suppression
3. **Layer 3 (.grype.yaml)**: Grype-native ignore rules for CVE suppressions
4. **Layer 4 (compensating_controls.py)**: Fingerprint-validated suppressions with file hash verification

---

## Running Scans Locally

### Prerequisites

- Docker installed with the `adept-release-scanner:latest` image built
- At least 8GB RAM available for ML passes (4GB minimum for non-ML)
- The repository checked out at the version to scan

### Build the Scanner Image

```bash
cd scripts/release && make docker-build
```

This builds a Docker image (~3.4GB) containing all scanner tools, ML models, and the ASOPB library.

### Scan the Staged Release Tree

The standard release workflow stages files through `.publish-exclude`, then scans the result:

```bash
# Step 1: Stage the release tree (applies .publish-exclude filter)
cd scripts/release && make stage

# Step 2: Run the full scan
make docker-scan-staged

# Step 3: Check the gate
SCAN_DIR=$(ls -td ../../logs/scan-staged-* | head -1)
python3 gate_check.py "$SCAN_DIR" --verbose
```

### Scan an Arbitrary Directory

For scanning any directory (not just the staged release):

```bash
# From project root:
make -C scripts/release scan-path SCAN_TARGET=examples/biofoundation_mcp_server

# Or with custom passes and gate:
make -C scripts/release scan-path SCAN_TARGET=/path/to/repo PASSES=enhanced GATE=70
```

### Scan with Specific Passes

```bash
# Lightweight (regex + secrets only, no Docker needed)
python3 scripts/release/scan_pipeline.py /path/to/tree --passes lightweight

# Enhanced (no ML models)
python3 scripts/release/scan_pipeline.py /path/to/tree --passes enhanced

# Full pipeline in container
docker run --rm --shm-size=4g --memory=8g \
  -v /path/to/tree:/scan:ro \
  -v $(pwd)/logs/scan-output:/output \
  adept-release-scanner:latest \
  /scan --passes all --format json --output-dir /output
```

### Scan with Allowlist Suppression

```bash
python3 scripts/release/scan_pipeline.py /path/to/tree \
  --passes all \
  --allowlist scripts/release/.asopb-allowlist.yaml \
  --format json
```

---

## Gate Checks and Release Decisions

The gate check script (`gate_check.py`) provides a binary PASS/FAIL decision:

```bash
# Default gate (ASPI >= 90)
python3 scripts/release/gate_check.py logs/scan-staged-20260511-1418

# Custom threshold
python3 scripts/release/gate_check.py logs/scan-staged-20260511-1418 --gate 95

# JSON output for CI
python3 scripts/release/gate_check.py logs/scan-staged-20260511-1418 --json

# Verbose domain breakdown
python3 scripts/release/gate_check.py logs/scan-staged-20260511-1418 --verbose
```

Exit codes:
- 0: PASS (ASPI >= gate threshold)
- 1: FAIL (ASPI < gate threshold)
- 2: Error (no scan data found)

### Analysis on Failure

When the gate fails, use the analysis tools to understand what needs fixing:

```bash
# Full FP analysis with simulated scoring
python3 scripts/release/analyze_findings.py "$SCAN_DIR" --simulate

# Only actionable findings (after all FP suppression)
python3 scripts/release/analyze_findings.py "$SCAN_DIR" --actionable-only
```

---

## Triaging Findings

### CVE Findings (D8)

CVE findings from Grype/Trivy are triaged by reachability:

1. **Check if the package is a direct or transitive dependency** -- transitive-only packages often have no reachable code path
2. **Search for usage of the vulnerable API** -- if the vulnerable function/class is never called, the CVE is not exploitable
3. **Classify exposure tier** -- a package only in Tier 3 (MCP servers, `--network=none`) has minimal attack surface

Remediation options:
- **Upgrade**: `uv lock --upgrade-package <pkg>` if a fix version exists
- **Suppress with justification**: Add to `.grype.yaml` with compensating control documentation
- **Accept risk**: Document in compensating controls registry if no fix available

### Credential Findings (D5/D8)

For secrets detected by regex, detect-secrets, or TruffleHog:

1. **Verified secrets** (TruffleHog): Immediate rotation required. These are confirmed live credentials.
2. **Unverified pattern matches**: Check if the "secret" is a placeholder, documentation example, or Helm template variable.
3. **File not in release**: If the file is excluded by `.publish-exclude`, findings are informational only.

### Adding Allowlist Rules

For confirmed false positives that recur across scans, add a suppression rule:

```yaml
# .asopb-allowlist.yaml
rules:
  - category: secrets
    type: detect-secrets
    file_patterns:
      - "docs/examples/*"
    pattern: "example-api-key-.*"
    reason: "Documentation placeholder values"
```

### Adding Compensating Controls

For CVEs that cannot be upgraded but have limited exposure:

```yaml
# .grype.yaml
ignore:
  # CVE-2026-12345 | HIGH | urllib3 2.0.3 | HTTP redirect loop DoS
  #
  # Compensating Control:
  #   urllib3 is only used in the scanner container which runs with
  #   --network=none (air-gapped). No inbound traffic vector exists.
  #
  # Evidence:
  #   grep -rn "import urllib3" scripts/release/ -> 1 hit (scanner only)
  #
  # Risk Acceptance:
  #   Accepted by: Paul Rigor (Lead), 2026-05-28
  #   Re-evaluate if: urllib3 is added to src/ or production services
  #
  - vulnerability: CVE-2026-12345
    package:
      name: urllib3
```

---

## CI Integration

ASOPB integrates with GitHub Actions through `.github/workflows/asopb-pre-release-scan.yml`:

### CI Phases

| Phase | Passes | Blocking? | Cost |
|-------|--------|-----------|------|
| Phase 1 (SAST) | regex only | YES (PR gate) | Free, deterministic |
| Phase 2 (ML+SCA) | ner_pii, toxicity, grype | Advisory (Critical CVEs block) | Free, container-based |
| Phase 2 (DAST) | promptfoo red-team | Advisory | ~$0.50-2.00/run |

### How CI Uses ASPI

- Phase 1 runs on every PR push (fast, regex-only, deterministic)
- Phase 2 runs in parallel advisory jobs (non-blocking except Critical CVEs)
- The publish workflow has an ASPI gate job that must pass before public release
- ASPI history is stored as GitHub artifacts (365-day retention) for trend analysis

### Critical CVE Enforcement

CI blocks PRs when Grype detects Critical CVEs because these carry D8 penalty weight of 40 (gate-failing regardless of other scores). The PR error message directs developers to use `/triage-cve` for investigation.

---

## Token Utilization and Cost Analysis

ASOPB includes a token utilization aggregation module for tracking LLM consumption across DAST scans and regular agent operations. This is critical for understanding the cost of security scanning vs productive work.

### Why Track Token Utilization?

Promptfoo red-team scans (DAST) consume significant LLM tokens because each probe injects a large system prompt (~10-15K tokens) alongside adversarial payloads. Without classification, these costs are invisible in provider billing dashboards. The token utilization module:

1. Queries token usage from observability backends (Langfuse, CloudWatch, Azure Monitor, GCP Cloud Logging)
2. Classifies traffic as DAST probes vs regular usage using input token fingerprinting
3. Computes costs against configurable pricing models
4. Persists results to SQLite for trend analysis across sprints

### E2E Workflow: Analyzing Promptfoo Scan Costs

**Step 1**: Ensure Langfuse is running and has trace data from your DAST scans.

```bash
# Verify Langfuse has data
docker ps | grep langfuse
curl -s http://localhost:3001/api/public/observations?type=GENERATION \
  -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'Total generations available: {len(data.get(\"data\", []))}')"
```

**Step 2**: Run the aggregation.

```python
import sys
sys.path.insert(0, "examples/adept_asopb/src")

from asopb.observability.factory import BackendFactory
from asopb.observability.aggregator import TokenUtilizationAggregator
from asopb.observability.models import AggregationFilters
from asopb.observability.persistence import TokenUtilizationStore

config = {
    "endpoint": "http://localhost:3001",
    "public_key": "<your-pk>",
    "secret_key": "<your-sk>",
}

backend = BackendFactory.create("langfuse", config)
aggregator = TokenUtilizationAggregator(backend)

filters = AggregationFilters(
    from_date="2026-05-26",  # Start of DAST scan window
    dast_fingerprint_threshold=15000,
)

report = aggregator.aggregate(filters=filters, cost_model="azure-o4-mini")
report.print_summary()

# Persist for trend tracking
store = TokenUtilizationStore()
run_id = store.save_report(report)
print(f"Persisted: {run_id}")
```

**Step 3**: View trends across multiple scan runs.

```python
store = TokenUtilizationStore()
for t in store.get_trends(last_n=5):
    print(f"{t['generated_at'][:10]} | DAST: ${t['dast_total_cost']:.2f} | "
          f"Regular: ${t['regular_total_cost']:.2f} | Total: ${t['total_cost']:.2f}")
```

**Step 4**: Export for sprint review.

```bash
# Via CLI
asopb token-usage aggregate --backend langfuse --from-date 2026-05-01 \
  --cost-model azure-o4-mini --format json --output logs/sprint_token_report.json
```

### DAST Fingerprinting

The module classifies generations using a configurable input token threshold (default: 15,000). This works because:

- **Promptfoo probes**: System prompt (~5K) + adversarial payload (~10-15K) = 15-20K input tokens
- **Regular agent calls**: User message + context = typically 500-5,000 input tokens

The threshold is tunable via `--dast-threshold` (CLI) or `AggregationFilters(dast_fingerprint_threshold=N)` (Python).

### Available Cost Models

| Model | Input $/1M | Output $/1M | Use Case |
|-------|-----------|------------|----------|
| `azure-o4-mini` | $1.10 | $4.40 | Azure OpenAI o4-mini (default) |
| `azure-gpt-4o` | $2.50 | $10.00 | Azure GPT-4o |
| `bedrock-claude-sonnet-4` | $3.00 | $15.00 | AWS Bedrock Claude Sonnet |
| `bedrock-claude-opus` | $15.00 | $75.00 | AWS Bedrock Claude Opus |
| `bedrock-claude-haiku` | $0.25 | $1.25 | AWS Bedrock Claude Haiku |

### Architecture

```
asopb/observability/
├── __init__.py               # Public API exports
├── aggregator.py             # Core aggregation engine
├── models.py                 # Data models (GenerationRecord, CostModel, Report)
├── factory.py                # BackendFactory — registry + create()
├── persistence.py            # SQLite persistence for trend data
├── cli.py                    # Click CLI: asopb token-usage
└── backends/
    ├── base.py               # ObservabilityBackend ABC
    ├── langfuse_backend.py   # Langfuse v2/v3 (fully implemented)
    ├── aws_cloudwatch_backend.py    # AWS CloudWatch (stub)
    ├── azure_monitor_backend.py     # Azure Monitor (stub)
    └── gcp_cloud_trace_backend.py   # GCP Cloud Logging (stub)
```

### Adding a New Backend

The factory pattern makes new backends plug-and-play:

```python
from asopb.observability.backends.base import ObservabilityBackend, BackendConfig
from asopb.observability.factory import BackendFactory
from asopb.observability.models import GenerationRecord

class MyBackend(ObservabilityBackend):
    @property
    def name(self) -> str:
        return "my-backend"

    def validate_config(self) -> None:
        if not self._config.endpoint:
            raise ValueError("endpoint is required")

    def fetch_generations(self, page_limit: int = 50) -> list[GenerationRecord]:
        # Query your observability system here
        ...

BackendFactory.register("my-backend", MyBackend)
```

---

## Claude Code Skills Reference

ASOPB ships with seven Claude Code skills that provide guided workflows for security operations. These skills are invoked with `/<skill-name>` in a Claude Code session.

### /token-utilization

Aggregates LLM token consumption from observability backends, classifies DAST vs regular traffic, computes costs, and persists for trend analysis.

Best for: Post-scan cost analysis, sprint review cost reporting, budget tracking.

### /scan-release

Runs the full ASOPB scan on the staged release tree. Walks through:
1. Staging (`make stage`)
2. Running the 7-pass container scan
3. Verifying output completeness
4. Computing ASPI and gate status
5. Analyzing findings

Best for: Pre-release verification before publish.

### /scan-path

Runs an ASOPB scan on any arbitrary directory. Supports both ADEPT internal modules and third-party repositories.

```
/scan-path examples/biofoundation_mcp_server
/scan-path /data/workspace/external-repo
```

Best for: Ad-hoc security assessment of any codebase.

### /triage-cve

Investigates CVE findings from Grype scans. Walks through:
1. Loading findings from scan output
2. Looking up GHSA/NVD details
3. Reachability analysis (direct vs transitive, service tier exposure)
4. Remediation (upgrade, suppress, accept risk)
5. Verification re-scan

Best for: When CI blocks a PR due to Critical CVEs, or when scan output shows D8 degradation.

### /prepare-release

The complete pre-release verification workflow:
1. Pre-flight checks (clean tree, version parity, scanner image)
2. Stage release tree
3. Run 7-pass scan
4. Analyze findings and compute ASPI
5. Gate decision (PASS/FAIL)
6. Dry-run verification (package build test)

Stops before publish -- only the developer executes `make publish`.

### /asopb-evaluate

Runs the full 8-domain ASOPB evaluation with LLM-graded T2 scoring. Handles credential routing (Azure vs Bedrock), build context synchronization, execution monitoring, and baseline comparison.

Best for: Deep security audits, maturity assessments, and longitudinal tracking.

### /promptfoo-check

Verifies Promptfoo CLI availability and LLM provider credentials, then offers to run Pass 5 (adversarial red-team) against a live endpoint.

Best for: Pre-release DAST verification against a running ADEPT stack.

---

## Using ASOPB for Generic Codebases

ASOPB is designed to work beyond the ADEPT platform. The scan pipeline and evaluator support arbitrary codebases through profiles and configurable parameters.

### Quick Start for Any Repository

```bash
# 1. Install the scanner image (one-time)
cd scripts/release && make docker-build

# 2. Scan any directory
make scan-path SCAN_TARGET=/path/to/your/repo PASSES=enhanced GATE=70

# 3. Or run directly
docker run --rm --network=none \
  -v /path/to/your/repo:/scan:ro \
  -v $(pwd)/output:/output \
  adept-release-scanner:latest \
  /scan --passes enhanced --format json --output-dir /output
```

### Scan Profiles

Profiles customize domain mappings, penalty weights, and category patterns for different frameworks:

```bash
# Generic profile (OWASP LLM Top 10 classification only)
make -C scripts/release asopb-evaluate SCAN_TARGET=/path/to/repo ASOPB_PROFILE=generic

# Custom profile from YAML
make -C scripts/release asopb-evaluate SCAN_TARGET=/path/to/repo ASOPB_PROFILE=/path/to/my-profile.yaml
```

### Creating a Custom Profile

```yaml
name: my-framework
description: Custom profile for my agentic platform
pipeline_weights:
  D5: 0.3
  D7: 0.3
  D8: 0.4
penalty_weights:
  D5:
    critical: 50.0
    high: 20.0
    medium: 10.0
    low: 2.0
framework_domain_map:
  CUSTOM_01:
    target_domain: D3
    target_controls: [D3.1, D3.2]
    base_t3_score: 7.5
category_patterns:
  - ["CUSTOM_01", "custom.*pattern|specific.*keyword"]
```

### What Works Without ADEPT

The following capabilities are fully generic (no ADEPT dependency):

| Capability | How to Use | What It Requires |
|-----------|------------|-----------------|
| Credential scanning | `--passes regex,secrets,trufflehog` | Scanner image |
| CVE/SCA scanning | `--passes grype` | Scanner image |
| PII/NER detection | `--passes all` (includes ML) | Scanner image + 8GB RAM |
| Toxicity detection | `--passes all` | Scanner image + 8GB RAM |
| Dead code detection | `--passes vulture` | Scanner image |
| ASPI scoring | `--format json` | Any pass output |
| Gate decisions | `gate_check.py` | Scan output directory |
| Promptfoo red-team | `--passes promptfoo --promptfoo-target <target>` | Live LLM endpoint + credentials |

### What Requires ADEPT-Specific Configuration

The full 8-domain ASOPB evaluation (T2 LLM grading) uses domain skill prompts that reference ADEPT architecture patterns. For non-ADEPT systems, use the `generic` profile or create a custom profile with domain-appropriate evaluation criteria.

### Integrating with Your CI Pipeline

The pipeline produces standard JSON output compatible with any CI system:

```bash
# Run scan in CI
docker run --rm --network=none \
  -v $GITHUB_WORKSPACE:/scan:ro \
  -v /tmp/scan-output:/output \
  adept-release-scanner:latest \
  /scan --passes enhanced --format json --output-dir /output

# Check gate
python3 scripts/release/gate_check.py /tmp/scan-output --gate 85 --json
```

The JSON output from `gate_check.py` includes:
```json
{
  "gate": 85.0,
  "aspi": 92.1,
  "stage": "S4 (Hardened)",
  "passed": true,
  "domains": {
    "d5": 95.0,
    "d8": 88.3,
    "d7": 94.2
  }
}
```

### The .publish-exclude Pattern

For projects that publish a subset of their repository (open-source releases from larger internal repos), ASOPB integrates with rsync-style exclusion files:

```bash
# Stage only publishable files
rsync -a --filter='merge .publish-exclude' . /tmp/release-stage/

# Scan only what will be published
docker run --rm --network=none \
  -v /tmp/release-stage:/scan:ro \
  adept-release-scanner:latest \
  /scan --passes enhanced --format text
```

This ensures the ASPI score reflects the actual published artifact, not internal-only files that will never reach end users.

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `examples/adept_asopb/src/asopb/` | Core ASOPB Python package |
| `examples/adept_asopb/pyproject.toml` | Package metadata and dependencies |
| `scripts/release/scan_pipeline.py` | 7-pass scan orchestrator with ASPI scoring |
| `scripts/release/gate_check.py` | Release gate binary decision (PASS/FAIL) |
| `scripts/release/compute_aspi.py` | ASPI computation from scan output |
| `scripts/release/analyze_findings.py` | Finding analysis and FP classification |
| `scripts/release/fp_patterns.py` | False positive heuristic rules |
| `scripts/release/compensating_controls.py` | Fingerprint-validated FP suppressions |
| `scripts/release/.asopb-allowlist.yaml` | Category-level allowlist rules |
| `scripts/release/.grype.yaml` | CVE suppression rules with justification |
| `scripts/release/Makefile` | All scanner and evaluation targets |
| `scripts/release/Dockerfile` | Scanner image build definition |
| `.publish-exclude` | rsync filter rules for release staging |
| `.claude/skills/scan-release/SKILL.md` | Claude Code skill: release scan |
| `.claude/skills/scan-path/SKILL.md` | Claude Code skill: arbitrary path scan |
| `.claude/skills/triage-cve/SKILL.md` | Claude Code skill: CVE investigation |
| `.claude/skills/prepare-release/SKILL.md` | Claude Code skill: pre-release workflow |
| `.claude/skills/asopb-evaluate/SKILL.md` | Claude Code skill: full 8-domain evaluation |
| `.claude/skills/promptfoo-check/SKILL.md` | Claude Code skill: red-team credential check |
| `.claude/skills/token-utilization/SKILL.md` | Claude Code skill: token cost analysis |
| `examples/adept_asopb/src/asopb/observability/` | Token utilization aggregation module |
| `examples/adept_asopb/tests/observability/` | Token utilization test suite (43 tests) |

---

## Appendix: ASOPB Package Architecture

```
examples/adept_asopb/src/asopb/
  __init__.py          # Public API exports
  cli.py               # CLI entry point (asopb evaluate, asopb scan)
  config.py            # Pydantic configuration models
  models.py            # Core data models (EvaluationReport, DomainResult, etc.)
  evaluator.py         # Main orchestrator (scan -> analyze -> score -> report)
  scoring.py           # ASPI calculator (composite and pipeline modes)
  profiles.py          # Scan profiles (generic, adept, custom YAML)
  aivss.py             # AI Vulnerability Scoring System integration
  evidence_store.py    # SQLite-backed evidence persistence
  logging.py           # Structured logging
  controls.yaml        # Control definitions (44 controls across 8 domains)
  domains/             # Per-domain evaluators (D1-D8)
    base.py            # Abstract DomainEvaluator class
    d1_model_integrity.py through d8_supply_chain.py
    registry.py        # Domain evaluator registry
  scanner/             # T1 evidence scanners
    auth.py, codebase.py, federation.py, itot.py, etc.
  analyzers/           # External tool integrations
    semgrep.py, bandit.py, pip_audit.py, tls.py, etc.
  redteam/             # T3 adversarial evidence ingestion
    promptfoo_ingester.py, json_ingester.py, langfuse_sink.py
  quality/             # FP suppression and quality tools
    allowlist.py, compensating_controls.py, dead_imports.py
  reports/             # Output formatters
    json_report.py, markdown_report.py, html_report.py
  observability/       # Token utilization aggregation
    aggregator.py, models.py, factory.py, persistence.py, cli.py
    backends/          # Pluggable observability backends
      base.py, langfuse_backend.py, aws_cloudwatch_backend.py,
      azure_monitor_backend.py, gcp_cloud_trace_backend.py
  llm/                 # LLM client for T2 grading
    client.py, skill_loader.py, langfuse_integration.py
  skills/              # Domain evaluation prompts (markdown templates)
    d1_model_integrity.md through d8_supply_chain.md
```

---

## Further Reading

- `scripts/release/SCORING_MODEL.md` -- Detailed scoring model documentation
- `scripts/release/PRE_RELEASE_REVIEW_GUIDE.md` -- Human review guide for releases
- `scripts/release/COMPENSATING_CONTROLS.md` -- Compensating controls methodology
- `scripts/release/TESTING_STRATEGY.md` -- Scanner testing approach
- `examples/adept_asopb/README.md` -- Package README and quickstart
- `examples/adept_asopb/CHANGELOG.md` -- Version history
