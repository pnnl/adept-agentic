# D8: Ecosystem and Supply Chain

## Domain Overview

Domain D8 evaluates supply chain security and ecosystem trust—how agents and their dependencies are sourced, verified, and kept secure. This includes MCP registry security, ML-BOM (Bill of Materials), dependency pinning, lock files, attestation, vendor-neutral routing, and secure package distribution.

Secure supply chain ensures that:
- Agent code and dependencies come from trusted sources
- Dependency versions are pinned and verified
- Software Bill of Materials (SBOM) is available and trackable
- No unauthorized code changes between build and deployment
- Security patches are applied promptly
- Single-vendor lock-in is avoided

## Controls

| ID | Name | Description |
|----|------|-------------|
| D8.1 | Registry Security | MCP and package registries require authentication; packages signed; registry itself is protected |
| D8.2 | ML-BOM (Software Bill of Materials) | Complete inventory of agent code, models, and dependencies; vulnerability tracking enabled |
| D8.3 | Dependency Pinning and Lock Files | Dependencies locked to specific versions; hash verification enforced |
| D8.4 | Attestation and Provenance | Build artifacts signed; provenance recorded; deployment validates signatures |
| D8.5 | Vendor-Neutral Supply Chain | Multiple vendors for critical services; no single-vendor lock-in; compatible substitutes documented |

## Tier 1 (Design) Criteria

Tier 1 credit requires evidence that the organization has:

- **D8.1**: Registry security model documented; authentication requirements specified; package signing approach defined
- **D8.2**: ML-BOM format chosen (SBOM, SPDX, CycloneDX); inventory process documented; vulnerability scanning approach specified
- **D8.3**: Dependency pinning strategy documented; lock file format chosen (requirements.txt, Poetry.lock, Pipfile.lock); hash verification approach defined
- **D8.4**: Build artifact signing approach documented (code signing, container image signing); provenance tracking mechanism specified
- **D8.5**: Vendor-neutral strategy for critical services documented; alternative vendors identified; switching procedure defined

## Tier 2 (Implementation) Criteria

Tier 2 credit requires evidence that the organization has:

- **D8.1**: Package registry authentication enforced; package signatures verified; registry infrastructure secured
- **D8.2**: ML-BOM generated and maintained; vulnerability scanner integrated in CI/CD; SBOM available for deployments
- **D8.3**: Lock files enforced; dependencies pinned with hashes; hash verification in build/deployment; no floating versions
- **D8.4**: Build artifacts signed; signature verification enforced at deployment; provenance records available; audit trail maintained
- **D8.5**: Multiple vendors operational; failover tested; vendor switching documented and verified

## Positive Patterns

Evidence that increases confidence in D8 maturity:

1. **Package registry requires API key** — Public registries (npm, PyPI) have authentication gate
2. **Package signatures enforced** — Downloaded packages verified against publisher signature
3. **SBOM in standard format** — SBOM (SPDX, CycloneDX) generated; available with deployment
4. **Vulnerability scanning in CI/CD** — SCA (Software Composition Analysis) tool scanning dependencies; CVEs blocked or flagged
5. **Dependencies pinned with hashes** — requirements.txt or Poetry.lock specifies exact version + hash
6. **Build artifacts signed** — Container images or binaries signed with private key; signature published
7. **Signed commits** — Code commits signed by developers; commit signatures verified
8. **Supply chain levels for software (SLSA)** — Build process meets SLSA levels 1-4; provenance recorded
9. **Dependency update automation** — Renovate or Dependabot scanning for updates; automated tests before merge
10. **Multiple model vendors** — Agent code doesn't depend on single LLM vendor; alternatives documented and tested

## Negative Patterns

Evidence that decreases confidence in D8 maturity:

