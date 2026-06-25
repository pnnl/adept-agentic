---
name: promptfoo-check
description: Check promptfoo LLM red-team credentials availability and offer to run Pass 5 adversarial scan against a live endpoint.
disable-model-invocation: true
allowed-tools: Bash(env | grep*) Bash(which *) Bash(command -v *) Bash(docker *) Bash(make *) Bash(python3 *) Bash(nohup *) Bash(ls *) Bash(cat *) Bash(grep *) Bash(find *) Bash(git *) Bash(node *) Bash(npm *) Bash(promptfoo *) Bash(mkdir *) Bash(tail *) Read
argument-hint: [optional: target provider, e.g. azureopenai:chat:o4-mini or openai:gpt-4o]
---

You are assisting an ADEPT developer with Pass 5 (promptfoo LLM red-team) of the ASOPB pre-release scan pipeline. Your job is to check that all required credentials and tooling are available, report readiness status, and offer to run the scan.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.
Do not include any AI agent references in commit messages or document metadata.

## DevSecOps Classification

This skill performs **DAST (Dynamic Application Security Testing)** — specifically LLM adversarial red-teaming against OWASP LLM Top 10 attack categories.

**CI vs pre-release enforcement**:
- In CI (`.github/workflows/asopb-pre-release-scan.yml`): **advisory only** (`continue-on-error: true`). Expensive due to backend LLM API calls — appropriate for awareness but not as a PR gate.
- In `/prepare-release`: **required gate step**. Must pass before publish approval.
- In `/asopb-evaluate`: Contributes to T3 (Adversarial) tier scores across all 8 domains.

**Cost awareness**: Each run probes a live LLM endpoint (Azure OpenAI, AWS Bedrock, or ADEPT gateway). A typical 66-test suite costs ~$0.50-2.00 per run depending on model pricing. This is why it is advisory in CI (runs on every PR push) but mandatory only at the pre-release gate.

---

## Step 1: Check promptfoo CLI and runtime availability

Check Node.js and promptfoo binary:

```
node --version 2>/dev/null
which promptfoo 2>/dev/null || command -v promptfoo 2>/dev/null
promptfoo --version 2>/dev/null
```

If promptfoo is not found on the host, check the scanner Docker image:

```
docker run --rm --entrypoint promptfoo ghcr.io/<org>/adept-release-scanner:latest --version 2>/dev/null
```

Also check the pinned version in the Dockerfile for reference:

```
grep PROMPTFOO_VERSION scripts/release/Dockerfile
```

If neither host nor container has promptfoo:
- Report: "promptfoo CLI not found on host or in scanner image."
- Suggest: `npm install -g promptfoo@<pinned-version>` (requires Node.js >=20.20.0)
- Or rebuild the scanner image: `cd scripts/release && make docker-build`

---

## Step 2: Check LLM provider credentials

Promptfoo needs API credentials for the target LLM provider. Check for the following environment variables based on common provider prefixes:

### Azure OpenAI (target prefix: `azureopenai:`)
```
env | grep -E "^(AZURE_API_KEY|AZURE_API_HOST|AZURE_API_VERSION|AZURE_OPENAI_API_KEY|AZURE_OPENAI_ENDPOINT)" 2>/dev/null | sed 's/=.*/=***/'
```

Required: `AZURE_API_KEY` (or `AZURE_OPENAI_API_KEY`) + `AZURE_API_HOST` (or `AZURE_OPENAI_ENDPOINT`)
Optional: `AZURE_API_VERSION` (defaults to 2024-02-01)

### OpenAI (target prefix: `openai:`)
```
env | grep -E "^OPENAI_API_KEY" 2>/dev/null | sed 's/=.*/=***/'
```

Required: `OPENAI_API_KEY`

### Anthropic (target prefix: `anthropic:`)
```
env | grep -E "^ANTHROPIC_API_KEY" 2>/dev/null | sed 's/=.*/=***/'
```

