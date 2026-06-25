# D4: Identity and Authentication

## Domain Overview

Domain D4 evaluates the security of agent identity and authentication—how agents are identified, authenticated, and authorized. This is the most critical domain. It covers agent identity binding, workload identity (JWKS, mTLS, service accounts), delegation chains, session validation, and replay prevention.

Secure identity ensures that:
- Only legitimate agents can authenticate
- An agent cannot impersonate another agent
- Delegation chains have clear authorization path
- Session tokens cannot be replayed
- Identity is cryptographically bound to the agent's code/configuration

## Controls

| ID | Name | Description |
|----|------|-------------|
| D4.1 | Agent Identity Binding | Agent identity is cryptographically bound to code/config/key material |
| D4.2 | Workload Identity (JWKS/mTLS) | Agent authenticates via workload credentials (JWT, mTLS cert, service account) |
| D4.3 | Delegation Chains | Multi-level delegation has clear authorization path; no elevation without approval |
| D4.4 | Session Validation | Session tokens are cryptographically validated; no replay or token reuse |
| D4.5 | mTLS Federation | Mutual TLS with client certificates; certificate pinning; revocation checking |

## Tier 1 (Design) Criteria

Tier 1 credit requires evidence that the organization has:

- **D4.1**: Architecture document defining agent identity model (e.g., agent public key, UUID, code hash); identity bootstrap process documented
- **D4.2**: Workload identity approach defined (JWT, mTLS cert, or service account); JWKS endpoint or certificate store documented
- **D4.3**: Delegation model documented; approval chain for elevation defined; constraint rules defined
- **D4.4**: Session token format specified (JWT, encrypted cookie, opaque handle); validation rules documented; token lifetime defined
- **D4.5**: mTLS requirements specified; certificate issuing authority defined; revocation approach documented

## Tier 2 (Implementation) Criteria

Tier 2 credit requires evidence that the organization has:

- **D4.1**: Agent identity binding enforced in code; identity verified at bootstrap; code hash or signature verification working
- **D4.2**: Workload identity operational; agents authenticating via credentials; credential rotation working; secrets not in code
- **D4.3**: Delegation enforcement in code; approval checks enforced; delegation limits enforced; audit log of delegations
- **D4.4**: Session validation in all request paths; token expiration enforced; token refresh working; replay detection active
- **D4.5**: mTLS enforced in production; certificates issued and rotated; certificate pinning implemented; CRL/OCSP checking working

## Positive Patterns

Evidence that increases confidence in D4 maturity:

1. **Agent code hash in identity** — Agent identity includes sha256(code); identity changes when code changes
2. **JWKS endpoint operational** — Public keys published; agents fetch keys for verification; key rotation working
3. **Workload identity (not user passwords)** — Agents authenticate via service account, JWT, or mTLS; no API keys in code
4. **JWT with short expiration** — Token lifetime < 1 hour; refresh token for renewal; expiration enforced
5. **Delegation approval logging** — Each delegation requires approval; approval recorded with approver ID and timestamp
6. **Certificate pinning** — Client pins expected certificate; MITM-resistant
7. **Session token is opaque** — Token is not self-describing; validation requires server state (resistant to tampering)
8. **Credential rotation enforced** — Secrets rotated automatically (e.g., every 90 days); old credentials revoked
9. **No hardcoded secrets** — Credentials loaded from secrets management system (Vault, AWS Secrets Manager, etc.)
10. **Multi-factor for delegation** — Delegation requires approval + MFA or dual-approval from different identities

## Negative Patterns

Evidence that decreases confidence in D4 maturity:

1. **No agent identity** — Agents identified only by IP address or HTTP header
2. **Agent identity not cryptographically bound** — Identity is static string with no cryptographic binding
3. **API keys in code** — Credentials hardcoded in source repo
4. **Long-lived tokens** — Session tokens valid for weeks or months
5. **No delegation approval** — One agent can delegate to another without authorization
6. **Delegation without limits** — Delegated agent inherits full permissions (can re-delegate infinitely)
7. **No token expiration** — Session tokens never expire
8. **Self-describing tokens** — JWT contains all authorization info; no server-side validation
9. **No certificate pinning** — Client accepts any certificate signed by trusted CA (vulnerable to MITM)
10. **No credential rotation** — Secrets never changed; old credentials remain valid indefinitely