1. **No registry authentication** — Public package registry used without authentication
2. **Package signatures not verified** — Packages downloaded but signatures not checked
3. **No SBOM** — No inventory of dependencies; cannot list what's deployed
4. **No vulnerability scanning** — Dependencies not scanned for known CVEs
5. **Floating dependency versions** — requirements.txt uses "requests>=2.0" without pinning exact version
6. **Build artifacts not signed** — Containers or binaries deployed without cryptographic signature
7. **Unsigned commits** — Code commits merged without signature verification
8. **No provenance tracking** — Cannot verify build origin or history
9. **Single model vendor** — Agent code tightly coupled to one LLM vendor; switching not feasible
10. **No dependency update process** — Old packages with CVEs remain in use indefinitely

## Scoring Rubric

### D8.1: Registry Security

| Evidence | Score |
|----------|-------|
| Public registries used without authentication; packages not verified | 0 |
| Registry security planned; authentication not yet implemented | 0.3 |
| Private registry or authentication in place; package signatures not verified | 0.5 |
| Registry authentication enforced; package signatures verified on pull | 0.7 |
| Private registry with authentication, signed packages, rate limiting, audit log, malware scanning | 1.0 |

### D8.2: ML-BOM (Software Bill of Materials)

| Evidence | Score |
|----------|-------|
| No SBOM; dependency inventory not maintained | 0 |
| SBOM planned; not implemented | 0.3 |
| SBOM created manually; not integrated in CI/CD; incomplete | 0.5 |
| SBOM generated automatically; includes code, models, dependencies; vulnerability scanner integrated | 0.7 |
| Comprehensive SBOM (SPDX, CycloneDX) generated; vulnerability tracking, license compliance, deployment manifest | 1.0 |

### D8.3: Dependency Pinning and Lock Files

| Evidence | Score |
|----------|-------|
| Floating versions; no lock file | 0 |
| Lock file exists but not enforced; can be overridden | 0.3 |
| Lock file enforced for some dependencies; hashes not verified | 0.5 |
| Lock file enforced; all dependencies pinned with hashes; hash verification in CI/CD | 0.7 |
| Strict lock file enforcement with hash verification, no floating versions, automated lock file updates, CVE scanning | 1.0 |

### D8.4: Attestation and Provenance

| Evidence | Score |
|----------|-------|
| No build artifact signing; no provenance tracking | 0 |
| Build signing planned; not implemented | 0.3 |
| Build artifacts signed; signatures not verified at deployment | 0.5 |
| Build artifacts signed; signature verification enforced; basic provenance recorded | 0.7 |
| Full attestation with signed builds, SLSA provenance, signature verification, audit trail, chain of custody | 1.0 |

### D8.5: Vendor-Neutral Supply Chain

| Evidence | Score |
|----------|-------|
| Single vendor for critical services; lock-in exists | 0 |
| Vendor diversity planned; implementation incomplete | 0.3 |
| Multiple vendors available; switching not tested | 0.5 |
| Multiple vendors operational; switching procedure documented and tested | 0.7 |
| Full vendor neutrality with multiple vendors, tested failover, documented compatibility, no lock-in | 1.0 |

## Common Pitfalls

These patterns may look like controls but are insufficient:

1. **Registry authentication exists but not enforced** — Registry requires login; build scripts sometimes bypass authentication
2. **SBOM created but not maintained** — SBOM generated once; not updated with dependency changes
3. **Lock file exists but floating versions in code** — Poetry.lock enforced; code also has "pip install requests" without pinning
4. **Build artifacts signed but signatures not verified** — Artifacts signed at build time; deployment doesn't check signatures
5. **Vendor diversity on paper only** — Alternative vendors listed in docs; not tested; switching not feasible
6. **Vulnerability scanner runs but results ignored** — SCA tool detects CVEs; build doesn't fail; old packages deployed
7. **SLSA claims without evidence** — Build claims SLSA level 3; provenance not actually recorded
8. **Dependency updates automated but untested** — Renovabot creates PRs; no automated tests run before merge

## Output Format

When evaluating this domain, respond with a JSON object following this schema:

