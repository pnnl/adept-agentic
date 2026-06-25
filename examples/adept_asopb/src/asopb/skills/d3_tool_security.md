# D3: Tool and MCP Security

## Domain Overview

Domain D3 evaluates the security of tools and Model Context Protocol (MCP) integrations—how tools are provisioned, isolated, and protected from misuse. This includes tool access control lists (ACLs), sandbox isolation, MCP supply chain security, command injection prevention, and pre-execution analysis.

Secure tool integration ensures that agents cannot escalate privileges, execute unintended commands, access unauthorized resources, or use tools to pivot to other systems.

## Controls

| ID | Name | Description |
|----|------|-------------|
| D3.1 | Tool ACLs | Each tool has defined access control; only authorized agents can invoke |
| D3.2 | Sandbox Isolation | Tools execute in isolated environments; resource and capability constraints |
| D3.3 | MCP Supply Chain | MCP servers are vetted; code reviewed; dependencies audited |
| D3.4 | Command Injection Prevention | User input is validated and escaped; static analysis checks |
| D3.5 | Pre-Execution Analysis | Tool invocations are analyzed for safety before execution |

## Tier 1 (Design) Criteria

Tier 1 credit requires evidence that the organization has:

- **D3.1**: Tool ACL matrix documented; mapping of agents to permitted tools defined
- **D3.2**: Sandbox architecture described (e.g., containers, seccomp, capability dropping); isolation goals stated
- **D3.3**: MCP server vetting checklist; code review process for MCP servers documented
- **D3.4**: Input validation strategy documented; command injection threat model; escaping approach defined
- **D3.5**: Pre-execution analysis approach described (static analysis, semantic checks, reputation checks)

## Tier 2 (Implementation) Criteria

Tier 2 credit requires evidence that the organization has:

- **D3.1**: Tool ACL enforced at runtime; invocation checks verify agent permissions; denied invocations logged
- **D3.2**: Sandbox execution working in production; resource limits enforced; capability restrictions applied; escape attempts logged
- **D3.3**: MCP servers code-reviewed before deployment; dependencies pinned; vulnerability scanning in CI/CD
- **D3.4**: Input validation in place; command injection tests passing; static analysis (e.g., Semgrep, Bandit) running in CI/CD
- **D3.5**: Pre-execution analysis running on all tool invocations; blocked invocations logged with reason; analysis latency monitored

## Positive Patterns

Evidence that increases confidence in D3 maturity:

1. **Tool ACL matrix in code** — Config file mapping agents to tools; runtime enforcement
2. **Separate tool execution user/process** — Tools run as non-root, restricted user account
3. **Container-based sandboxing** — Each tool invocation in isolated container; resource limits applied
4. **Input validation framework** — Central validation library for all tool inputs; no raw shell commands
5. **Shellcode/payload detection** — Static analysis (Semgrep, Bandit) finding injection patterns
6. **MCP server approval workflow** — Sign-off required before new MCP server deployment
7. **Dependency lock files** — requirements.txt with pinned versions; hash verification (Poetry, pip-compile)
8. **Command whitelist** — Allowed commands enumerated; others rejected at invocation time
9. **Execution audit trail** — All tool invocations logged with: who (agent), what (tool, params), when, result, any errors
10. **Capability dropping** — Seccomp, SELinux, or AppArmor profiles removing unnecessary syscalls

## Negative Patterns

Evidence that decreases confidence in D3 maturity:

1. **No tool ACLs** — Any agent can invoke any tool
2. **Tools run as root** — Privilege escalation risk if tool is compromised
3. **Raw shell commands** — User input passed directly to shell() or exec()
4. **No input validation** — Parameters accepted without sanitization
5. **MCP servers not reviewed** — External MCP code used without code review
6. **No dependency pinning** — Dependency versions not locked; auto-updates possible
7. **No pre-execution analysis** — Invocations executed immediately without safety check
8. **Audit log not tamper-evident** — Tool invocations logged but logs not immutable
9. **No sandbox isolation** — Tools execute in main agent process; no resource limits
10. **Disabled security features** — Sandbox or validation disabled in production for performance

## Scoring Rubric

### D3.1: Tool ACLs

| Evidence | Score |
|----------|-------|
| No tool ACLs; any agent can invoke any tool | 0 |
| ACL matrix documented but not enforced | 0.3 |
| Tool ACLs exist; enforcement in 50%+ of invocation paths | 0.5 |
| Tool ACLs enforced at runtime; denied invocations logged | 0.7 |
| Strict ACL enforcement; all invocations checked; detailed audit log; ACL updates require approval | 1.0 |

### D3.2: Sandbox Isolation

| Evidence | Score |
|----------|-------|
| No sandbox; tools run in main process | 0 |
| Sandbox architecture planned; not implemented | 0.3 |
| Basic process isolation (separate user account); some resource limits | 0.5 |
| Container or VM sandboxing; resource limits enforced (CPU, memory, disk); capability dropping | 0.7 |
| Full sandboxing with containers and seccomp; resource quotas enforced; escape attempts logged; regular testing | 1.0 |

