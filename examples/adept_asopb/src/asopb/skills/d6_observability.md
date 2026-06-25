# D6: Observability and Audit

## Domain Overview

Domain D6 evaluates observability and audit logging—whether the organization can see what agents are doing, understand decision paths, track resource usage, and maintain compliance evidence. This includes chain-of-thought (CoT) logging, glass-box tracing, cost tracking, structured event logging, and compliance evidence collection.

Secure observability ensures that:
- Agent decision paths are auditable (CoT, reasoning traces)
- All agent actions are logged with context and metadata
- System behavior can be understood post-incident
- Compliance requirements (GDPR, SOC2, HIPAA) can be demonstrated
- Cost attribution is accurate
- Audit logs are tamper-resistant

## Controls

| ID | Name | Description |
|----|------|-------------|
| D6.1 | Glass-Box Tracing | Agent reasoning and decision paths are logged in detail (CoT, intermediate steps) |
| D6.2 | Structured Event Logging | All agent actions logged with standardized schema; queryable and immutable |
| D6.3 | Cost and Usage Tracking | API calls, tokens, and resource usage tracked; cost attribution accurate |
| D6.4 | Langfuse/OpenTelemetry Integration | Third-party observability platforms (Langfuse, OpenTelemetry) integrated |
| D6.5 | Compliance Evidence | Audit logs support compliance claims (GDPR, SOC2, HIPAA); retention policies enforced |

## Tier 1 (Design) Criteria

Tier 1 credit requires evidence that the organization has:

- **D6.1**: CoT logging strategy documented; agent reasoning capture approach defined; trace storage defined
- **D6.2**: Event logging schema documented (who, what, when, where, why); storage backend defined; immutability requirements stated
- **D6.3**: Cost tracking approach documented; token counting strategy defined; cost attribution model specified
- **D6.4**: Langfuse or OpenTelemetry integration approach documented; instrumentation points identified
- **D6.5**: Compliance requirements identified; retention policies documented; audit capabilities described

## Tier 2 (Implementation) Criteria

Tier 2 credit requires evidence that the organization has:

- **D6.1**: CoT logging implemented in code; agent reasoning captured; traces stored and queryable
- **D6.2**: Structured logging enforced in code; all agent actions logged; immutable storage; queryable
- **D6.3**: Token counting working; cost attributed to requests/agents; cost reports generated
- **D6.4**: Langfuse/OpenTelemetry integration working; traces visible in platform; performance metadata collected
- **D6.5**: Audit logs stored with retention policy; compliance evidence can be extracted; audit trail covers all critical actions

## Positive Patterns

Evidence that increases confidence in D6 maturity:

1. **CoT captured in production logs** — Agent reasoning steps logged; visible in log aggregation platform
2. **Structured logging with JSON schema** — Log entries include: agent_id, action, result, timestamp, cost, metadata
3. **Immutable audit log** — Logs stored with tamper-detection (Merkle chain, signed entries, write-once storage)
4. **Distributed tracing** — Request traces include all agent steps, tool invocations, LLM calls; queryable by trace ID
5. **Cost tracking per agent/request** — Token counts, API costs attributed accurately; cost reports available
6. **Langfuse or OpenTelemetry working** — Traces visible in external platform; performance metrics available
7. **Retention policy enforced** — Logs not deleted before retention period; old logs archived
8. **Queryable audit trail** — Can search by agent_id, action, timestamp; results show full context
9. **PII redaction** — Sensitive data redacted from logs before storage; compliance data available
10. **Cost attribution by service** — Can break down costs by agent, model, tool, time period

## Negative Patterns

Evidence that decreases confidence in D6 maturity:

1. **No CoT logging** — Agent reasoning not captured; decisions unexplainable
2. **Unstructured logs** — Free-form text logs; no schema; not queryable
3. **Mutable audit log** — Logs stored in database that can be edited; no tamper detection
4. **No cost tracking** — No visibility into API costs; cost attribution impossible
5. **No distributed tracing** — Request trace doesn't span all components; missing visibility
6. **Langfuse/OpenTelemetry not used** — External observability platform not integrated
7. **No retention policy** — Logs deleted arbitrarily; no archive
8. **PII in logs** — Sensitive data stored unredacted; compliance risk
9. **Log aggregation not working** — Logs generated but not collected; scattered across systems
10. **No cost reports** — Cost data collected but not analyzed; cannot explain spending

## Scoring Rubric

### D6.1: Glass-Box Tracing

| Evidence | Score |
|----------|-------|
| No CoT logging; agent reasoning not captured | 0 |
| CoT logging planned; not implemented | 0.3 |
| CoT logging in development; some reasoning steps captured | 0.5 |
| CoT logging in production; agent reasoning captured and queryable | 0.7 |
| Full CoT logging with distributed tracing; reasoning traces stored; traces indexed and searchable; performance metadata | 1.0 |

### D6.2: Structured Event Logging

| Evidence | Score |
|----------|-------|
| Unstructured logs; no schema | 0 |
| Structured logging planned; not implemented | 0.3 |
| Some structured logs; inconsistent schema; not all actions logged | 0.5 |
| Structured logging enforced; consistent schema; all actions logged; queryable | 0.7 |
| Full structured logging with immutable storage, tamper-detection, indexing, search capability, PII redaction | 1.0 |

### D6.3: Cost and Usage Tracking