Required: `ANTHROPIC_API_KEY`

### AWS Bedrock (target prefix: `bedrock:`)
```
env | grep -E "^(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_REGION_NAME|AWS_DEFAULT_REGION)" 2>/dev/null | sed 's/=.*/=***/'
```

Required: `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + region

---

## Step 3: Report credential readiness

Present a status table summarizing what was found:

```
Pass 5 (Promptfoo) Readiness Check
====================================
CLI:              [AVAILABLE | MISSING]  (version X.Y.Z / via Docker image)
Azure OpenAI:    [READY | PARTIAL | MISSING]
OpenAI:          [READY | MISSING]
Anthropic:       [READY | MISSING]
AWS Bedrock:     [READY | PARTIAL | MISSING]
```

Mark a provider as READY only if all required variables are set (non-empty).
Mark as PARTIAL if some but not all required variables are set.
Mark as MISSING if none are set.

If the user provided a target argument, highlight whether that specific provider is ready.

---

## Step 4: Check for hand-crafted configs

Look for the curated adversarial test configs:

```
ls scripts/release/tests/promptfoo_redteam_config.yaml \
   scripts/release/tests/promptfoo_redteam_config_bedrock.yaml \
   scripts/release/tests/promptfoo_redteam_config_adept.yaml 2>/dev/null
```

Report which configs are available:
- `promptfoo_redteam_config.yaml`: 13 tests, Azure OpenAI target
- `promptfoo_redteam_config_bedrock.yaml`: 42 tests, AWS Bedrock Claude Opus
- `promptfoo_redteam_config_adept.yaml`: 42 tests, live ADEPT gateway (requires running stack)

### Check ADEPT stack availability (for PROVIDER=adept):

```
docker ps --filter "name=agent_gateway" --filter "status=running" --format "{{.Names}}: {{.Status}}" 2>/dev/null
docker ps --filter "name=orchestration_service" --filter "status=running" --format "{{.Names}}: {{.Status}}" 2>/dev/null
docker ps --filter "name=keycloak" --filter "status=running" --format "{{.Names}}: {{.Status}}" 2>/dev/null
```

If all three services are running, report: "ADEPT stack running -- PROVIDER=adept available."
If not: "ADEPT stack not running -- PROVIDER=adept unavailable (run: make start)."

### Pre-flight checks for PROVIDER=adept (CRITICAL):

Before running `make dast-full` or `make dast-full-external`, verify:

1. **Keycloak realm**: `docker exec agent_gateway env | grep KEYCLOAK_REALM` — confirm the realm name matches `DAST_KEYCLOAK_REALM` in the Makefile (default: `master`).

2. **Client ID**: `cat deployment/local/docker-compose/.env-keycloak-credentials-dir/VALIDATION_RUNNER_CLIENT_ID` — confirm it matches `DAST_CLIENT_ID`.

3. **JWT test**: Acquire a token and verify agent_gateway accepts it.
   NOTE: The token issuer (`iss` claim) will be `http://keycloak:8180/...` — the JWT must
   be used within the same Docker network where it was issued, otherwise issuer validation fails.
   ```bash
   CLIENT_SECRET=$(cat deployment/local/docker-compose/.env-keycloak-credentials-dir/VALIDATION_RUNNER_CLIENT_SECRET)
   JWT=$(docker run --rm --network=adept_application_network curlimages/curl:latest -sf -X POST \
     "http://keycloak:8180/realms/master/protocol/openid-connect/token" \
     -d "grant_type=client_credentials" -d "client_id=validation-runner-client" \
     -d "client_secret=$CLIENT_SECRET" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
   docker run --rm --network=adept_application_network curlimages/curl:latest -sf \
     -H "Authorization: Bearer $JWT" http://agent_gateway:8081/health
   ```

4. **nginx reload (external path only)**: If agent_gateway was restarted more recently than nginx_proxy, run `docker exec nginx_proxy nginx -s reload` to refresh upstream DNS cache.

