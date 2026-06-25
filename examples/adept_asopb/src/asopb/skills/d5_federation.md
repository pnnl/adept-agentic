# D5: Federation and Trust

## Domain Overview

Domain D5 evaluates cross-facility agent federation and trust boundaries—how agents in different organizations, data centers, or security domains communicate securely. This includes agent-to-agent security (A2A), gateway trust models, session smuggling prevention, SSRF (Server-Side Request Forgery) prevention, and delegation across trust boundaries.

Secure federation ensures that:
- One agent cannot impersonate another across trust boundaries
- Cross-facility communication is authenticated and authorized
- Metadata or context cannot be smuggled across boundaries
- Agents cannot make arbitrary requests to internal services (SSRF prevention)
- Delegation across trust boundaries requires explicit approval

## Controls

| ID | Name | Description |
|----|------|-------------|
| D5.1 | A2A (Agent-to-Agent) Security | Agent-to-agent communication is authenticated and encrypted |
| D5.2 | Gateway Trust Model | Gateways validate and transform cross-boundary traffic; identity is verified at boundary |
| D5.3 | Session Smuggling Prevention | Context/session data cannot cross trust boundaries without re-authentication |
| D5.4 | SSRF Prevention | Agents cannot make arbitrary requests to internal services; request validation enforced |
| D5.5 | Cross-Facility Delegation | Delegation across trust boundaries requires explicit approval; constraints enforced |

## Tier 1 (Design) Criteria

Tier 1 credit requires evidence that the organization has:

- **D5.1**: A2A communication model documented; encryption and authentication approach defined
- **D5.2**: Gateway architecture documented; trust model defined; validation rules specified
- **D5.3**: Session/context boundary rules documented; re-authentication requirements defined
- **D5.4**: SSRF threat model documented; request validation strategy defined; URL/resource allowlist approach specified
- **D5.5**: Cross-facility delegation policy documented; approval process defined; constraint rules specified

## Tier 2 (Implementation) Criteria

Tier 2 credit requires evidence that the organization has:

- **D5.1**: A2A communication encrypted (mTLS, TLS); authentication enforced; message signing for non-repudiation
- **D5.2**: Gateway enforcing trust boundary; all cross-boundary traffic validated; identity verified; audit log of boundary crossings
- **D5.3**: Session data cleared at boundary crossing; re-authentication enforced; old session invalidated; context not propagated
- **D5.4**: Request URL validation on all outbound requests; internal IPs blocked; DNS validation; SSRF tests passing
- **D5.5**: Cross-facility delegation requires gateway approval; constraints enforced; audit log of cross-facility delegations

## Positive Patterns

Evidence that increases confidence in D5 maturity:

1. **A2A uses mTLS with certificate pinning** — Agent verifies peer certificate; MITM-resistant
2. **Gateway acts as identity transformer** — Gateway verifies source identity and re-asserts identity on behalf of source
3. **Session data cleared at boundary** — Context variables reset; session token invalidated; clean context passed
4. **Request URL validation** — Allowlist of permitted hostnames; private IPs (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) blocked
5. **DNS rebinding protection** — Gateway validates that hostname resolves to expected IP; repeated resolution checks
6. **Cross-facility delegation approval** — Delegation across boundaries requires human or automated approval
7. **Audit trail of federation** — All cross-facility communication logged with source, destination, and purpose
8. **Trust boundary enforcement** — No ambient authorization; credentials don't carry across boundaries
9. **Gateway rate limiting** — Cross-boundary requests rate-limited; burst attacks prevented
10. **Metadata stripping** — Internal headers/metadata removed before crossing boundary

## Negative Patterns

Evidence that decreases confidence in D5 maturity:

1. **A2A communication over plain HTTP** — No encryption or authentication
2. **No gateway between facilities** — Direct agent-to-agent communication across boundaries
3. **Session context propagated across boundaries** — Agent in facility A can use facility B's session tokens
4. **No request validation** — Agent can request arbitrary internal IPs/URLs
5. **DNS resolution cached** — SSRF via DNS rebinding possible (hostname resolves to internal IP)
6. **Cross-facility delegation unrestricted** — Any agent can delegate to any agent in any facility
7. **No audit log of federation** — Cross-facility communication not logged
8. **Metadata propagated across boundaries** — Internal headers (X-Internal-ID, etc.) sent to external agents
9. **No rate limiting on gateway** — Burst attacks possible
10. **Trust boundary crossing unvalidated** — Old credentials valid in new facility; no re-authentication