| Evidence | Score |
|----------|-------|
| No cost tracking; no visibility into API usage | 0 |
| Cost tracking planned; not implemented | 0.3 |
| Token counting in place; cost attribution incomplete or inaccurate | 0.5 |
| Cost tracking working; token counts accurate; cost attribution per request | 0.7 |
| Full cost tracking with per-agent/per-model attribution, cost reports, budget alerts, cost optimization analysis | 1.0 |

### D6.4: Langfuse/OpenTelemetry Integration

| Evidence | Score |
|----------|-------|
| No external observability platform used | 0 |
| Langfuse/OpenTelemetry planned; not integrated | 0.3 |
| Integration in progress; partial coverage of agent traces | 0.5 |
| Langfuse/OpenTelemetry integrated; agent traces visible in platform | 0.7 |
| Full integration with distributed tracing, performance metrics, cost tracking, custom events, alerts working | 1.0 |

### D6.5: Compliance Evidence

| Evidence | Score |
|----------|-------|
| No compliance logging; cannot demonstrate controls | 0 |
| Compliance requirements identified; logging not addressed | 0.3 |
| Compliance logging planned; some logs captured | 0.5 |
| Compliance logs captured; retention policy enforced; evidence extractable | 0.7 |
| Full compliance evidence with retention policy, audit trail, PII handling, compliance reports, signed audit logs | 1.0 |

## Common Pitfalls

These patterns may look like controls but are insufficient:

1. **CoT logging in development only** — Reasoning captured in dev logs; disabled in production for performance
2. **Structured logging in application code only** — Logs structured at application level; not enforced in all layers
3. **Cost tracking collected but not attributed** — Token counts recorded; no mapping to agents/requests/models
4. **Langfuse integration but traces incomplete** — External platform integrated; traces don't span all components
5. **Audit logs stored but not immutable** — Logs stored in mutable database; no tamper-detection
6. **Retention policy documented but not enforced** — Policy exists; old logs not actually deleted/archived
7. **PII redaction documented but not enforced** — Plan to redact sensitive data; logs contain PII unredacted
8. **Cost reports generated but not actionable** — Reports exist; no clear cost attribution; cannot explain variance

## Output Format

When evaluating this domain, respond with a JSON object following this schema:

```json
{
  "domain": "D6",
  "domain_name": "Observability and Audit",
  "controls": [
    {
      "id": "D6.1",
      "name": "Glass-Box Tracing",
      "tier1_score": 0.6,
      "tier2_score": 0.4,
      "evidence": "CoT logging implemented; agent reasoning steps captured in logs. Traces not yet queryable; stored as plain text files.",
      "findings": [
        "Positive: Agent reasoning captured in logs",
        "Positive: CoT logging in production",
        "Negative: Traces stored as plain text; not indexed or queryable",
        "Negative: No distributed tracing; missing some steps"
      ]
    },
    {
      "id": "D6.2",
      "name": "Structured Event Logging",
      "tier1_score": 0.7,
      "tier2_score": 0.5,
      "evidence": "Structured logging implemented with JSON schema. All agent actions logged with: agent_id, action, timestamp, result.",
      "findings": [
        "Positive: Structured JSON logging enforced",
        "Positive: Consistent schema across logs",
        "Negative: Logs stored in mutable database; no tamper-detection",
        "Negative: PII sometimes present in logs (not redacted)"
      ]
    },
    {
      "id": "D6.3",
      "name": "Cost and Usage Tracking",
      "tier1_score": 0.5,
      "tier2_score": 0.3,
      "evidence": "Token counting implemented. Cost tracking per API call. Cost attribution to agents incomplete.",
      "findings": [
        "Positive: Token counts accurate",
        "Positive: API costs tracked",
        "Negative: No aggregation by agent; cannot break down costs by who spent what"
      ]
    }
  ],
  "summary": "Observability is partially implemented. CoT logging captures agent reasoning, but traces are not queryable. Structured logging is enforced with consistent schema. Cost tracking exists but lacks per-agent attribution. External platforms not yet integrated.",
  "recommendations": [
    "Index and make CoT traces queryable (ELK, Splunk, or similar)",
    "Add tamper-detection to audit logs (Merkle chain or signed entries)",
    "Implement cost attribution by agent and model",
    "Integrate with Langfuse or OpenTelemetry for distributed tracing",
    "Enforce PII redaction in all logging paths"
  ],
  "overall_tier1": 0.6,
  "overall_tier2": 0.4
}
```

## Notes

- **Glass-Box Tracing**: CoT (chain-of-thought) logging should capture intermediate reasoning steps. For LLM calls, log the reasoning trace (if available). For tool invocations, log the inputs and outputs. This enables post-incident analysis.
- **Structured Logging**: JSON schema is the standard. Each log entry should include: timestamp, agent_id, action, result, cost (tokens), metadata (request_id, trace_id, etc.).
- **Cost and Usage Tracking**: Track at multiple levels: (1) per API call (model, tokens), (2) per agent (cumulative cost), (3) per request (end-to-end cost). Attribute to cost center or business unit.
- **Langfuse/OpenTelemetry**: Langfuse is agent-specific observability; OpenTelemetry is distributed tracing standard. Either or both can be used.
- **Compliance Evidence**: Audit logs should cover: authentication events, authorization decisions (delegation), sensitive operations (data access, deletion), configuration changes. Retention: 1-7 years depending on regulation.
- **Immutable Audit Log**: Write-once storage (e.g., S3 with object lock) or cryptographic signing (Merkle chain, sequential log with hash chaining) prevents tampering.
