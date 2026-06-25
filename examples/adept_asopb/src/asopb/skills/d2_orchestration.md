# D2: Orchestration Security

## Domain Overview

Domain D2 evaluates the security of agent orchestration—how agents are coordinated, supervised, and prevented from drift or poisoning. This includes session isolation, supervisor/worker validation, routing constraints, memory poisoning defense, and policy rollback capabilities.

Secure orchestration ensures that agents cannot break isolation, cannot be redirected to unintended targets, and cannot accumulate corrupted context that drives them off-policy.

## Controls

| ID | Name | Description |
|----|------|-------------|
| D2.1 | Session Isolation | Each agent session is logically and resource-isolated from others |
| D2.2 | Supervisor/Worker Validation | Supervisory agents can validate or veto worker agent decisions |
| D2.3 | Routing Constraints | Agents can only invoke permitted tools/services; routing is enforced |
| D2.4 | Memory Poisoning Defense | Context/memory is validated; corrupted or malicious inputs are detected |
| D2.5 | Policy Rollback | Agent policies can be reverted quickly; change audit trail maintained |

## Tier 1 (Design) Criteria

Tier 1 credit requires evidence that the organization has:

- **D2.1**: Architecture diagram showing session isolation; documented session lifecycle; segregation policy defined
- **D2.2**: Documented supervisor role; workflow showing validation gate; approval process defined
- **D2.3**: Documented routing policy (e.g., "agent X can call tools A, B, C only"); tool allowlist defined
- **D2.4**: Memory validation strategy documented; threat model for context poisoning; detection approach described
- **D2.5**: Policy change process documented; rollback procedure defined; audit requirement stated

## Tier 2 (Implementation) Criteria

Tier 2 credit requires evidence that the organization has:

- **D2.1**: Session isolation enforced in code (separate context managers, isolated storage); session keys validated; resource limits per session
- **D2.2**: Supervisor validation working in production; logs of decisions approved/rejected; validator service operational
- **D2.3**: Tool routing enforced at runtime; ACL checks in invocation path; evidence of rejected calls in logs
- **D2.4**: Memory validation filters active; suspicious inputs logged and flagged; poisoned context detection in operation
- **D2.5**: Policy versioning in code/config; rollback procedure tested; audit log of changes with timestamps and approvers

## Positive Patterns

Evidence that increases confidence in D2 maturity:

1. **Documented session model** — Clear description of session lifecycle, isolation boundaries, token refresh
2. **Supervisor oversight in production** — Logs showing supervisor approvals/rejections; supervisor error rate tracked
3. **Tool allowlist enforcement** — ACL config file; runtime checks; denied access logs
4. **Context validation on ingestion** — Input sanitization; prompt injection detection; entropy checks
5. **Rate limiting per session** — Tokens/requests throttled; burst protection
6. **Multi-agent coordination rules** — Documented handoff protocol; approved escalation paths
7. **Immutable audit log** — Session events logged with tamper-evidence (e.g., sequential IDs, signed log entries)
8. **Context freshness tracking** — Timestamps on memory; old context auto-purged; cache expiration
9. **Supervisor diversity** — Multiple supervisors can override decisions (no single point of veto)
10. **Policy change CI/CD** — Policy changes require code review and approval before deployment

## Negative Patterns

Evidence that decreases confidence in D2 maturity:

1. **No session isolation** — Sessions share context or memory; cross-session interference possible
2. **Supervisor role not enforced** — Supervisor defined in docs but no code validation
3. **No tool routing enforcement** — Agent can call any available tool without restriction
4. **Unbounded context growth** — Memory accumulates without validation or cleanup
5. **No rollback procedure** — Policy changes are one-way; no version history
6. **Single supervisor** — One person/system can approve all decisions (concentration of control)
7. **No audit trail** — Session events not logged or logs not immutable
8. **Supervisor can be bypassed** — Logic allows agent to proceed without supervisor approval
9. **Policy changes not tracked** — No record of who changed what and when
10. **Poisoned memory not detected** — Corrupted context silently propagates to downstream decisions

## Scoring Rubric

### D2.1: Session Isolation

| Evidence | Score |
|----------|-------|
| No explicit session isolation; shared context | 0 |
| Sessions documented but isolation not enforced in code | 0.3 |
| Session context isolated; some resource limits; basic separation | 0.5 |
| Session isolation enforced; session keys validated; resource limits per session | 0.7 |
| Full isolation with cross-session access prevention; token refresh enforced; resource quotas; verified separation | 1.0 |

### D2.2: Supervisor/Worker Validation