---

## Step 5: Offer scan options

Based on readiness, present available scan options to the user:

### If at least one provider is READY:

```
Available scan modes:
  1. Container-based eval with provider presets (RECOMMENDED, 42 tests, ~5 min)
     cd scripts/release && make promptfoo-scan-container PROVIDER=bedrock
     cd scripts/release && make promptfoo-scan-container PROVIDER=azure
     cd scripts/release && make promptfoo-scan-container PROVIDER=bedrock LANGFUSE=1

  2. Hand-crafted eval on host (requires promptfoo CLI on PATH)
     promptfoo eval -c scripts/release/tests/promptfoo_redteam_config.yaml

  3. Auto-generated red-team scan (OWASP + 14 security plugins, 5 tests/plugin, ~30 min)
     cd scripts/release && make promptfoo-scan TARGET=<provider> PURPOSE="ADEPT AI assistant"

     Note: promptfoo redteam run (cloud generation) may require email verification
     in v0.121.5+. Use mode 1 for air-gapped/offline environments.

  4. Offline dataset scan (no LLM generation for test creation, still needs target for eval)
     cd scripts/release && make promptfoo-offline TARGET=<provider>

     Plugins: beavertails, cyberseceval, donotanswer, harmbench, xstest

  5. Pipeline integration (runs promptfoo as part of full scan_pipeline.py)
     python3 scripts/release/scan_pipeline.py /tmp/adept-release-stage \
       --passes regex,secrets,trufflehog,promptfoo \
       --promptfoo-target <provider>
```

### Provider presets (for `make promptfoo-scan-container`):

| PROVIDER= | Model | Config YAML | Required Env Vars | Notes |
|-----------|-------|-------------|-------------------|-------|
| `bedrock` | Claude Opus 4.6 (inference profile) | `promptfoo_redteam_config_bedrock.yaml` | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION | Direct LLM probe (no platform defenses) |
| `azure` | Azure OpenAI o4-mini | `promptfoo_redteam_config.yaml` | AZURE_API_KEY, AZURE_API_HOST | Direct LLM probe (no platform defenses) |
| `adept` | ADEPT Gateway (ScientificWorkflowAgent) | `promptfoo_redteam_config_adept.yaml` | (auto: JWT from Keycloak) | Full stack probe with auth, RBAC, tool ACL |

### ADEPT provider details (PROVIDER=adept):

**What it tests**: The full ADEPT 3-tier stack — agent_gateway (auth/RBAC) + orchestration_service (system prompt, tool management) + LLM backend. This catches issues that direct LLM probes miss: auth bypass, system prompt leakage through the orchestration layer, tool ACL violations.

**JWT acquisition** (handled automatically by `make dast-full`):
```bash
# Service account (validation-runner-client, full access):
CRED_DIR=deployment/local/docker-compose/.env-keycloak-credentials-dir
CLIENT_SECRET=$(cat $CRED_DIR/VALIDATION_RUNNER_CLIENT_SECRET)
CLIENT_ID=$(cat $CRED_DIR/VALIDATION_RUNNER_CLIENT_ID)
JWT=$(docker run --rm --network=adept_application_network \
  curlimages/curl -sf -X POST "http://keycloak:8180/realms/master/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

NOTE: The token issuer (iss claim) will be `http://keycloak:8180/...`. The JWT must be used within the same Docker network where the gateway validates against this issuer. Using `localhost:8180` works only if the gateway accepts the localhost issuer (non-standard).

