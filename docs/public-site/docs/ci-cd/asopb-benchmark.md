# ASOPB Benchmark

## Overview

The **Agentic Security & Operations Performance Benchmark (ASOPB)** is a security evaluation framework purpose-built for agentic AI systems. It assesses release artifacts across 8 security domains and produces a composite score (ASPI) that gates publication.

ASOPB scans run in an **air-gapped Docker container** with no network access, ensuring that sensitive findings cannot be exfiltrated during evaluation.

## Security Domains

| Domain | ID | Focus Area |
|--------|----|------------|
| Model Integrity | D1 | Model provenance, weight tampering, poisoning indicators |
| Orchestration | D2 | Agent control flow, prompt injection resistance, state isolation |
| Tool Security | D3 | Tool registration validation, sandbox enforcement, ACL coverage |
| Identity | D4 | Authentication strength, credential hygiene, token lifecycle |
| Federation | D5 | Inter-agent trust, A2A credential management, mesh security |
| Observability | D6 | Audit completeness, log integrity, anomaly detection coverage |
| IT/OT Boundary | D7 | Network segmentation, privileged operation controls, HPC isolation |
| Supply Chain | D8 | Dependency provenance, container image lineage, secret exposure |

## ASPI Scoring

Each domain receives an individual score using a logarithmic penalty model:

```
domain_score = max(0, 100 - SUM(weight * ln(1 + count)))
```

Where:

- `weight` is the severity multiplier for the finding category (critical=40, high=20, medium=10, low=5)
- `count` is the number of findings in that category
- `ln` is the natural logarithm, providing diminishing marginal penalty

The **composite ASPI score** is a weighted average of the three most impactful domains:

```
ASPI = D5 * 0.4 + D8 * 0.4 + D7 * 0.2
```

!!! note "Domain weighting rationale"
    Federation (D5) and Supply Chain (D8) receive higher weight because compromises in these domains have the widest blast radius in distributed agentic systems.

## Stage Classification

| Stage | ASPI Range | Classification | Release Eligible |
|-------|-----------|----------------|-----------------|
| S4 | >= 90 | Hardened | Yes |
| S3 | 70 - 89 | Managed | No (requires remediation) |
| S2 | 50 - 69 | Developing | No |
| S1 | < 50 | Initial | No |

Only **S4 (Hardened)** artifacts may proceed to the publish step.

## Scan Pipeline

The scanner executes a 7-pass pipeline, each pass targeting a distinct finding category:

| Pass | Tool | Target |
|------|------|--------|
| P0 | Custom regex patterns | Hardcoded secrets, API keys, tokens |
| P1 | detect-secrets | Entropy-based secret detection |
| P1.5 | TruffleHog | Git history and verified credential scanning |
| P2 | NER/PII detector | Personal identifiable information, named entities |
| P3 | Toxicity classifier | Offensive content, unsafe language |
| P4 | Grype | Container image vulnerability scanning |
| P5 | Promptfoo | Adversarial LLM red-teaming (dynamic, optional) |

!!! info "Static vs. dynamic passes"
    Passes P0-P4 are static analysis (run against source artifacts). Pass P5 (Promptfoo) is dynamic -- it probes a live LLM endpoint and is invoked separately via the `--promptfoo-target` flag.

## Integration with CI/CD

The ASOPB scan integrates into the release lifecycle at step 5:

```bash
# Stage the release tree
make stage

# Run the full static scan (passes P0-P4)
make scan-release

# Check the ASPI score
# If ASPI >= 90: proceed to dry-run
# If ASPI < 90: remediate findings or update .publish-exclude
```

The scanner produces structured JSON output with per-domain scores, individual findings with file paths and line numbers, and the composite ASPI score. CI workflows parse this output to enforce the gate automatically.