```json
{
  "domain": "D8",
  "domain_name": "Ecosystem and Supply Chain",
  "controls": [
    {
      "id": "D8.1",
      "name": "Registry Security",
      "tier1_score": 0.5,
      "tier2_score": 0.3,
      "evidence": "Private PyPI registry set up with authentication required. Package signatures not yet verified.",
      "findings": [
        "Positive: Private registry with authentication gate",
        "Negative: Package signatures not verified on installation",
        "Negative: No malware scanning in registry"
      ]
    },
    {
      "id": "D8.2",
      "name": "ML-BOM (Software Bill of Materials)",
      "tier1_score": 0.4,
      "tier2_score": 0.2,
      "evidence": "SBOM created manually for deployment. Not automatically generated. Incomplete (missing model versions).",
      "findings": [
        "Positive: SBOM exists in some form",
        "Negative: Manual SBOM creation; easy to become stale",
        "Negative: Model versions not tracked in SBOM",
        "Negative: Vulnerability scanning not integrated"
      ]
    },
    {
      "id": "D8.3",
      "name": "Dependency Pinning and Lock Files",
      "tier1_score": 0.6,
      "tier2_score": 0.5,
      "evidence": "Poetry.lock enforced in production. Some dependencies use floating versions in poetry.toml. Hash verification not yet implemented.",
      "findings": [
        "Positive: Poetry.lock enforced; pins specific versions",
        "Negative: Some floating version specs remain (e.g., 'requests>=2.25')",
        "Negative: Hash verification not enforced"
      ]
    },
    {
      "id": "D8.4",
      "name": "Attestation and Provenance",
      "tier1_score": 0.3,
      "tier2_score": 0.0,
      "evidence": "Build artifacts not signed. No provenance tracking. Container images pushed to registry without signature.",
      "findings": [
        "Positive: None",
        "Negative: Container images not signed",
        "Negative: No provenance records; cannot verify build origin",
        "Negative: Deployment doesn't verify artifact integrity"
      ]
    },
    {
      "id": "D8.5",
      "name": "Vendor-Neutral Supply Chain",
      "tier1_score": 0.5,
      "tier2_score": 0.2,
      "evidence": "LiteLLM supports multiple model vendors (Claude, GPT-4). Failover not tested; switching manual process.",
      "findings": [
        "Positive: LiteLLM abstraction supports multiple vendors",
        "Negative: No active failover testing",
        "Negative: Switching procedure not documented",
        "Negative: Data exchange lock-in (models trained on vendor-specific data)"
      ]
    }
  ],
  "summary": "Supply chain security is partially implemented. Private registry with authentication is in place but package signatures not verified. SBOM is created manually and incomplete. Dependency pinning via Poetry.lock is enforced. Build artifact signing and provenance tracking are missing. Vendor diversity is supported via LiteLLM but not actively tested.",
  "recommendations": [
    "Enable package signature verification on all registry pulls",
    "Automate SBOM generation; include model and dependency versions",
    "Implement container image signing with Cosign or similar",
    "Set up and test vendor failover procedure (e.g., switch from Claude to GPT-4 model)",
    "Integrate vulnerability scanner (Snyk, Trivy) in CI/CD; fail builds on critical CVEs",
    "Record build provenance (SLSA level 3+); sign build artifacts"
  ],
  "overall_tier1": 0.46,
  "overall_tier2": 0.24
}
```

## Notes

- **Registry Security**: Use private registries for sensitive code (e.g., internal PyPI). Enforce authentication and package signing. Monitor registry for suspicious uploads.
- **ML-BOM**: Include code repositories, pinned model versions (e.g., "Claude 3 Sonnet v2024-06-05"), dependency versions, and licenses. Use standard format (SPDX, CycloneDX) for automated processing.
- **Dependency Pinning**: Floating versions (e.g., "2.x") allow patch updates but are unpredictable. Pin exact versions + hashes for reproducibility. Use Renovate/Dependabot for automated updates with testing.
- **Attestation**: Use tools like Cosign (container images), sigstore (code signing), or custom signing for build artifacts. Record provenance (SLSA) to prove artifact lineage.
- **Vendor Neutrality**: Use abstraction layers (LiteLLM) for models. Test vendor switching regularly. Document API compatibility and data format differences.
- **SLSA Provenance**: Levels 0-4, with 4 being fully reproducible builds with signed provenance. Level 3 (unsigned provenance in build logs) is practical for most organizations.