### D3.3: MCP Supply Chain

| Evidence | Score |
|----------|-------|
| MCP servers used without review | 0 |
| MCP server list maintained; informal code review | 0.3 |
| MCP servers code-reviewed; basic dependency checks | 0.5 |
| MCP servers formally approved; dependencies pinned; vulnerability scanning in CI/CD | 0.7 |
| MCP server approval with sign-off; dependency lock files; SCA (Snyk, Dependabot) scans; attestation | 1.0 |

### D3.4: Command Injection Prevention

| Evidence | Score |
|----------|-------|
| Raw user input to shell; no validation | 0 |
| Input validation planned; not implemented | 0.3 |
| Basic input filtering (length, character set); some shell escaping | 0.5 |
| Input validation framework in place; all parameters validated; static analysis (Semgrep, Bandit) checks | 0.7 |
| Comprehensive validation with parameterized commands (no string concatenation); static analysis passing; fuzz testing; injection tests > 90% passing | 1.0 |

### D3.5: Pre-Execution Analysis

| Evidence | Score |
|----------|-------|
| No pre-execution analysis; invocations executed immediately | 0 |
| Pre-execution analysis planned but not implemented | 0.3 |
| Basic safety checks (e.g., parameter bounds); some invocations analyzed | 0.5 |
| Pre-execution analysis on all invocations; blocked invocations logged; latency < 100ms | 0.7 |
| Comprehensive analysis (semantic, reputation, capability checks) on all invocations; blocked reasons logged; latency optimized; tested with adversarial invocations | 1.0 |

## Common Pitfalls

These patterns may look like controls but are insufficient:

1. **ACL matrix in docs but not code** — Spreadsheet shows tool permissions; code doesn't enforce
2. **Tool inputs validated in one place only** — Validation in HTTP layer but not in tool execution layer
3. **Sandbox not resource-constrained** — Tools run in separate container but no CPU/memory limits
4. **MCP code review but no dependency audit** — Server code is reviewed; dependencies are not
5. **Dependency pinning without hash verification** — Version is pinned; package source not verified
6. **Pre-execution analysis is advisory only** — Warnings logged but invocation proceeds anyway
7. **Audit log kept but not immutable** — Events logged to database; no tamper-evidence (e.g., Merkle chain)
8. **Tool execution as root** — Sandbox exists but process runs as root; no privilege dropping

## Output Format

When evaluating this domain, respond with a JSON object following this schema:

```json
{
  "domain": "D3",
  "domain_name": "Tool and MCP Security",
  "controls": [
    {
      "id": "D3.1",
      "name": "Tool ACLs",
      "tier1_score": 0.5,
      "tier2_score": 0.3,
      "evidence": "Tool ACL matrix exists in design docs. Partial enforcement in code; missing checks in webhook handlers.",
      "findings": [
        "Positive: ACL matrix documented and referenced in code",
        "Negative: Enforcement not comprehensive; edge cases bypass ACL checks"
      ]
    },
    {
      "id": "D3.2",
      "name": "Sandbox Isolation",
      "tier1_score": 0.7,
      "tier2_score": 0.5,
      "evidence": "Tools execute in Docker containers with resource limits (CPU 100m, memory 256Mi). Seccomp profile not yet applied.",
      "findings": [
        "Positive: Container-based sandboxing; resource limits enforced",
        "Negative: Capability dropping (seccomp) not yet implemented; escape testing not documented"
      ]
    }
  ],
  "summary": "Tool security is partially implemented. ACLs are documented but enforcement is incomplete. Sandboxing via containers is in place with resource limits, but capability-level restriction is missing. Input validation and pre-execution analysis need strengthening.",
  "recommendations": [
    "Enforce tool ACLs at all invocation points; audit missing checks",
    "Deploy Semgrep and Bandit in CI/CD to detect injection patterns",
    "Apply seccomp profiles to container sandbox",
    "Implement pre-execution analysis for all tool invocations with logging"
  ],
  "overall_tier1": 0.6,
  "overall_tier2": 0.4
}
```

## Notes

- **Tool ACLs**: ACL can be role-based (agent role determines which tools) or explicit (agent ID mapped to tools). Either approach is acceptable.
- **Sandbox Isolation**: Containers (Docker, Podman) are the standard for sandbox isolation in agentic systems. Seccomp profiles further restrict the syscall surface.
- **MCP Supply Chain**: MCP servers are executable code; they must be reviewed before use. Equivalent to code review for any dependency.
- **Command Injection**: Parameterized commands (e.g., subprocess.run([cmd, arg1, arg2])) are safe; string concatenation (f"{cmd} {arg}") is dangerous.
- **Pre-Execution Analysis**: Can be rule-based (static checks), ML-based (anomaly detection), or human approval. Latency < 100ms is acceptable for most use cases.