| Evidence | Score |
|----------|-------|
| No supervisor/validation workflow | 0 |
| Supervisor role defined in docs only | 0.3 |
| Supervisor role exists; some validation logic; not always enforced | 0.5 |
| Supervisor validates worker decisions; logs approvals/rejections; enforced in most paths | 0.7 |
| Supervisor oversight in all worker actions; approval required; audit trail; supervisor diversity/redundancy | 1.0 |

### D2.3: Routing Constraints

| Evidence | Score |
|----------|-------|
| No routing constraints; agents can call any tool | 0 |
| Routing policy documented but not enforced | 0.3 |
| Tool allowlist exists; enforcement in 50%+ of call sites | 0.5 |
| Tool allowlist enforced; ACL checks at invocation; denied calls logged | 0.7 |
| Strict routing enforcement; allowlist config-driven; denied calls tracked; cross-domain routing blocked | 1.0 |

### D2.4: Memory Poisoning Defense

| Evidence | Score |
|----------|-------|
| No memory validation; context accepted as-is | 0 |
| Memory validation strategy documented but not implemented | 0.3 |
| Basic context validation (format checks); some sanitization | 0.5 |
| Context validation enforced; suspicious inputs flagged; logs of validation failures | 0.7 |
| Comprehensive validation with entropy checks, prompt injection detection, reputation checks; poisoned context quarantined | 1.0 |

### D2.5: Policy Rollback

| Evidence | Score |
|----------|-------|
| No policy versioning; changes are one-way | 0 |
| Policy versioning in version control but no rollback procedure | 0.3 |
| Policy versions tracked; manual rollback documented | 0.5 |
| Automated rollback procedure; tested rollback; audit log of changes | 0.7 |
| Full policy versioning with signed changes; rollback tested in production; approval chain for changes; immutable audit trail | 1.0 |

## Common Pitfalls

These patterns may look like controls but are insufficient:

1. **Session documentation without enforcement** — Session model described in design doc; code uses global context
2. **Supervisor is logged but not required** — Supervisor can approve decisions but agent proceeds regardless of response
3. **Tool allowlist in docs only** — Policy lists permitted tools; code doesn't check at runtime
4. **Ad-hoc memory validation** — Input checked in one place but accepted without validation elsewhere
5. **Policy in version control but no rollback** — Git history exists; no automated procedure to revert to previous policy
6. **Supervisor bypass path** — Approval required for normal case but edge case allows direct execution
7. **Audit log not tamper-evident** — Events logged to file but not signed or sequenced; log could be modified
8. **Cross-session interference ignored** — Sessions documented as isolated but memory/context is actually shared

## Output Format

When evaluating this domain, respond with a JSON object following this schema:

```json
{
  "domain": "D2",
  "domain_name": "Orchestration Security",
  "controls": [
    {
      "id": "D2.1",
      "name": "Session Isolation",
      "tier1_score": 0.7,
      "tier2_score": 0.5,
      "evidence": "Session context isolated in code via separate RequestContext objects. Resource limits (token budget) enforced per session. Cross-session memory access prevented.",
      "findings": [
        "Positive: Session isolation enforced in codebase; resource quotas applied",
        "Negative: Resource limits checked in application code; no OS-level isolation (e.g., containers)"
      ]
    },
    {
      "id": "D2.2",
      "name": "Supervisor/Worker Validation",
      "tier1_score": 0.5,
      "tier2_score": 0.3,
      "evidence": "Supervisor role defined in architecture; approval workflow documented. Some logs of approval decisions.",
      "findings": [
        "Positive: Supervisor validation workflow exists",
        "Negative: Supervisor approval not enforced for all actions; some edge cases bypass validation"
      ]
    }
  ],
  "summary": "Orchestration has basic session isolation but lacks production-grade enforcement. Supervisor validation exists but is not comprehensive. Tool routing constraints are documented but not fully enforced.",
  "recommendations": [
    "Enforce supervisor approval in all worker action paths; test edge cases",
    "Implement runtime tool ACL checks; add denied-call logging",
    "Add context validation filter on all input ingestion points",
    "Implement automated policy rollback with audit trail"
  ],
  "overall_tier1": 0.55,
  "overall_tier2": 0.4
}
```

## Notes

- **Session Isolation**: Even if true OS-level isolation (containers, VMs) is not available, logical isolation with proper context management is acceptable for Tier 1/2. Full isolation requires separate processes or containers.
- **Supervisor/Worker**: Supervisor can be a service, algorithm, or human. The key is that critical decisions are validated before execution. For high-risk systems, require human supervisors.
- **Routing Constraints**: Allowlist is the standard approach. "Agent X can call tools A, B, C" is enforced via code checks or middleware.
- **Memory Poisoning**: This includes both adversarial inputs and corrupted state from previous operations. Validation includes format, entropy, and semantic checks.
- **Policy Rollback**: This should be automated and tested regularly. Manual rollback is Tier 1; automated rollback with testing is Tier 2.
