# D1: Foundation Model Integrity

## Domain Overview

Domain D1 evaluates the security and trustworthiness of the foundation models that power agentic systems. This includes vendor diversity, CBRN gating, model vetting processes, adversarial robustness, and dual-use risk assessment.

A secure agent ecosystem requires strong controls over which models can be deployed, how they're selected, and how they're protected from adversarial inputs that could cause harm.

## Controls

| ID | Name | Description |
|----|------|-------------|
| D1.1 | Vendor Neutrality (LiteLLM) | Support for multiple model vendors (Anthropic, OpenAI, Google, local) via unified API |
| D1.2 | CBRN Gating | Restrictions on model inference for Chemical, Biological, Radiological, Nuclear content |
| D1.3 | Model Vetting | Documented approval process for foundation models before deployment |
| D1.4 | Adversarial Robustness | Testing and validation against prompt injection and jailbreak attempts |
| D1.5 | Dual-Use Evaluation | Risk assessment for models that could enable harmful applications |

## Tier 1 (Design) Criteria

Tier 1 credit requires evidence that the organization has:

- **D1.1**: Documented use of a vendor-neutral LLM abstraction layer (e.g., LiteLLM, OpenAI Router) that supports at least 2 different model vendors
- **D1.2**: CBRN policy document defining which model types can/cannot be used for sensitive domains; evidence of configuration preventing CBRN inference
- **D1.3**: Written model approval checklist, documented evaluation process before deployment; evidence of baseline model vetting
- **D1.4**: Documented test suite or red-team plan for adversarial inputs; evidence of baseline jailbreak testing (even basic)
- **D1.5**: Risk assessment document for each deployed model; evidence of dual-use review before production use

## Tier 2 (Implementation) Criteria

Tier 2 credit requires evidence that the organization has:

- **D1.1**: Automated model routing/failover working in production; model vendors verified to be operational; cost tracking across vendors
- **D1.2**: Deployed content filters or model gating in runtime; evidence of CBRN rejection in logs; audit trail of CBRN policy enforcement
- **D1.3**: Model approval records; versions pinned in code/config; model updates tracked; evidence of re-vetting after model updates
- **D1.4**: Adversarial test results; evidence of passing jailbreak/prompt injection tests; fuzzing or systematic red-teaming logs
- **D1.5**: Risk register with mitigation status; evidence of model-specific safety features enabled (e.g., safety layer API); approval signatures

## Positive Patterns

Evidence that increases confidence in D1 maturity:

1. **Multiple model vendors in production** — LiteLLM config with 2+ vendors; failover working
2. **Documented model selection criteria** — Checklist including safety, cost, latency, capability fit
3. **Ongoing adversarial testing** — Regular red-team reports; automated jailbreak test suite in CI/CD
4. **Safety layer enablement** — Evidence of model-specific safety features (e.g., Anthropic safety layer, OpenAI safety features)
5. **Model version pinning** — Clear model version in code/config; hash verification or artifact signing
6. **CBRN policy in code** — Content moderation rules in configuration; reject patterns for CBRN keywords
7. **Fallback model strategy** — Secondary model defined; tested fallover path
8. **Model cost and latency monitoring** — Metrics tracking model performance across vendors
9. **Security headers/API keys** — Use of Anthropic API safety headers (detect_malicious_usage, etc.)
10. **Third-party model audits** — Evidence of using audited models (e.g., Claude 4 transparency, GPT-4 red-teaming)

## Negative Patterns

Evidence that decreases confidence in D1 maturity:

1. **Single-vendor lock-in** — Only one model vendor; no documented fallback
2. **No model vetting** — Models used directly without approval process
3. **CBRN policy absent or unenforced** — No CBRN gating; policy not validated in code
4. **No adversarial testing** — Zero evidence of red-teaming or jailbreak testing
5. **Uncontrolled model updates** — No version pinning; auto-updates without re-vetting
6. **No dual-use assessment** — Missing risk register or safety review
7. **Hardcoded API keys** — Keys in source code instead of secrets management
8. **No fallback strategy** — Single model, no redundancy
9. **Unmonitored model behavior** — No logs of CBRN rejections or safety violations
10. **Disabled safety features** — Safety layers or content filters turned off

## Scoring Rubric

### D1.1: Vendor Neutrality

| Evidence | Score |
|----------|-------|
| Single vendor, no LLM abstraction layer | 0 |
| LLM abstraction layer implemented but not used in production | 0.3 |
| 1 vendor operational via abstraction layer; documented but not tested | 0.5 |
| 2+ vendors configured, 1 actively used with fallback documented | 0.7 |
| 2+ vendors in production with tested failover; cost tracking | 1.0 |

### D1.2: CBRN Gating