## Scoring Rubric

### D4.1: Agent Identity Binding

| Evidence | Score |
|----------|-------|
| No cryptographic identity binding; agent ID is static string | 0 |
| Agent identity documented but not cryptographically bound | 0.3 |
| Identity includes code hash or signing key; binding not fully enforced | 0.5 |
| Agent identity cryptographically bound to code/config; identity verified at startup; binding enforced | 0.7 |
| Identity includes code hash, config hash, and signing key; cryptographic verification required; identity rotation audited | 1.0 |

### D4.2: Workload Identity (JWKS/mTLS)

| Evidence | Score |
|----------|-------|
| Agents authenticate via API key or password | 0 |
| Workload identity approach planned; credentials still in code | 0.3 |
| Workload credentials (JWT, mTLS cert) used; not rotated or inconsistently enforced | 0.5 |
| Workload identity operational; credentials rotated; secrets management in place | 0.7 |
| Full workload identity with credential rotation, JWKS endpoint, audit of credential usage; secrets never in code | 1.0 |

### D4.3: Delegation Chains

| Evidence | Score |
|----------|-------|
| No delegation control; any agent can delegate to any other | 0 |
| Delegation documented but not enforced | 0.3 |
| Delegation validation in code; some delegation limits; approval not enforced | 0.5 |
| Delegation approval required; constraints enforced; audit log of delegations | 0.7 |
| Strict delegation control with multi-level approval; delegation limits per level; re-delegation prevented; audit trail | 1.0 |

### D4.4: Session Validation

| Evidence | Score |
|----------|-------|
| Session tokens not validated; no expiration | 0 |
| Session validation planned; not implemented | 0.3 |
| Session tokens validated; expiration enforced; token refresh not working | 0.5 |
| Session tokens validated on all requests; expiration enforced; refresh working; no token reuse | 0.7 |
| Opaque session tokens with server-side validation; short lifetime (< 1 hour); secure refresh; replay detection; revocation lists | 1.0 |

### D4.5: mTLS Federation

| Evidence | Score |
|----------|-------|
| No mTLS; plain HTTP or unvalidated TLS | 0 |
| mTLS planned; certificates not yet deployed | 0.3 |
| mTLS enforced; certificates issued; pinning not implemented | 0.5 |
| mTLS with certificate pinning; certificate rotation tested; CRL/OCSP checking in place | 0.7 |
| Full mTLS federation with certificate pinning, automated rotation, CRL/OCSP, revocation audit, cross-facility mTLS | 1.0 |

## Common Pitfalls

These patterns may look like controls but are insufficient:

1. **Agent identity is UUID only** — UUID is random; no cryptographic binding to code or config
2. **Workload credentials documented but not enforced** — Design specifies JWKS; code still uses API keys
3. **JWT signed but not verified** — Token is JWT; signature verification not performed by server
4. **Delegation documented but not enforced in code** — Design says "agent X can delegate to Y"; no code check
5. **Session tokens are JWTs with all claims** — Token contains authorization info; no server-side validation needed (vulnerable to tampering)
6. **Certificate pinning in comments** — Code comments say "pin certificate"; pinning not actually implemented
7. **Credential rotation documented but not automated** — Process requires manual action; no CI/CD integration
8. **Approval for delegation is advisory** — Delegation approval can be logged; agent proceeds regardless of response

## Output Format

When evaluating this domain, respond with a JSON object following this schema:

```json
{
  "domain": "D4",
  "domain_name": "Identity and Authentication",
  "controls": [
    {
      "id": "D4.1",
      "name": "Agent Identity Binding",
      "tier1_score": 0.7,
      "tier2_score": 0.5,
      "evidence": "Agent identity includes UUID and code hash. Identity stored in agent config and verified at startup. Code hash not updated automatically on code change.",
      "findings": [
        "Positive: Identity includes cryptographic binding (code hash)",
        "Positive: Identity verified at bootstrap time",
        "Negative: Code hash verification requires manual update when code changes",
        "Negative: No continuous identity validation during runtime"
      ]
    },
    {
      "id": "D4.2",
      "name": "Workload Identity (JWKS/mTLS)",
      "tier1_score": 0.5,
      "tier2_score": 0.2,
      "evidence": "Agent uses JWT signed with private key. JWT contains agent ID, expiration. JWKS endpoint not implemented; public key distribution not automated.",
      "findings": [
        "Positive: Agent authenticates with JWT (workload identity)",
        "Negative: JWKS endpoint not implemented; public key distribution manual",
        "Negative: JWT not rotated; signing key never changed",
        "Negative: Private key stored in agent config (not in secrets manager)"
      ]
    },
    {
      "id": "D4.3",
      "name": "Delegation Chains",
      "tier1_score": 0.3,
      "tier2_score": 0.0,
      "evidence": "Delegation model documented but not enforced in code. No approval required for delegation.",
      "findings": [
        "Positive: Delegation model defined in architecture doc",
        "Negative: No delegation approval enforcement",
        "Negative: No delegation limits enforced",
        "Negative: Delegated agent inherits all permissions without constraints"
      ]
    },
    {
      "id": "D4.4",
      "name": "Session Validation",
      "tier1_score": 0.6,
      "tier2_score": 0.4,
      "evidence": "Session tokens are JWTs with 24-hour expiration. Token validation checks signature and expiration on each request. Token refresh not implemented.",
      "findings": [
        "Positive: Session tokens validated with expiration check",
        "Negative: JWT is self-describing (contains full claims); no server-side state validation",
        "Negative: 24-hour expiration is too long (should be < 1 hour)",
        "Negative: No token refresh mechanism; users must re-authenticate after expiration"
      ]
    },
    {
      "id": "D4.5",
      "name": "mTLS Federation",
      "tier1_score": 0.4,
      "tier2_score": 0.0,
      "evidence": "mTLS between services is planned but not yet implemented. TLS is enforced but not mutual.",
      "findings": [
        "Positive: TLS required between services",
        "Negative: Server does not require or validate client certificates",
        "Negative: Certificate pinning not implemented",
        "Negative: No revocation checking (CRL/OCSP)"
      ]
    }
  ],
  "summary": "Identity and authentication are partially implemented. Agent identity is documented and includes code hash binding, but enforcement is incomplete. Workload identity via JWT is used but lacks automated key distribution (JWKS). Delegation is not enforced. Session validation exists but uses long-lived JWT tokens. mTLS is not yet implemented.",
  "recommendations": [
    "Implement JWKS endpoint for public key distribution and rotation",
    "Enforce delegation approval in code; require MFA for elevation",
    "Reduce session token lifetime to < 1 hour; implement token refresh",
    "Implement opaque session tokens with server-side validation store",
    "Deploy mTLS with certificate pinning and CRL/OCSP validation",
    "Automate credential rotation (keys, certificates) every 90 days",
    "Add continuous identity validation during runtime (re-verify code hash periodically)"
  ],
  "overall_tier1": 0.5,
  "overall_tier2": 0.22,
  "risk_level": "HIGH",
  "risk_notes": "Agent identity is not strongly bound; delegation is unenforced; session tokens are too long-lived. Recommend priority fixes: JWKS endpoint, delegation enforcement, session token lifetime reduction."
}
```

## Notes

- **Agent Identity Binding**: The gold standard is: `identity = sha256(code) | sha256(config) | public_key`. Changes to code or config invalidate the identity (requiring re-approval).
- **Workload Identity**: JWKS (JSON Web Key Set) is the standard for publishing public keys. Equivalent to a certificate store. Agents fetch keys from JWKS endpoint to verify peer JWTs.
- **Delegation Chains**: A delegates to B; B can delegate to C. Each level should have constraints (e.g., B can only delegate read permissions, not write). Infinite re-delegation is a security anti-pattern.
- **Session Validation**: Opaque tokens (not JWTs) are more secure because they require server-side validation. Self-describing tokens (JWTs with all claims) are convenient but vulnerable to tampering if signature is not verified.
- **mTLS Federation**: Mutual TLS (client cert + server cert) prevents MITM attacks. Certificate pinning (client expects specific server cert) prevents issuance-based MITM. CRL/OCSP prevents use of revoked certificates.
- **Tier 1 vs Tier 2**: Tier 1 is design-level (documented, some code checks). Tier 2 is production-enforced (all code paths validated, audit trails, secrets management).