## Scoring Rubric

### D5.1: A2A (Agent-to-Agent) Security

| Evidence | Score |
|----------|-------|
| A2A communication over HTTP without encryption | 0 |
| A2A planned to use TLS; not yet implemented | 0.3 |
| A2A uses TLS; agent identity not validated | 0.5 |
| A2A uses TLS with certificate validation; identity verified | 0.7 |
| A2A uses mTLS with certificate pinning; message signing for non-repudiation; key rotation working | 1.0 |

### D5.2: Gateway Trust Model

| Evidence | Score |
|----------|-------|
| No gateway; direct agent-to-agent communication | 0 |
| Gateway planned; not implemented | 0.3 |
| Gateway exists; minimal validation of cross-boundary traffic | 0.5 |
| Gateway validates identity and enforces trust boundary; logs boundary crossings | 0.7 |
| Gateway acts as identity transformer; validates source, re-asserts identity, enforces audit trail; rate limiting | 1.0 |

### D5.3: Session Smuggling Prevention

| Evidence | Score |
|----------|-------|
| Session context propagated across boundaries without validation | 0 |
| Session boundary rules documented but not enforced | 0.3 |
| Session data partially cleared at boundary; old session sometimes invalidated | 0.5 |
| Session boundary enforced; old session invalidated; context reset at crossing | 0.7 |
| Strict session boundary with clean context; old session revoked; cross-boundary context rejected; audit trail | 1.0 |

### D5.4: SSRF Prevention

| Evidence | Score |
|----------|-------|
| No request validation; agent can request arbitrary IPs/URLs | 0 |
| Request validation planned; not implemented | 0.3 |
| Basic URL validation (allowlist); private IPs not blocked | 0.5 |
| URL allowlist enforced; private IPs blocked; DNS validation in place | 0.7 |
| Strict SSRF prevention with hostname allowlist, private IP blocking, DNS rebinding protection, SSRF tests > 90% passing | 1.0 |

### D5.5: Cross-Facility Delegation

| Evidence | Score |
|----------|-------|
| No approval for cross-facility delegation; unrestricted | 0 |
| Cross-facility delegation documented but not enforced | 0.3 |
| Delegation across boundaries controlled; approval not always required | 0.5 |
| Cross-facility delegation requires approval; constraints enforced; audit log | 0.7 |
| Strict cross-facility delegation control with multi-level approval, per-delegation constraints, revocation capability, audit trail | 1.0 |

## Common Pitfalls

These patterns may look like controls but are insufficient:

1. **A2A with TLS but no certificate validation** — TLS for encryption only; peer identity not verified
2. **Gateway exists but doesn't validate requests** — Gateway forwards traffic; no trust boundary enforcement
3. **Session boundary documented but not enforced** — Design says context resets at boundary; code propagates context
4. **Request validation in application only** — Validation in agent code; bypassed if agent is compromised
5. **Hostname allowlist but no DNS rebinding check** — Hostname checked once at request time; subsequent DNS lookups not validated
6. **Cross-facility delegation approval is advisory** — Approval can be logged; agent proceeds regardless
7. **Audit log of federation but not immutable** — Events logged to database; no tamper-evidence
8. **Rate limiting on gateway but no burst protection** — Rate limit allows some burst; no token bucket or backpressure

## Output Format

When evaluating this domain, respond with a JSON object following this schema:

```json
{
  "domain": "D5",
  "domain_name": "Federation and Trust",
  "controls": [
    {
      "id": "D5.1",
      "name": "A2A (Agent-to-Agent) Security",
      "tier1_score": 0.6,
      "tier2_score": 0.3,
      "evidence": "A2A communication documented to use TLS. Certificate validation not fully implemented; agent identity verification missing.",
      "findings": [
        "Positive: A2A uses TLS for encryption",
        "Negative: Peer certificate validation not enforced",
        "Negative: Agent identity verification not implemented",
        "Negative: No certificate pinning"
      ]
    },
    {
      "id": "D5.2",
      "name": "Gateway Trust Model",
      "tier1_score": 0.4,
      "tier2_score": 0.0,
      "evidence": "Gateway architecture documented but not yet deployed. Direct agent communication currently used.",
      "findings": [
        "Positive: Gateway architecture designed and documented",
        "Negative: Gateway not implemented in production",
        "Negative: Direct agent-to-agent communication used instead of gateway routing"
      ]
    },
    {
      "id": "D5.3",
      "name": "Session Smuggling Prevention",
      "tier1_score": 0.5,
      "tier2_score": 0.2,
      "evidence": "Session context documented to reset at boundaries. Implementation incomplete; some context variables propagate across facilities.",
      "findings": [
        "Positive: Session boundary rules documented",
        "Negative: Context variables sometimes propagate (e.g., agent_id, permissions)",
        "Negative: Old session token sometimes accepted in new facility"
      ]
    },
    {
      "id": "D5.4",
      "name": "SSRF Prevention",
      "tier1_score": 0.5,
      "tier2_score": 0.4,
      "evidence": "URL allowlist enforced in gateway. Private IPs (10.0.0.0/8) not blocked; DNS rebinding protection not implemented.",
      "findings": [
        "Positive: URL allowlist implemented",
        "Negative: Private IP ranges not rejected",
        "Negative: DNS rebinding attack possible (hostname checked once; subsequent resolution not re-validated)"
      ]
    },
    {
      "id": "D5.5",
      "name": "Cross-Facility Delegation",
      "tier1_score": 0.3,
      "tier2_score": 0.0,
      "evidence": "Cross-facility delegation not addressed in current design. Agents can delegate across boundaries without approval.",
      "findings": [
        "Positive: None",
        "Negative: No approval process for cross-facility delegation",
        "Negative: Delegated agent in facility B inherits facility A permissions",
        "Negative: No audit trail of cross-facility delegations"
      ]
    }
  ],
  "summary": "Federation and trust boundaries are partially designed but not fully implemented. A2A communication uses TLS but lacks identity verification. Gateway architecture is planned but not deployed. Session smuggling prevention is incomplete. SSRF prevention has gaps (private IPs, DNS rebinding). Cross-facility delegation is unenforced.",
  "recommendations": [
    "Implement gateway with trust boundary enforcement; deploy in critical paths",
    "Add peer certificate validation and pinning to A2A communication",
    "Implement strict session boundary with clean context at crossing",
    "Block private IP ranges in SSRF validation; add DNS rebinding protection",
    "Design and enforce approval process for cross-facility delegation"
  ],
  "overall_tier1": 0.46,
  "overall_tier2": 0.18,
  "risk_level": "MEDIUM-HIGH"
}
```

## Notes

- **A2A Security**: mTLS with certificate pinning is the gold standard. Agent A pins Agent B's certificate; Agent B pins Agent A's certificate. Prevents MITM and certificate-based impersonation.
- **Gateway Trust Model**: Gateway acts as a "trust boundary enforcer". Source identity is validated at entry; re-asserted on behalf of source at exit. Gateway controls which agents can communicate.
- **Session Smuggling**: Session tokens and context variables (e.g., permissions, user ID) should not carry across trust boundaries. Crossing a boundary requires re-authentication.
- **SSRF Prevention**: Common SSRF targets: 127.0.0.1 (localhost), 10.0.0.0/8 (private), 169.254.169.254 (AWS metadata). Also check: cloud metadata endpoints, Kubernetes API server, internal services.
- **DNS Rebinding**: Hostname resolves to external IP at request time; resolves to internal IP on subsequent lookup. Mitigation: validate hostname resolves to same IP on each use, or cache DNS results with short TTL.
- **Cross-Facility Delegation**: Delegation across trust boundaries should require explicit approval at the boundary. Delegated agent should inherit only specific permissions, not all permissions of delegator.