**Model ID**: `agentic-framework:scientific-agent-v1` (ADEPT's meta-model, not a raw LLM)

**Two access patterns**:
- Container-to-container: `OPENAI_BASE_URL=http://agent_gateway:8081/v1` (used by `make dast-full`)
- External via nginx: `OPENAI_BASE_URL=https://api.agentic.local/v1` (used by `make dast-full-external`)

**Post-scan cross-reference report**:
After promptfoo eval completes, `report_dast_cross_reference.py` correlates results with Docker service logs (agent_gateway, orchestration_service) to show what happened server-side for each probe. Run via:
```bash
cd scripts/release && make dast-full          # Local (internal path)
cd scripts/release && make dast-full-external  # External (nginx TLS path)
cd scripts/release && make dast-remote DAST_HOST=<ip>  # Remote (SSH tunnel, any endpoint with 80/443)
```

**Network authorization note**: When targeting remote endpoints, ensure you have authorization to send adversarial probes to that host. For PNNL-managed infrastructure, verify the scan is permitted under your security testing authorization before running cross-network adversarial traffic.

**Outputs**: `dast_report.json` + `dast_report.md` + `dast_report.html` (interactive timeline with Chart.js)

### Planned providers (create config + add to Makefile):

| Provider | promptfoo target format | Env vars |
|----------|------------------------|----------|
| OpenAI (direct) | `openai:chat:gpt-4o` | OPENAI_API_KEY |
| Anthropic (direct) | `anthropic:messages:claude-opus-4-6-20250514` | ANTHROPIC_API_KEY |
| Ollama (local) | `ollama:chat:llama3.1:70b` | OLLAMA_BASE_URL |
| vLLM (internal) | `openai:chat:<model>` + OPENAI_BASE_URL | OPENAI_BASE_URL, OPENAI_API_KEY |
| NVIDIA NIM | `openai:chat:meta/llama-3.1-70b` | OPENAI_BASE_URL=https://integrate.api.nvidia.com/v1 |

Recommend mode 1 (container-based with PROVIDER preset) for quick pre-commit validation. It avoids email verification, runs inside the scanner container (no host deps), and supports Langfuse instrumentation.

### If NO providers are READY:

Report which credentials are needed and where to set them:
- For interactive use: `export AZURE_API_KEY=... AZURE_API_HOST=...` in shell
- For CI: Set as repository secrets in GitHub Actions
- For container scans: Pass via `--env` or `.env` file to Docker

Also note: offline dataset plugins (beavertails, xstest, etc.) still require a live endpoint for evaluation -- they only skip LLM-generated test prompts.

---

## Step 6: If user confirms, run the scan

If the user chooses to run a scan, execute it. Use `nohup` for long-running scans and report the log path:

```
cd scripts/release && make promptfoo-scan TARGET=<target>
```

After completion, summarize: pass rate, number of findings, severity breakdown, and which ASOPB domains are impacted.

---

## Notes

- Promptfoo findings are T3-grade adversarial evidence (highest confidence tier)
- Findings map to ASOPB domains: D4 (authorization), D5 (information disclosure)
- The scan requires a LIVE endpoint -- it sends adversarial prompts to the model
- promptfoo redteam run (cloud generation) requires email verification in v0.121.5+
- promptfoo eval with hand-crafted configs works without verification (recommended for CI)

### Baselines (42-test suite, 2026-05-26):

| Provider | Pass Rate | Key Finding |
|----------|-----------|-------------|
| Bedrock (Claude Opus) | 97.6% (41/42) | LLM07-3: system prompt JSON encoding |
| Azure (o4-mini) | 84.6% (11/13, old 13-test) | Translation+injection, deletion instruction |
| ADEPT Gateway | 85.7% (36/42) | 3 failed (content safety filter, markdown exfil, LLM10 repetition), 3 errors (400 from content filter) |

### Cross-reference report availability:

| Scan Mode | Cross-ref with Docker logs? |
|-----------|----------------------------|
| `PROVIDER=bedrock` | No (direct LLM, no stack) |
| `PROVIDER=azure` | No (direct LLM, no stack) |
| `PROVIDER=adept` via `make dast-full` | Yes (agent_gateway + orchestration_service) |
| `PROVIDER=adept` via `make dast-remote` | Yes (remote logs via SSH) |
| CI workflow | No (no ADEPT stack in CI) |
