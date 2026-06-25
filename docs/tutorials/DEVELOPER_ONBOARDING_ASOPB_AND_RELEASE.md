# Developer Onboarding: ASOPB Security Scanning and Release Pipeline

**Audience**: Software engineers joining the ADEPT project who need to:
1. Deploy a development environment on AWS EC2
2. Understand ASOPB (Agentic Security & Operations Performance Benchmark)
3. Run security scans against ADEPT or arbitrary codebases
4. Develop ADEPT-compatible MCP servers with security best practices
5. Use the release pipeline to publish safely

**Time**: 2-3 hours end-to-end (including EC2 provisioning)

---

## Table of Contents

1. [AWS EC2 Development Environment](#1-aws-ec2-development-environment)
2. [What is ASOPB?](#2-what-is-asopb)
3. [Running Your First ASOPB Scan](#3-running-your-first-asopb-scan)
4. [Understanding ASPI Scores](#4-understanding-aspi-scores)
5. [Scanning Arbitrary Codebases](#5-scanning-arbitrary-codebases)
6. [Developing ADEPT-Compatible MCP Servers](#6-developing-adept-compatible-mcp-servers)
7. [The Release Pipeline](#7-the-release-pipeline)
8. [Claude Code Skills Reference](#8-claude-code-skills-reference)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. AWS EC2 Development Environment

ADEPT development requires a Linux environment with Docker. The recommended setup is an AWS EC2 instance provisioned via CDK.

### 1.1 Prerequisites

- AWS account with EC2/VPC/SSM/CloudFormation permissions
- AWS CLI v2 configured (`aws configure`)
- Node.js 20+ (for CDK CLI)
- Python 3.11+
- VS Code with Remote-SSH extension (recommended)

### 1.2 Provision EC2 Instance

There are two deployment paths depending on your AWS account:

| Account Type | Tool | Guide |
|--------------|------|-------|
| Your AWS VPC | CDK + Ansible (two-step) | `devtools/skypilot/ONBOARDING.md` |
| Other accounts | CDK direct | `devtools/aws-cdk/QUICK_START.md` |

#### Two-Step Deployment (Recommended)

Some accounts enforce SCPs (Service Control Policies) and require agent registration post-creation. The workflow uses containerized CDK + Ansible:

```bash
# 1. Build the devtools container (one-time)
make sky-build

# 2. Bootstrap CDK in account (one-time per account)
make cdk-bootstrap

# 3. Validate the CloudFormation stack
make cdk-diff

# 4. Deploy the EC2 instance
make cdk-deploy

# 5. Wait for cloud-init hooks (~5 min)
make ec2-wait-ready

# 6. Run Ansible OS preparation
make ansible-prepare-vm

# 7. SSH into the instance
make ec2-ssh
```

The instance spec: `t3.2xlarge` (8 vCPU, 32GB RAM), 100GB root + 500GB data volume, Rocky Linux 9.

#### Direct CDK Deployment

```bash
cd devtools/aws-cdk

# Create Python venv and install deps
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Deploy (prompts for confirmation)
cdk deploy --require-approval broadening

# Get instance IP
aws ec2 describe-instances \
  --filters "Name=tag:aws:cloudformation:stack-name,Values=AdeptDev*" \
  --query "Reservations[].Instances[].PublicIpAddress" --output text
```

### 1.3 Bootstrap ADEPT on the Instance

After SSH access is established:

```bash
# Clone the repository
git clone https://github.com/pnnl/adept-agentic.git
cd adept-agentic

# Copy .env from template and configure
cp .env.example .env
# Edit .env with your LLM API keys, AWS credentials, etc.

# Start all services (Docker Compose, ~10 min first time)
make start

# Verify health
make validate-service-health
```

### 1.4 VS Code Remote Development

Add to `~/.ssh/config`:

```
Host adept-dev
    HostName <INSTANCE_IP>
    User rocky
    IdentityFile ~/.ssh/adept-dev.pem
    LocalForward 8083 localhost:8083
    LocalForward 8084 localhost:8084
    LocalForward 8086 localhost:8086
    LocalForward 8180 localhost:8180
    LocalForward 3000 localhost:3000
```

Then in VS Code: `Ctrl+Shift+P` > "Remote-SSH: Connect to Host" > select `adept-dev`.

### 1.5 Docker Hub Rate Limiting (AWS-Specific)

AWS EC2 instances share public IPs and hit Docker Hub's anonymous pull limit (100/6h). Mitigate by authenticating:

```bash
export DOCKERHUB_USERNAME='your-username'
export DOCKERHUB_TOKEN='your-access-token'
./scripts/aws-docker-hub-auth.sh
```

The `quick-start-adept-and-subsystems.sh` script auto-detects AWS and prompts for credentials.

---

## 2. What is ASOPB?

**ASOPB** (Agentic Security & Operations Performance Benchmark) is a security evaluation framework that scores codebases across 8 domains:

| Domain | Name | What It Measures |
|--------|------|------------------|
| D1 | Foundation Model Integrity | Prompt injection, model poisoning, jailbreak resistance |
| D2 | Orchestration Security | Session isolation, state management, auth flows |
| D3 | Tool and MCP Security | Tool schema validation, parameter injection, ACL enforcement |
| D4 | Identity and Authentication | JWT handling, credential storage, RBAC |
| D5 | Federation and Trust | Credential leakage, verified secrets, internal infrastructure exposure |
| D6 | Observability and Audit | Logging, monitoring, audit trail completeness |
| D7 | IT/OT Convergence | Toxic content, compliance violations |
| D8 | Ecosystem and Supply Chain | Dependency vulnerabilities, dead code, supply chain secrets |

### 2.1 Architecture

```
                    ASOPB Library (examples/adept_asopb/)
                    ┌──────────────────────────────────────┐
                    │  CLI (cli.py)                         │
                    │  Config (config.py)                   │
                    │  Evaluator (evaluator.py)             │
                    │  Scoring (scoring.py)                 │
                    │  Scanner Registry (scanner/)          │
                    │  Domain Evaluators (domains/)         │
                    │  Models (models.py)                   │
                    └──────────────────────────────────────┘

                    Release Pipeline (scripts/release/)
                    ┌──────────────────────────────────────┐
                    │  scan_pipeline.py (7-pass pipeline)   │
                    │  scan_sensitive_content.py (Pass 0)   │
                    │  scan_secrets.py (Pass 1)             │
                    │  scan_trufflehog.py (Pass 1.5)        │
                    │  scan_ner_pii.py (Pass 2)             │
                    │  scan_toxicity.py (Pass 3)            │
                    │  scan_promptfoo.py (Pass 5)           │
                    │  publish-to-public.sh                 │
                    └──────────────────────────────────────┘
```

### 2.2 Two Scoring Modes

**Composite** (full 8-domain): Each domain scores controls at three tiers:
- T1: Deterministic checks (pattern matching, config validation)
- T2: LLM-assisted assessment (requires Bedrock/Azure endpoint)
- T3: Dynamic testing (red-team probes against live systems)

Formula: `ASPI = weighted_average(domain_scores)` where each domain = `(T1 + T2 + T3) / 3`

**Pipeline** (D5/D7/D8 subset): Logarithmic penalty model optimized for release scanning:

```
domain_score = max(0, 100 - SUM(weight_i * ln(1 + count_i)))
ASPI = D5 * 0.4 + D8 * 0.4 + D7 * 0.2
```

Pipeline mode is used by the release gate (`make asopb-release-gate`).

---

## 3. Running Your First ASOPB Scan

### 3.0 Quick Start: Full 8-Domain ASPI (Pre-Stage vs Staged)

The two most common evaluation targets are the **source repo** (pre-stage, development signal)
and the **staged release tree** (post-`make stage`, release gate). Both use the same scanner
image and produce a full T1+T2+T3 composite ASPI score.

**Using Claude Code skills (recommended):**

If you're working in Claude Code, invoke the evaluation skill directly:

```
/asopb-evaluate
```

The skill walks you through pre-flight checks, credential routing, execution, monitoring, and
result analysis. It handles both pre-stage and staged targets automatically.

Related Claude Code skills for the full release lifecycle:

| Skill | When to Use |
|-------|-------------|
| `/asopb-evaluate` | Run ASOPB evaluation (pre-stage or staged) with credential routing |
| `/prepare-release` | Full release pipeline: stage, scan, dry-run, publish gate |
| `/validate-tests` | Verify test coverage before evaluation |
| `/audit-hygiene` | Pre-push checklist (includes ASOPB gate status) |

The `/prepare-release` skill includes a Phase 4b (Token Budget Gate) that auto-invokes
`/asopb-evaluate` with the staged tree. Use it when preparing a release; use `/asopb-evaluate`
directly when you want a development-time quality signal on any target.

**Three Scoring Engines — What to Use When:**

| Engine | Skill | Question It Answers | Speed | Cost | Gate? |
|--------|-------|---------------------|-------|------|-------|
| Pipeline ASPI | `/prepare-release`, `/scan-release` | "Can we publish this code?" | 30-75 min | Free | YES (>= 90) |
| Ad-hoc ASPI | `/scan-path` | "What's the security posture of this directory?" | 30-75 min | Free | No (advisory) |
| Promptfoo | `/promptfoo-check` | "Is our deployed system resistant to adversarial prompts?" | ~5-15 min | LLM tokens | No (advisory) |
| Full ASPI | `/asopb-evaluate` | "What's our overall security maturity score?" | ~15-45 min | ~200k tokens | No (advisory) |

How they connect (no overlap):

- **Pipeline ASPI** = static analysis. Scans code for secrets, CVEs, PII, toxicity.
  Produces T2 (implementation) evidence. Deterministic. No external dependencies.
- **Promptfoo** = dynamic red-team. Probes a live LLM endpoint with adversarial inputs.
  Produces T3 (adversarial testing) evidence. Requires live service.
- **Full ASPI** = comprehensive audit. Combines T1 (design docs, graded by LLM) +
  T2 (Pipeline scanner findings) + T3 (Promptfoo results) into an 8-domain composite.

The **release gate** only requires Pipeline ASPI >= 95 because it validates the
published artifact (static code). Promptfoo validates the live deployment. Full ASPI
provides a holistic view for milestone reviews.

**The Evaluation Cube (3 Dimensions):**

ASOPB evaluation has three independent dimensions:

1. **Target stage**: Pre-stage (full source repo) vs Staged (`.publish-exclude` filtered release tree)
2. **Scoring mode**: Pipeline (D5/D7/D8, penalty-based, deterministic) vs Full (8 domains, T1+T2+T3 composite, LLM-assisted)
3. **Codebase**: ADEPT (uses `--profile adept` for domain mapping) vs Arbitrary (generic profile, any repo)

**The 2x2 Matrix (ADEPT codebase — most common):**

| | Pipeline ASPI (D5/D7/D8, penalty) | Full ASPI (8 domains, T1+T2+T3) |
|--|------------------------------------|---------------------------------|
| **Pre-stage** (source repo) | Development quality signal. Fast (5 min), no LLM. | Deep security audit. Per-domain T1/T2. LLM cost (~196k tokens, ~15 min). |
| **Staged** (release tree) | **Release gate (ASPI >= 95)**. Deterministic, air-gapped. | Advisory post-gate quality. Non-blocking. |

When to use each quadrant:

- **Pipeline + Staged** = the release gate. Run before every publish. Must pass >= 95.
- **Pipeline + Pre-stage** = fast CI check. Run after code changes to catch regressions.
- **Full + Pre-stage** = deep development analysis. Per-domain T1/T2 breakdown.
- **Full + Staged** = advisory release quality. Confirms depth on filtered content.

**The third dimension — arbitrary codebases:**

ASOPB can scan any codebase, not just ADEPT. The profile controls how findings map to domains:

| Profile | Use Case | Domain Mapping |
|---------|----------|----------------|
| `adept` | ADEPT framework releases | Keycloak→D4, MCP→D3, Langfuse→D6, HPC→D7 |
| `generic` (default) | Any repository | Pattern-based (JWT→D4, TLS→D5, Docker→D8) |
| Custom YAML | Specialized projects | Your own category→domain rules |

```bash
# Scan arbitrary codebase (uses generic profile by default)
make asopb-evaluate SCAN_TARGET=/path/to/any/repo

# Scan with ADEPT-specific domain mapping
make asopb-evaluate SCAN_TARGET=/path/to/repo ASOPB_PROFILE=adept

# Scan with custom profile
make asopb-evaluate SCAN_TARGET=/path/to/repo ASOPB_PROFILE=/path/to/profile.yaml
```

See Section 5 ("Scanning Arbitrary Codebases") for detailed examples.

**Makefile equivalents (ADEPT codebase):**

```bash
cd scripts/release

# Pipeline + Pre-stage (fast CI check)
make asopb-pipeline SCAN_TARGET=/path/to/your/adept-workspace

# Pipeline + Staged (release gate)
make asopb-pipeline

# Full + Pre-stage (deep development)
make asopb-evaluate SCAN_TARGET=/path/to/your/adept-workspace

# Full + Staged (advisory release)
make asopb-evaluate
```

**Manual commands (copy-paste):**

**Pre-stage (source repo):**

```bash
cd /path/to/your/adept-workspace

mkdir -p logs/asopb-eval-prestage-$(date +%Y%m%d-%H%M) && \
nohup docker run --rm \
  -v /path/to/your/adept-workspace:/scan:ro \
  -v "$(pwd)/logs/asopb-eval-prestage-$(date +%Y%m%d-%H%M)":/output \
  -v "$(pwd)/scripts/release/tests/promptfoo_results:/redteam:ro" \
  --env-file .env \
  --entrypoint python3 \
  adept-release-scanner:latest \
  -m asopb.cli evaluate /scan --format json --output /output \
    --model "azure/o4-mini" \
    --skip-analyzers \
    --redteam-dir /redteam \
  > logs/asopb_eval_prestage_$(date +%Y%m%d_%H%M%S).log 2>&1 &
echo "PRE-STAGE PID: $!"
```

**Staged (release tree):**

```bash
cd /path/to/your/adept-workspace

# Stage first (if not already done)
make -C scripts/release stage

mkdir -p logs/asopb-eval-staged-$(date +%Y%m%d-%H%M) && \
nohup docker run --rm \
  -v /tmp/adept-release-stage-$(date +%Y%m%d):/scan:ro \
  -v "$(pwd)/logs/asopb-eval-staged-$(date +%Y%m%d-%H%M)":/output \
  -v "$(pwd)/scripts/release/tests/promptfoo_results:/redteam:ro" \
  --env-file .env \
  --entrypoint python3 \
  adept-release-scanner:latest \
  -m asopb.cli evaluate /scan --format json --output /output \
    --model "azure/o4-mini" \
    --skip-analyzers \
    --redteam-dir /redteam \
  > logs/asopb_eval_staged_$(date +%Y%m%d_%H%M%S).log 2>&1 &
echo "STAGED PID: $!"
```

**Or via Makefile (equivalent):**

```bash
cd scripts/release

# Pre-stage (source repo)
make asopb-evaluate SCAN_TARGET=/path/to/your/adept-workspace

# Staged (default — uses /tmp/adept-release-stage-YYYYMMDD)
make asopb-evaluate
```

**Key differences:**

| | Pre-Stage | Staged |
|--|-----------|--------|
| What it scans | Full repo (src/, docs/, tests/, scripts/) | Publishable content only (.publish-exclude filtered) |
| Default target | Must set `SCAN_TARGET=$(PWD)` | Default (STAGE_DIR) |
| Purpose | Development quality signal | Release gate (Pipeline ASPI >= 95) |
| Token budget | ~196k tokens (44 calls, 8 domains) | Same |
| Typical duration | ~15 min (azure/o4-mini) | ~12 min (smaller tree) |

**Using Bedrock instead of Azure:**

```bash
source setup-claude-bedrock.sh && \
docker run --rm \
  -v /path/to/your/adept-workspace:/scan:ro \
  -v "$(pwd)/logs/asopb-eval-bedrock-$(date +%Y%m%d-%H%M)":/output \
  -v "$(pwd)/scripts/release/tests/promptfoo_results:/redteam:ro" \
  -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  -e AWS_REGION_NAME="${AWS_REGION_NAME:-us-west-2}" \
  --entrypoint python3 \
  adept-release-scanner:latest \
  -m asopb.cli evaluate /scan --format json --output /output \
    --model "bedrock/us.anthropic.claude-opus-4-20250514-v1:0" \
    --skip-analyzers \
    --redteam-dir /redteam
```

**Monitoring progress:**

```bash
# Follow the log
tail -f logs/asopb_eval_prestage_*.log

# Check if still running
docker ps --filter ancestor=adept-release-scanner:latest --format "{{.ID}} {{.Status}}"
```

**Comparing results:**

```bash
# After both complete, compare ASPI scores
for dir in logs/asopb-eval-prestage-* logs/asopb-eval-staged-*; do
  score=$(python3 -c "import json; r=json.load(open('$dir/report.json')); print(f'{r.get(\"aspi\", 0):.1f}')" 2>/dev/null)
  echo "$(basename $dir): ASPI = $score"
done
```

### 3.1 Quick Lint (No Docker, No Network)

The fastest way to verify ASOPB works:

```bash
cd scripts/release
make asopb-lint
```

This runs import checks and basic validation inside the scanner container with `--network=none`.

### 3.2 Pipeline Posture Check (D5/D7/D8)

Scan the current repository for credential leaks, toxic content, and supply chain issues:

```bash
cd scripts/release
make asopb-posture SCAN_TARGET=/path/to/your/code
```

This produces a JSON report with pipeline ASPI score (target: >= 90 for release).

### 3.3 Full 8-Domain Evaluation (No LLM)

```bash
cd scripts/release
make asopb-pipeline SCAN_TARGET=/path/to/your/code
```

Runs all 8 domain evaluators with `--skip-llm` (deterministic T1 scoring only).

### 3.4 LLM-Assisted Evaluation (Bedrock)

Requires AWS credentials with Bedrock access:

```bash
cd scripts/release
make asopb-evaluate-bedrock SCAN_TARGET=/path/to/your/code
```

This enables T2 scoring via Claude on Bedrock for deeper security analysis.

### 3.4b Token Budget Gate (Cost Control)

Full 8-domain LLM evaluation makes ~44 LLM calls (~196k tokens). Use `--token-budget`
to set a ceiling and get prompted before exceeding it:

```bash
# Set a 200k token ceiling — prompts if estimate exceeds budget
asopb evaluate /scan --token-budget 200000

# Auto-confirm in CI (no interactive prompt)
asopb evaluate /scan --token-budget 200000 --token-budget-confirm

# Or via environment variable
ASOPB_TOKEN_BUDGET=200000 make -C scripts/release asopb-evaluate SCAN_TARGET=/path/to/code
```

When the budget is exceeded, the CLI offers three choices: proceed (f), skip LLM (c),
or abort (a). Use `--token-budget-confirm` in non-interactive environments to auto-proceed.

### 3.5 Interpreting Output

The evaluation produces `report.json` in the output directory:

```json
{
  "scoring_mode": "pipeline",
  "aspi": 72.8,
  "stage": "S3 (Monitored)",
  "domain_scores": {
    "D5": 65.2,
    "D7": 95.0,
    "D8": 68.1
  },
  "formula": "D5*0.4 + D8*0.4 + D7*0.2"
}
```

Stage thresholds:
- **S4 (Hardened)**: ASPI >= 90 — release gate passes
- **S3 (Monitored)**: ASPI >= 70 — acceptable for internal use
- **S2 (Managed)**: ASPI >= 50 — needs remediation before release
- **S1 (Minimal)**: ASPI < 50 — significant security gaps

---

## 4. Understanding ASPI Scores

### 4.1 Pipeline Penalty Weights

Each finding type carries a severity-based penalty weight:

| Domain | Critical | High | Medium | Low |
|--------|----------|------|--------|-----|
| D5 (Federation) | 40 | 15 | 8 | 1.5 |
| D7 (Compliance) | 8 | 4 | 2 | 1 |
| D8 (Supply Chain) | 40 | 15 | 5 | 2.5 |

The logarithmic formula `weight * ln(1 + count)` means:
- First critical finding: large penalty (e.g., 40 * ln(2) = 27.7 points)
- Additional findings: diminishing penalty (logarithmic, not linear)
- Low-severity findings: negligible impact individually

### 4.2 Common Score Patterns

| Scenario | Expected ASPI | Action |
|----------|---------------|--------|
| Clean codebase, no secrets | 100.0 | Ready to release |
| 5 low-severity pattern matches | >= 95 | Review, likely false positives |
| 1 verified credential in source | ~72 | Remove immediately |
| 3 CVEs in dependencies | ~60 | Update dependencies |
| Toxic content in comments | ~85-95 | Review and clean |

### 4.3 False Positive Suppression

ASOPB supports `.asopb-ignore` files for known false positives:

```yaml
# .asopb-ignore
suppressions:
  - finding_id: "REGEX-001"
    path: "tests/fixtures/mock_credentials.py"
    reason: "Test fixture with intentionally fake credentials"
  - category: "internal_ip"
    path: "docs/architecture/*.md"
    reason: "Documentation references to example IPs"
```

---

## 5. Scanning Arbitrary Codebases

ASOPB is codebase-agnostic. You can scan any repository to assess its security posture before developing MCP servers or integrations.

### 5.1 Scan a Third-Party Library

```bash
# Clone the target library
git clone https://github.com/org/some-library.git /tmp/scan-target

# Run pipeline scan
cd /path/to/adept/scripts/release
make asopb-posture SCAN_TARGET=/tmp/scan-target
```

### 5.2 Scan with Custom Domain Selection

```bash
# Only evaluate D8 (supply chain) for a dependency audit
make asopb-custom \
  SCAN_TARGET=/tmp/scan-target \
  ASOPB_DOMAINS="D8" \
  ASOPB_SCORING_MODE=pipeline
```

### 5.3 Scan with Specific Scanners

```bash
# Only run federation and supply_chain scanners (skip slow analyzers)
make asopb-custom \
  SCAN_TARGET=/tmp/scan-target \
  ASOPB_ONLY_SCANNERS="federation,supply_chain" \
  ASOPB_DISABLE_ANALYZERS="tls,semgrep"
```

### 5.4 Pre-Integration Security Assessment

Before wrapping a third-party library as an MCP server:

1. **Run ASOPB posture check** — look for embedded credentials, supply chain issues
2. **Review D3 (Tool Security)** — check if the library validates inputs properly
3. **Check D8 (Supply Chain)** — audit transitive dependencies for known CVEs
4. **Document findings** — add to your MCP server's `SECURITY.md`

```bash
# Full assessment workflow
make asopb-pipeline SCAN_TARGET=/tmp/target-library
# Review report.json
# If ASPI < 70, investigate before proceeding
```

---

## 5.5 Scan Profiles

Profiles bundle framework-specific configuration for ASOPB. They control how red-team findings are classified, how severity-to-penalty mapping works, and which scanners apply to which domains.

**Built-in profiles**:
- `generic` — Codebase-agnostic, OWASP LLM Top 10 classification only
- `adept` — Adds ADEPT attack categories A-H with framework-specific regex patterns

**Using profiles via CLI**:

```bash
# Use built-in profile
make -C scripts/release asopb-evaluate \
  SCAN_TARGET=/path/to/code \
  ASOPB_PROFILE=adept

# Use custom profile YAML
make -C scripts/release asopb-evaluate \
  SCAN_TARGET=/path/to/code \
  ASOPB_PROFILE=/path/to/my-profile.yaml
```

**Creating a custom profile** (for non-ADEPT frameworks):

```yaml
# my-profile.yaml
name: my-framework
description: Custom profile for My Framework
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
  MY_CAT_01:
    target_domain: D3
    target_controls: [D3.1, D3.2]
    base_t3_score: 7.5
category_patterns:
  - ["MY_CAT_01", "custom.*pattern|specific.*keyword"]
```

**Profile lifecycle**:
1. Profile is selected at evaluation time via `--profile` CLI flag
2. If a name is given (`generic`, `adept`), looked up from the built-in registry
3. If a path is given (`.yaml` file), loaded and registered on the fly
4. Profile overrides: penalty weights, domain mapping, scanner-to-domain map, pipeline weights
5. Profile does NOT persist state — it's a pure configuration object

**When to create a custom profile**:
- You're scanning a non-ADEPT codebase with domain-specific attack patterns
- You want different penalty weights (e.g., stricter on D3 for a tool-heavy codebase)
- You need custom red-team classification patterns for framework-specific attacks

**Testing profiles**:

```bash
# Run profile unit tests in container
make -C examples/adept_asopb test-profiles-container
```

---

## 6. Developing ADEPT-Compatible MCP Servers

### 6.1 MCP Server Template

Start from the canonical template:

```bash
cp -r examples/mcp_server_template examples/my_new_mcp_server
cd examples/my_new_mcp_server

# Replace all placeholders
find . -type f -exec sed -i 's/{{NAME}}/my_new/g' {} \;
find . -type f -exec sed -i 's/{{DISPLAY_NAME}}/My New MCP Server/g' {} \;
```

Reference implementations:
- `examples/biofoundation_mcp_server/` — mass spectrometry tools
- `examples/academy_mcp_server/` — educational/training tools
- `examples/aws_mcp/` — AWS service integration

### 6.2 Security Requirements for MCP Servers

Every MCP server registered with ADEPT must meet these D3 (Tool Security) requirements:

1. **Input validation**: All tool parameters must use Pydantic models with constraints
2. **No credential embedding**: Secrets come from environment variables or mounted files
3. **Session isolation**: Tools must scope resources to `mcp_session_id`
4. **No shell injection**: Never pass user input directly to `subprocess` or `os.system`
5. **Timeout enforcement**: All external calls must have configurable timeouts

### 6.3 Running ASOPB on Your MCP Server

```bash
# From your MCP server directory
cd examples/my_new_mcp_server

# Run ASOPB against your server code
make -C ../../scripts/release asopb-posture \
  SCAN_TARGET=$(pwd)

# Or use the full evaluation
make -C ../../scripts/release asopb-pipeline \
  SCAN_TARGET=$(pwd)
```

### 6.4 ASOPB-Driven Development Workflow

1. **Write tool implementation** with Pydantic input validation
2. **Run `asopb-lint`** to catch import/syntax issues
3. **Run `asopb-posture`** to catch credential leaks early
4. **Write tests** (unit + integration + MCP registration)
5. **Run `asopb-pipeline`** before PR submission
6. **Target ASPI >= 90** for the release gate

### 6.5 Registering Your MCP Server with ADEPT

After development, register tools with the ADEPT gateway:

```bash
# Register tools (uses Pydantic schema discovery)
python scripts/register_my_new_tools.py \
  --gateway-url http://localhost:8083 \
  --username admin \
  --password <password>

# Verify registration
afk tools list --format table
```

See `docs/MCP_SERVER_BLUEPRINT.md` for the complete reference.

---

## 7. The Release Pipeline

### 7.1 Release Lifecycle Overview

```
Code Complete → Stage → ASOPB Scan → Dry Run → Publish → Tag
                 │          │            │         │
                 │          │            │         └─ Manual only
                 │          │            └─ Safe preview
                 │          └─ ASPI >= 90 gate
                 └─ make stage (rsync + .publish-exclude)
```

### 7.2 Staging

Staging creates a filtered copy of the repository (credentials, internal docs, and dev tools stripped):

```bash
cd scripts/release
make stage
# Creates /tmp/adept-release-stage-YYYYMMDD/
```

The `.publish-exclude` file (231 rules) controls what gets excluded.

### 7.3 ASOPB Release Gate

The release gate requires Pipeline ASPI >= 95 (see `docs/security/ASPI_SCORING_REFERENCE.md`):

```bash
make asopb-release-gate SCAN_TARGET=/tmp/adept-release-stage-20260521
```

If the gate fails, the scan report shows which findings need remediation.

**CVE remediation workflow**: Use the `/triage-cve` Claude Code skill to investigate D8 supply chain findings. It guides you through CVE lookup, reachability analysis, and remediation (package upgrade or compensating control). See `docs/guides/CVE_TRIAGE_GUIDE.md` for the full walkthrough.

**Key reference documents for release security**:
- `docs/security/ASPI_SCORING_REFERENCE.md` — Scoring formula, gate thresholds, scan type differences
- `docs/guides/CVE_TRIAGE_GUIDE.md` — CVE investigation and remediation workflow
- `docs/guides/COMPENSATING_CONTROLS_GUIDE.md` — False-positive suppression with integrity checks
- `scripts/release/PRE_RELEASE_REVIEW_GUIDE.md` — Full 5-phase pre-release verification

### 7.4 Dry Run

Preview what would be published without actually pushing:

```bash
./publish-to-public.sh \
  --version v1.0.20260521 \
  --source-ref main \
  --dry-run
```

### 7.5 Publish (Manual Only)

Publishing is never automated. After dry-run review:

```bash
./publish-to-public.sh \
  --version v1.0.20260521 \
  --source-ref main
```

This squash-merges the filtered tree into `pnnl/adept-agentic` (public repo).

### 7.6 Makefile Target Reference

All targets are in `scripts/release/Makefile`:

| Target | Purpose | Network |
|--------|---------|---------|
| `asopb-lint` | Import/syntax validation | none |
| `asopb-posture` | D5/D7/D8 pipeline scoring | none |
| `asopb-pipeline` | Full 8-domain, no LLM | none |
| `asopb-evaluate-bedrock` | LLM-assisted via Bedrock | egress proxy |
| `asopb-redteam-live` | Dynamic red-team probes | target endpoint |
| `asopb-release-gate` | Pre-release ASPI check | none |
| `asopb-custom` | Fully parameterized | varies |
| `scan` | Quick regex scan (no Docker) | host |
| `scan-lightweight` | Regex + detect-secrets | host |
| `scan-enhanced` | + TruffleHog | host |
| `docker-scan-staged` | Full container scan | none |
| `stage` | Create release staging | host |

### 7.7 Parameterizable Variables

```bash
# Domain selection
ASOPB_DOMAINS="D5,D7,D8"

# Scanner control
ASOPB_ONLY_SCANNERS="federation,supply_chain"
ASOPB_DISABLE_SCANNERS="codebase"

# Analyzer control
ASOPB_DISABLE_ANALYZERS="tls"
ASOPB_ONLY_ANALYZERS="semgrep,bandit"

# Scoring mode
ASOPB_SCORING_MODE=pipeline  # or: composite

# Scan target
SCAN_TARGET=/path/to/code
```

---

## 8. Claude Code Skills Reference

If you use Claude Code for development, invoke these skills for guided workflows:

### Feature Lifecycle Skills

| Skill | Command | Purpose |
|-------|---------|---------|
| Start Feature | `/start-feature` | Begin any feature/bugfix/enhancement (Phases 0-9) |
| Start Sprint | `/start-sprint` | Multi-day coordinated sprint setup (issues + plans) |
| Validate Tests | `/validate-tests` | Check required test tiers and timestamped evidence |
| Write Session Report | `/write-session-report` | Draft implementation report after tests pass |
| Update Tracking Docs | `/update-tracking-docs` | Sync CHANGELOG, ROADMAP, KNOWN_ISSUES |
| Prepare Commit | `/prepare-commit` | Build Conventional Commit message with doc references |
| Audit Hygiene | `/audit-hygiene` | Full Code Hygiene checklist (PASS/FAIL per item) |
| Pre-Push Review | `/pre-push-review` | Semantic self-review before push |
| Prepare PR | `/prepare-pr` | Create PR, check Copilot/peer review, resolve findings |
| Close Task | `/close-task` | Run Phases 5-9 in sequence (test→document→commit→audit→push) |

### MCP Server Development Skills

| Skill | Command | Purpose |
|-------|---------|---------|
| MCP Plan | `/mcp-plan` | Analyze a library and produce MCP server plan |
| MCP Scaffold | `/mcp-scaffold` | Create new MCP server from template |
| MCP Add Tool | `/mcp-add-tool` | Add tool to existing MCP server |
| MCP Test | `/mcp-test` | Run 4-tier MCP test strategy |
| MCP Register | `/mcp-register` | Register MCP tools with ADEPT gateway |

### Release and Security Skills

| Skill | Command | Purpose |
|-------|---------|---------|
| Prepare Release | `/prepare-release` | Stage, scan, dry-run (never publishes) |
| ASOPB Evaluate | `/asopb-evaluate` | Guided security evaluation with 5 workflow options |
| Scan Release | `/scan-release` | Full 7-pass ASOPB scan on staged release tree |
| Scan Path | `/scan-path` | Ad-hoc scan of any directory with ASPI scoring |
| Triage CVE | `/triage-cve` | Investigate and remediate CVE findings from scans |
| Promptfoo Check | `/promptfoo-check` | Adversarial red-team evaluation against live LLM |
| Token Utilization | `/token-utilization` | Aggregate LLM token consumption and costs |
| Sync Docs | `/sync-docs` | Check parity across public Pages, wiki, CLAUDE.md |
| Connect ADEPT | `/connect-adept` | Connect Claude Code to an ADEPT instance |

### 8.1 ASOPB Evaluate Workflows

The `/asopb-evaluate` skill offers 5 workflows:

- **A. Quick Posture** — D5/D7/D8 subset with pipeline scoring (2 min)
- **B. Full Pipeline** — All 8 domains, deterministic only (5 min)
- **C. LLM-Assisted** — Full evaluation via Bedrock or Azure (15-90 min)
- **D. Red-Team** — Dynamic probes against live endpoints (20 min)
- **E. Release Gate** — Pass/fail check before publish (5 min)

**Common invocation patterns with skills:**

| Goal | Skill | What Happens |
|------|-------|--------------|
| Development quality signal | `/asopb-evaluate` → choose target: project root | Runs all 8 domains against source tree, shows ASPI |
| Pre-release validation | `/prepare-release` | Stages, scans (Pipeline ASPI >= 95 gate), dry-run |
| Full composite before merge | `/asopb-evaluate` → choose target: staged tree | T1+T2+T3 composite on filtered release content |
| Quick check after code changes | `/asopb-evaluate` → choose "Quick Posture" | D5/D7/D8 in 2 min, no LLM cost |
| Cost-aware full evaluation | `/asopb-evaluate` → set `--token-budget 200000` | Estimates cost, prompts before spending tokens |

**Skill-to-Makefile mapping:**

```bash
# These are equivalent:
# Skill: /asopb-evaluate → target: project root, model: azure/o4-mini
make -C scripts/release asopb-evaluate SCAN_TARGET=/path/to/your/adept-workspace

# Skill: /asopb-evaluate → target: staged tree (default)
make -C scripts/release asopb-evaluate

# Skill: /prepare-release → Phase 4 (ASOPB scan)
make -C scripts/release stage && make -C scripts/release asopb-pipeline

# Skill: /asopb-evaluate → Quick Posture
make -C scripts/release asopb-posture SCAN_TARGET=/path/to/your/adept-workspace
```

**When to use which skill:**

- Use **`/asopb-evaluate`** when you want to run an evaluation at any point during development.
  It handles image checks, credential routing, execution, and result analysis.
- Use **`/prepare-release`** when you're ready to publish — it runs the full release pipeline
  including staging, pipeline scan (ASPI >= 95 gate), token budget gate for T2, and dry-run.
  It never executes the publish step.
- Use **`/validate-tests`** before evaluation to ensure your test evidence is current.
- Use **`/audit-hygiene`** as a final pre-push check that includes ASOPB gate status.

---

## 9. Troubleshooting

### Scanner Container Issues

```bash
# Verify scanner image exists
docker images | grep adept-release-scanner

# Rebuild if missing or stale (syncs canonical ASOPB library → builds image)
cd scripts/release && make docker-build

# Check image freshness vs source changes
docker inspect adept-release-scanner:latest --format '{{.Created}}' | cut -d'T' -f1
git log -1 --format=%ci -- scripts/release/scan_*.py scripts/release/scanner_logging.py examples/adept_asopb/src/asopb/

# Run self-test (includes upstream version parity + CVE check)
make docker-self-test

# Skip parity check for faster iteration
make docker-self-test SELFTEST_FLAGS="--skip-parity"
```

**Image freshness**: Scanner code and the ASOPB library (`examples/adept_asopb/src/asopb/`) are
baked into the Docker image at build time via the `sync-asopb` → `check-asopb` → `docker build`
chain. If you modify scanner scripts or `asopb/logging.py`, you MUST rebuild the image before
scanning. The Makefile handles this automatically when using `make docker-build`.

**Self-test output**: Every scan automatically runs `scanner_selftest.py` first (9 categories).
Results appear in stderr and `selftest_results.json`. Categories include:
- Binary/Python package version validation
- Scanner script importability
- ML model weight availability
- **Version parity vs upstream** (PyPI + GitHub) with CVE lookup via OSV.dev

If parity checks find CVEs, use the `/triage-cve` Claude Code skill to investigate.

### ML Passes Missing (Silent OOM)

If `pass_ner_pii.json` and/or `pass_toxicity.json` are missing from scan output:

**Root cause**: Docker container killed by cgroup when memory exceeded. No Python traceback
is produced — the process simply vanishes mid-inference.

**Symptoms**:
- stderr shows model weights loading, then silence (no "Complete" line)
- Only `pass_regex.json` + `pass_secrets.json` in output
- `gate_check.py` reports ASPI=100 (false positive — treats missing files as zero findings)

**Fix**:
```bash
# Verify memory flags are set (Makefile auto-detects host RAM)
make -n docker-scan-staged | grep -o '\-\-memory=[^ ]*'
# Expected: --memory=8g (on >=16GB host)

# Manual run with explicit memory:
docker run --rm --network=none --shm-size=4g --memory=8g ...

# Check host available memory
free -m | awk '/^Mem:/{print "Available:", $7, "MB"}'

# Check dmesg for OOM kill evidence
dmesg | tail -20 | grep -i "oom\|killed"
```

**Required minimums**: `--shm-size=4g` + `--memory=8g` (NER+PII peak ~3.5GB RSS combined).
See `.claude/skills/scan-release/SKILL.md` for detailed model memory profiles.

### ASPI Score of 0.0

This usually means scanners returned no findings (empty scan results). Check:
1. `SCAN_TARGET` path exists and contains files
2. Scanner container has read access to the target
3. Run with `--verbose` flag for detailed output

### LLM Evaluation Timeout

If `asopb-evaluate-bedrock` hangs:
1. Check AWS credentials: `aws sts get-caller-identity`
2. Verify Bedrock access: `aws bedrock list-foundation-models --region us-west-2`
3. Check egress proxy: the scanner container uses `--network=none` by default; LLM targets use the egress proxy

### EC2 Instance Provisioning Fails

Common causes:
- **Insufficient permissions**: Need EC2, VPC, SSM, CloudFormation, IAM (for instance profile)
- **SCP blocks**: Use only approved VPC subnets (auto-selected by CDK stack)
- **Quota exceeded**: Check EC2 instance limits in the region
- **AMI not found**: The CDK stack uses Rocky Linux 9 AMI; verify it exists in your region

### Docker Hub Rate Limiting

```bash
# Check remaining pulls
docker pull alpine 2>&1 | grep -i "rate"

# Authenticate to increase limit
./scripts/aws-docker-hub-auth.sh
```

---

## Appendix A: File Layout Reference

```
scripts/release/
├── Makefile                    # All scan/evaluate/release targets
├── Dockerfile                  # Scanner container (TruffleHog, BERT, Promptfoo)
├── scan_pipeline.py            # 7-pass orchestrator
├── scan_sensitive_content.py   # Pass 0: regex patterns
├── scan_secrets.py             # Pass 1: detect-secrets
├── scan_trufflehog.py          # Pass 1.5: TruffleHog v3
├── scan_ner_pii.py             # Pass 2: BERT NER + PII
├── scan_toxicity.py            # Pass 3: toxic-bert
├── scan_promptfoo.py           # Pass 5: LLM red-team
├── publish-to-public.sh        # Release publisher
├── PRE_RELEASE_REVIEW_GUIDE.md # Human review checklist
├── SCORING_MODEL.md            # Penalty weight documentation
└── tests/                      # Scanner self-tests (367 tests)

examples/adept_asopb/
├── src/asopb/
│   ├── cli.py                  # Click CLI (evaluate command)
│   ├── config.py               # Pydantic config (EvalConfig, ScoringConfig)
│   ├── evaluator.py            # Main evaluation orchestrator
│   ├── scoring.py              # ASPICalculator + PipelineScorer
│   ├── models.py               # Data models (DomainResult, ScanFinding, etc.)
│   ├── scanner/                # 8 scanner implementations
│   └── domains/                # 8 domain evaluators (D1-D8)
├── tests/                      # 384 unit tests
├── Makefile                    # docker-build, docker-test targets
└── pyproject.toml              # Package definition
```

## Appendix B: Quick Command Reference

```bash
# === EC2 Provisioning ===
make sky-build                              # Build devtools container
make cdk-deploy                             # Deploy EC2 instance
make ansible-prepare-vm                     # Configure OS
make ec2-ssh                                # SSH into instance

# === ADEPT Stack ===
make start                                  # Start all services
make stop                                   # Stop services
make rebuild                                # Full rebuild
make validate-service-health                # Health check

# === ASOPB Scanning ===
make -C scripts/release asopb-lint          # Quick lint
make -C scripts/release asopb-posture       # D5/D7/D8 pipeline
make -C scripts/release asopb-pipeline      # Full 8-domain
make -C scripts/release asopb-release-gate  # Release check

# === MCP Server Development ===
cp -r examples/mcp_server_template examples/my_server  # Start from template
make -C scripts/release asopb-posture SCAN_TARGET=examples/my_server  # Security check

# === Release ===
make -C scripts/release stage               # Stage for release
make -C scripts/release docker-scan-staged  # Scan staged tree
./scripts/release/publish-to-public.sh --dry-run  # Preview
```

---

## CI/CD Security Pipeline (DevSecOps)

The ASOPB scanning pipeline is integrated into GitHub Actions CI via `.github/workflows/asopb-pre-release-scan.yml`. It uses industry-standard DevSecOps categories:

| Category | What It Does | CI Behavior | Skill Equivalent |
|----------|-------------|-------------|------------------|
| **SAST** | Pattern matching for secrets, credentials, internal infra | Blocking (Phase 1) | `/scan-release` |
| **SCA** | Dependency vulnerability scanning (Grype) + version drift | Critical CVEs block; drift advisory | `/triage-cve` |
| **DAST** | Promptfoo LLM adversarial red-team (OWASP LLM Top 10) | Advisory in CI; required for release | `/promptfoo-check` |
| **DLP** | ML-based content safety (NER, PII, toxicity detection) | Advisory (conditional, labeled PRs only) | `/scan-release` (full) |

### What Blocks Your PR

Only three things will block a PR from merging:

1. **ASPI < threshold** (Phase 1 regex scan) — fix: run `/scan-release` locally, remediate findings
2. **Critical CVEs detected** (Grype SCA scan) — fix: run `/triage-cve`, upgrade or suppress
3. **ASPI < 90 on publish** (publish workflow gate) — fix: run `/prepare-release` locally

Everything else (DLP findings, DAST results, version drift) appears as advisory PR comments.

### ASPI Score History

Every CI scan uploads a JSON artifact (`aspi-history-<sha>`, 365-day retention) with Phase 1 and Phase 2 scores. Query historical trends:

```bash
gh api repos/{owner}/{repo}/actions/artifacts \
  --jq '.artifacts[] | select(.name | startswith("aspi-history-")) | {name, created_at}' | head -20
```

### Version Parity Advisory

On every PR, a "Scanner Dependency Drift" comment is posted showing which scanner dependencies are behind upstream and whether any pinned versions have known CVEs. This is informational only — no action required unless Critical CVEs are flagged.

---

## DAST: Cross-Referenced Report Pipeline

Beyond CI advisory scans, ADEPT provides a full DAST (Dynamic Application Security Testing) pipeline that probes the live ADEPT gateway with 42 adversarial tests and cross-references the results with Docker service logs.

### Why Cross-Referencing Matters

Standard DAST (promptfoo eval) only shows the client perspective: "did the probe pass or fail?" The cross-referenced report adds the server perspective: what did agent_gateway and orchestration_service actually log during each probe? This catches:

- **Auth bypass attempts** that the gateway silently rejected
- **System prompt leakage** that passed client grading but triggered server warnings
- **Tool ACL violations** that the orchestration service blocked at Tier 2

### Quick Start

```bash
cd scripts/release

# Full local DAST (requires running ADEPT stack)
make dast-full

# External path via nginx (TLS, production-equivalent)
make dast-full-external

# Remote EC2 stack via SSH tunnel
make dast-remote DAST_HOST=10.115.14.51
```

### What You Get

After `make dast-full` completes (~2 minutes):

| File | Description |
|------|-------------|
| `logs/dast-adept-*/promptfoo_results.json` | Raw promptfoo output (42 test results) |
| `logs/dast-adept-*/dast_report.html` | Interactive HTML dashboard (Chart.js, dark theme) |
| `logs/dast-adept-*/dast_report.json` | Structured report with server correlation |
| `logs/dast-adept-*/dast_report.md` | Markdown summary |

### Reading the HTML Report

The interactive report has four tabs:

1. **Timeline**: Bar chart showing all 42 probes with pass/fail/error status. Click any bar to jump to probe details.
2. **OWASP Categories**: Radar chart of pass rates per OWASP LLM Top 10 category, plus stacked bar breakdown.
3. **Probe Details**: Filterable/sortable table. Click any row to expand full prompt, response, grading reason, and server-side correlation (gateway request ID, orchestration thread/session, warnings).
4. **Anomalies**: Cards showing probes that passed client grading but triggered server-side warnings. These are the cross-reference insights.

### Interpreting Results

| Pass Rate | Assessment |
|-----------|-----------|
| >= 95% | Excellent — platform defenses working well |
| 85-95% | Good — review failures for actionable fixes |
| 70-85% | Needs attention — multiple OWASP categories exposed |
| < 70% | Critical — investigate before release |

### Configuration

The Makefile uses parameterized variables for auth:

```makefile
DAST_KEYCLOAK_REALM ?= master
DAST_CLIENT_ID ?= validation-runner-client
DAST_KEYCLOAK_PORT ?= 8180
```

Override for different stack configurations: `make dast-full DAST_KEYCLOAK_REALM=agentic`

### Related Skills

| Skill | Use Case |
|-------|----------|
| `/promptfoo-check` | Check credentials, offer scan modes, run advisory scan |
| `/scan-release` | Full 7-pass static scan + optional DAST supplemental check |
| `/deploy-cloud` | Provision EC2 + run DAST as Phase 6 advisory step |

---

## Related Documentation

- Architecture: `docs/PLATFORM_AI_ENGINEER_ONBOARDING.md`
- MCP Blueprint: `docs/MCP_SERVER_BLUEPRINT.md`
- Release Process: `docs/guides/RELEASING.md`
- Code Hygiene: `docs/development/CODE_HYGIENE.md`
- Feature Workflow: `docs/development/FEATURE_DEVELOPMENT_WORKFLOW.md`
- AWS Deployment: `devtools/AWS_VM_DEPLOYMENT_GUIDE.md`
- SkyPilot Onboarding: `devtools/skypilot/ONBOARDING.md`
- Scoring Model: `scripts/release/SCORING_MODEL.md`
- Scanner README: `scripts/release/README.md`
- **ASPI Scoring Reference**: `docs/security/ASPI_SCORING_REFERENCE.md` (scan types, gates, domain weights)
- **CVE Triage Guide**: `docs/guides/CVE_TRIAGE_GUIDE.md` (investigate and remediate CVE findings)
- **Compensating Controls Guide**: `docs/guides/COMPENSATING_CONTROLS_GUIDE.md` (FP suppression with integrity checks)
- **DAST Pipeline**: `docs/implementation-plans/DAST_CROSS_REFERENCED_REPORT_PIPELINE.md` (architecture, targets, acceptance criteria)
- **Pre-Release Review Guide**: `scripts/release/PRE_RELEASE_REVIEW_GUIDE.md` (5-phase release verification)
- **CI Gap Remediation Plan**: `docs/implementation-plans/CI_GAP_REMEDIATION_PLAN.md` (DevSecOps pipeline hardening)
- **CI Configuration**: `docs/ci/ASOPB_CI_CONFIGURATION.md` (workflow operational reference)