| Evidence | Score |
|----------|-------|
| No CBRN policy or controls | 0 |
| CBRN policy document only (not implemented) | 0.3 |
| CBRN policy documented and partially enforced (e.g., manual review) | 0.5 |
| CBRN filter deployed; some validation in logs | 0.7 |
| CBRN filter automated and enforced; audit trail of rejections; tested | 1.0 |

### D1.3: Model Vetting

| Evidence | Score |
|----------|-------|
| No model selection process; models used ad-hoc | 0 |
| Model selection documented but not enforced | 0.3 |
| Model vetting checklist; versions pinned in config | 0.5 |
| Models approved and pinned; approval records kept; minor updates tracked | 0.7 |
| Formal approval process with sign-off; model inventory; re-vetting on updates; hashes verified | 1.0 |

### D1.4: Adversarial Robustness

| Evidence | Score |
|----------|-------|
| No adversarial testing | 0 |
| Adversarial testing planned but not executed | 0.3 |
| Basic jailbreak test attempt (manual); some results documented | 0.5 |
| Regular adversarial testing; test results in CI/CD; some test automation | 0.7 |
| Comprehensive red-teaming; fuzzing suite; prompt injection tests; jailbreak attempts logged; passing > 80% | 1.0 |

### D1.5: Dual-Use Evaluation

| Evidence | Score |
|----------|-------|
| No dual-use assessment; no risk register | 0 |
| Risk assessment document drafted but not validated | 0.3 |
| Risk register for deployed models; assessment of 50%+ models | 0.5 |
| Risk assessment for all models; mitigation plan for high-risk; some safety features enabled | 0.7 |
| Complete risk register with sign-off; all models assessed; mitigations implemented; evidence of safety layer use; approval records | 1.0 |

## Common Pitfalls

These patterns may look like controls but are insufficient:

1. **LLM abstraction layer exists but not used** — Code uses vendor SDKs directly instead of abstraction layer
2. **CBRN policy in documentation only** — Written policy with no code enforcement; no audit trail
3. **Vetting of only the initial model** — Model re-vetted only after major version bumps, not patch updates
4. **Single adversarial test** — One red-team report from external consultant; no ongoing testing
5. **Safety features documented but disabled** — Code comments reference safety features that are commented out
6. **Risk register without mitigations** — Risk document identifies dual-use concerns but no actions taken
7. **Model pinning without hash verification** — Version pinned in code but no cryptographic verification
8. **Fallback model not tested** — Fallback model defined in config but never validated to work

## Output Format

When evaluating this domain, respond with a JSON object following this schema:

```json
{
  "domain": "D1",
  "domain_name": "Foundation Model Integrity",
  "controls": [
    {
      "id": "D1.1",
      "name": "Vendor Neutrality (LiteLLM)",
      "tier1_score": 0.5,
      "tier2_score": 0.0,
      "evidence": "Uses LiteLLM abstraction layer with Claude and GPT-4 configured. Fallback not tested in production.",
      "findings": [
        "Positive: LiteLLM integrated in codebase",
        "Negative: Single vendor actively used; no production failover test"
      ]
    },
    {
      "id": "D1.2",
      "name": "CBRN Gating",
      "tier1_score": 0.3,
      "tier2_score": 0.0,
      "evidence": "CBRN policy document exists but no code enforcement.",
      "findings": [
        "Positive: Written policy for CBRN restrictions",
        "Negative: No runtime filter; no audit trail of rejections"
      ]
    }
  ],
  "summary": "Foundation model management is documented at design level but lacks production enforcement. Vendor diversity is configured but not actively used. CBRN restrictions exist in policy but are not implemented in code.",
  "recommendations": [
    "Test multi-vendor failover in staging environment",
    "Implement runtime CBRN content filter with logging",
    "Document and execute monthly adversarial testing plan",
    "Create and sign-off formal model approval checklist"
  ],
  "overall_tier1": 0.35,
  "overall_tier2": 0.0
}
```

## Notes

- **Vendor Neutrality**: LiteLLM and similar abstraction layers are the de facto standard for avoiding single-vendor lock-in. Accept equivalents (e.g., AWS Bedrock API, Azure OpenAI router) if they support 2+ vendors.
- **CBRN Gating**: This is critical for regulated deployments. "CBRN" refers to Chemical, Biological, Radiological, Nuclear content. Gating means refusing inference requests that match CBRN patterns or use models that can't be restricted.
- **Model Vetting**: Even simple checklist (capability, cost, safety) is better than none. Require documentation, not just oral tradition.
- **Adversarial Robustness**: Classic jailbreak attempts (e.g., "act as an evil AI", "ignore instructions") count; fuzzing is better; ongoing testing is best.
- **Dual-Use**: Models like those that can write code can be misused for malware, SQL injection, etc. Assessment doesn't need to be exhaustive, but must be documented.
