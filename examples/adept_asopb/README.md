# ASOPB: Agentic Security and Operations Performance Benchmark

A comprehensive, extensible evaluation framework for assessing the security posture and operational resilience of agentic AI platforms. ASOPB provides deterministic control assessment coupled with LLM-driven analysis across eight security domains (D1-D8), producing a weighted Agentic Security Posture Index (ASPI) and detailed evidence bundles suitable for regulatory compliance and longitudinal tracking.

[![PyPI Version](https://img.shields.io/pypi/v/asopb.svg)](https://pypi.org/project/asopb/)
[![License: BSD-2-Clause](https://img.shields.io/badge/license-BSD--2--Clause-blue.svg)](https://opensource.org/licenses/BSD-2-Clause)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org)

## TL;DR

Run a comprehensive security evaluation on an agentic system:

```bash
pip install asopb[analyzers]
asopb evaluate /path/to/framework --config asopb.yaml --output results/
```

This produces:
- A JSON report with ASPI score (0-100) and per-domain breakdowns
- Evidence bundles showing scanner findings, LLM assessments, and red-team results
- Markdown and HTML exports for stakeholder communication
- SQLite evidence store for longitudinal analysis

## What ASOPB Measures

ASOPB evaluates agentic systems across **8 security domains**, each assessed at three evidence tiers (T1 Design, T2 Implementation, T3 Adversarial):

| Domain | Description | Weight | Key Controls |
|--------|-------------|--------|--------------|
| **D1: Foundation Model Integrity** | Verification that the underlying model is uncompromised, maintained, and conforms to specs | 1.5 | Model provenance, version management, capability inventory |
| **D2: Inference Integrity** | Input/output validation and determinism assurance | 1.5 | Input sanitization, output filtering, reproducibility |
| **D3: Agent Instruction Integrity** | System prompt immutability and injection resistance | 1.2 | Instruction immutability, version control, user override prevention |
| **D4: Agent Identity & Authentication** | Cryptographic identity verification and access control | 1.3 | Identity attestation, user authentication, authorization/RBAC |
| **D5: Information Disclosure Control** | PII filtering, secure logging, model fingerprinting resistance | 1.2 | PII detection, secure logging, anti-fingerprinting |
| **D6: External Tool Integration Safety** | Tool inventory, sandboxing, result validation | 1.0 | Tool inventory, access control, result validation |
| **D7: Compliance & Ethical Constraints** | Harmful content prevention, bias monitoring, regulatory compliance | 1.0 | Harmful content prevention, fairness monitoring, GDPR/data residency |
| **D8: Operational Monitoring & Incident Response** | Anomaly detection, security logging, incident response plans | 1.1 | Anomaly detection, event logging, incident response plan |

### Evidence Tiers (T1, T2, T3)

- **T1 (Design)**: Architectural design evidence, policies, and documentation
- **T2 (Implementation)**: Deployed runtime controls, automation, and verification mechanisms
- **T3 (Adversarial)**: Red-team exercises, attack simulations, and adversarial validation

Control scores on each tier (0-10) combine into a composite score (0-100) based on the rubric defined in `controls.yaml`.

## Architecture

ASOPB uses a **three-layer evaluation pipeline**:

```
Repository/Framework
         |
         v
    [Scanner Layer]
    (gitxray, auth patterns, static files)
         |
         v
    [Analyzer Layer]
    (Semgrep, Bandit, pip-audit, etc.)
         |
         v
   [Domain Evaluator Layer]
    (LLM skill-driven assessment,
     red-team result synthesis,
     evidence aggregation)
         |
         v
    [ASPI Calculator]
    (Weighted domain scores -> 0-100)
         |
         v
   EvaluationReport
   (JSON + evidence bundle)
```

Each layer produces `ScanResult` and `ControlEvidence` objects that flow through the evidence store (SQLite with CRC hashing) for integrity verification and version tracking.

## Installation

### Standard Install
```bash
pip install asopb
```

### With Analyzers
Includes external tools (Semgrep, Bandit, pip-audit):
```bash
pip install asopb[analyzers]
```

### From Source (with `uv`)
```bash
git clone https://github.com/pnnl/adept-agentic.git
cd asopb
uv sync
uv run asopb --version
```

### Optional: Specific Analyzers
```bash
pip install asopb[gitxray,semgrep,bandit]
```

## Quick Start

### 1. Full Evaluation with Custom Config
```bash
asopb evaluate /path/to/framework \
  --config asopb.yaml \
  --output results/ \
  --format json
```

### 2. Quick Scan (Scanners Only)
```bash
asopb scan /path/to/framework --output scan_results/
```

### 3. Evaluate Single Domain
```bash
asopb evaluate /path/to/framework \
  --domains D1,D4 \
  --skip-llm \
  --output results/
```

### 4. Compare Two Reports
```bash
asopb compare results/report_v1.json results/report_v2.json --format text
```

## Python API

Use ASOPB programmatically in Python:

```python
import asyncio
from pathlib import Path
from asopb import Evaluator, EvalConfig, LLMConfig

async def main():
    # Configure evaluation
    config = EvalConfig(
        llm=LLMConfig(
            model="claude-sonnet-4-20250514",
            temperature=0.1,
        ),
        output_dir=Path("./results"),
        verbose=True,
    )

    # Create evaluator
    evaluator = Evaluator(config=config)

    # Run evaluation
    report = await evaluator.evaluate("/path/to/framework")

    # Access results
    print(f"ASPI: {report.aspi}")
    for domain_id, domain in report.domains.items():
        print(f"{domain_id}: {domain.domain_score}")

    # Export evidence bundle
    bundle_dir = report.to_evidence_bundle(Path("./bundles"))
    print(f"Evidence bundle: {bundle_dir}")

asyncio.run(main())
```

### Common Operations

```python
# Skip LLM scoring (deterministic only)
config.skip_llm = True

# Use specific analyzers
config.analyzers.enabled = ["semgrep", "bandit"]

# Override LLM model
config.llm.model = "gpt-4o"

# Set stage hint for applicability
config.scoring.stage_hint = "S3"  # S1, S2, S3, or S4

# Load custom controls
config.scoring.custom_controls_path = Path("./custom_controls.yaml")

# Load red-team reports
config.red_team.report_paths = [Path("./red_team_results.json")]
```

## Configuration

Create an `asopb.yaml` file to configure the evaluation:

```yaml
# LLM Configuration
llm:
  model: "claude-sonnet-4-20250514"      # Primary model
  fallback_model: "gpt-4o"                # Fallback if primary unavailable
  temperature: 0.1                        # Low temp for consistency
  max_tokens: 4096
  rate_limit_rpm: 30
  timeout_seconds: 120
  cache_enabled: true                     # Cache LLM responses
  cache_dir: null                         # null = default location

# Analyzer Configuration
analyzers:
  enabled:
    - gitxray
    - semgrep
    - bandit
    - pip_audit
    - dockerfile
    - tls
  disabled: []
  timeout_seconds: 300
  semgrep_rules: null                     # Custom Semgrep ruleset
  bandit_config: null                     # Custom Bandit config

# Scoring Configuration
scoring:
  domain_weights:
    D1: 1.5  # Foundation Model Integrity
    D2: 1.5  # Inference Integrity
    D3: 1.2  # Agent Instruction Integrity
    D4: 1.3  # Identity & Authentication
    D5: 1.2  # Information Disclosure
    D6: 1.0  # Tool Integration Safety
    D7: 1.0  # Compliance & Ethics
    D8: 1.1  # Monitoring & Incident Response
  custom_controls_path: null              # Merge with built-in controls
  domains_to_evaluate: null               # null = all applicable
  stage_hint: null                        # S1, S2, S3, or S4

# Evidence Store Configuration
evidence_store:
  enabled: true
  db_path: ./asopb_evidence.db            # null = in-memory
  auto_commit: true

# Red-Team Configuration
red_team:
  report_paths: []                        # Pre-existing red-team reports
  simulator_plugins: []                   # Custom attack simulators
  simulator_timeout_seconds: 600

# Global Settings
skip_llm: false                           # Run deterministic-only
verbose: false
max_concurrency: 8
output_dir: ./asopb_output
framework_name: null                      # Auto-detected
framework_version: null                   # Auto-detected
```

Load configuration from file:

```python
from asopb import EvalConfig
config = EvalConfig.from_yaml(Path("asopb.yaml"))
```

## Custom Controls

ASOPB is extensible via YAML-driven custom controls (STIG-style). Supplement or override built-in controls:

```yaml
# custom_controls.yaml
asopb_version: "1.0.0"

domains:
  D1:
    controls:
      - id: "D1.4"
        name: "Custom model attestation"
        description: "Your organization-specific requirement"
        severity: "high"
        applicable_stages: ["S2", "S3", "S4"]
        t1_criteria:
          - "Attestation schema documented"
        t2_criteria:
          - "Attestation deployed and verified"
        t3_criteria:
          - "Attestation bypass testing"
        nist_mapping: ["SI-7"]
        owasp_mapping: []
        tags: ["custom"]

  D4:
    controls:
      - id: "D4.4"
        name: "MFA for agent deployment"
        description: "Require multi-factor approval for model rollout"
        severity: "high"
        applicable_stages: ["S3", "S4"]
        t1_criteria:
          - "MFA policy documented"
        t2_criteria:
          - "MFA enforced in deployment pipeline"
        t3_criteria:
          - "MFA bypass testing"
        nist_mapping: ["AC-2", "IA-2"]
        tags: ["custom", "deployment"]
```

Load custom controls:

```python
config.scoring.custom_controls_path = Path("custom_controls.yaml")
```

Controls are merged with built-in controls; custom controls override built-in ones with the same `control_id`.

## Red-Team Plugin Architecture

Extend ASOPB with custom attack simulators via the factory pattern. Plugins implement the `RedTeamPlugin` base class:

```python
# my_plugin.py
from asopb.red_team import RedTeamPlugin
from asopb.models import RedTeamReport, RedTeamScenario

class MyCustomAttackSimulator(RedTeamPlugin):
    """Custom attack simulator plugin."""

    name = "my_custom_simulator"
    description = "Simulates custom attack vectors"

    async def run(self, framework_path: Path, config: EvalConfig) -> RedTeamReport:
        """Run attack simulation and return results."""
        scenarios = []

        # Define attack scenarios
        scenario = RedTeamScenario(
            scenario_id="CUSTOM-1",
            scenario_name="Custom attack vector",
            attack_vector="Description of the attack",
            target_domain="D3",
            target_controls=["D3.1", "D3.3"],
            outcome="defense_held",  # or "partial_bypass", "full_bypass"
            outcome_description="System successfully defended against this attack",
            severity="high",
            t3_score_contribution=2.0,  # Points deducted if defense failed
        )
        scenarios.append(scenario)

        return RedTeamReport(
            report_id=f"rt-{self.name}",
            source=self.name,
            framework_version=config.framework_version,
            scenarios=scenarios,
        )
```

Register via entry point in `pyproject.toml`:

```toml
[project.entry-points."asopb.red_team_plugins"]
my_simulator = "my_plugin:MyCustomAttackSimulator"
```

Load plugin:

```python
config.red_team.simulator_plugins = ["my_plugin"]
```

## CLI Reference

### evaluate
Run a comprehensive evaluation on a framework.

```bash
asopb evaluate REPO_PATH [OPTIONS]

Options:
  --config, -c PATH           Path to asopb.yaml config file
  --model, -m MODEL           Override LLM model (e.g., gpt-4o)
  --output, -o PATH           Output directory for reports
  --format, -f FORMAT         Output format: json|markdown|html (default: json)
  --domains, -d DOMAINS       Comma-separated domain IDs (e.g., D1,D3,D5)
  --skip-llm                  Skip LLM-assisted scoring
  --skip-analyzers            Skip external analyzers
  --verbose, -v               Enable verbose logging
  --stage-hint STAGE          S1, S2, S3, or S4 (applicability hint)
  --custom-controls PATH      Path to custom controls YAML
```

### scan
Quick scan with scanners only (no LLM, no analyzers).

```bash
asopb scan REPO_PATH [OPTIONS]

Options:
  --output, -o PATH           Output directory
  --verbose, -v               Enable verbose logging
```

### tools
List available analyzers and their installation status.

```bash
asopb tools
```

### compare
Compare two evaluation reports and show the delta.

```bash
asopb compare REPORT_A REPORT_B [OPTIONS]

Options:
  --format, -f FORMAT         text|json (default: text)
```

### validate
Validate report integrity and evidence store consistency.

```bash
asopb validate REPORT_JSON
```

### init
Create a default `asopb.yaml` configuration file.

```bash
asopb init [OPTIONS]

Options:
  --path, -p PATH             Output path (default: ./asopb.yaml)
```

## Output Formats

### JSON
Complete machine-readable evaluation report with all evidence:

```bash
asopb evaluate /path --format json --output results/
# Produces: results/asopb-YYYYMMDD-HHMMSS.json
```

Structure includes:
- `report_id`, `framework`, `timestamp`, `asopb_version`
- `domains`: Per-domain results with control scores and evidence
- `scan_results`, `analyzer_results`: Raw tool findings
- `red_team_reports`: Red-team exercise results
- `aspi`: Weighted aggregate security posture index
- `config_snapshot`: Configuration used for evaluation

### Markdown
Human-readable report suitable for documentation:

```bash
asopb evaluate /path --format markdown --output results/
# Produces: results/asopb-YYYYMMDD-HHMMSS.md
```

Includes:
- Executive summary with ASPI score
- Domain-level tables and narrative summaries
- Control details with evidence references
- Remediation recommendations

### HTML
Interactive browser-viewable report:

```bash
asopb evaluate /path --format html --output results/
# Produces: results/asopb-YYYYMMDD-HHMMSS.html
```

Features:
- Styled tables and charts
- Evidence bundle links
- Responsive design
- Embeddable in dashboards

### Evidence Bundles
Self-contained directory with all evidence artifacts:

```
asopb-20250329-143025/
├── report.json                 # Main report
├── evidence/
│   ├── D1.json                 # Domain-specific evidence
│   ├── D2.json
│   └── ...
├── scans/
│   ├── semgrep.json            # Scanner/analyzer raw output
│   ├── bandit.json
│   └── ...
└── red_team/
    └── rt-20250329-custom.json # Red-team scenarios
```

Export programmatically:

```python
bundle_dir = report.to_evidence_bundle(Path("./bundles"))
```

## Evidence Store

ASOPB maintains a SQLite evidence store for integrity verification and longitudinal analysis.

### Database Schema

Tables:
- `control_evidence`: All evidence pieces collected, deduplicated by evidence_hash (SHA-256)
- `evaluation_snapshots`: Per-framework-version snapshots with timestamps
- `version_deltas`: Diff tracking between framework versions

### CRC Hashing & Integrity

Each evidence piece is hashed for:
- Deduplication: Identical evidence not stored twice
- Integrity verification: Tamper detection
- Change tracking: Version delta queries

```python
from asopb import EvidenceStore

store = EvidenceStore(db_path=Path("asopb_evidence.db"))

# Query version delta
deltas = store.query_version_deltas(
    version_a="myframework:v1.0.0",
    version_b="myframework:v1.0.1",
)
for delta in deltas:
    print(f"Evidence changed: {delta.control_id}")
```

### Version Tracking

Reports are automatically tagged with framework version metadata:

```python
from asopb.models import FrameworkVersion

version = FrameworkVersion(
    name="myframework",
    version="1.0.0",
    git_commit="abc123...",
    git_branch="main",
    git_tag="v1.0.0",
    snapshot_date=datetime.now(),
    source_url="https://github.com/...",
    source_hash="sha256:...",
)
```

Use `version_key` for deterministic lookups:

```python
version_key = version.version_key  # "myframework:abc123" or "myframework:1.0.0"
```

## Relationship to SaTML Paper

This implementation operationalizes the ASOPB benchmark from the SoK paper "Security and Operations Performance of Agentic AI Platforms" (SaTML, to appear). The framework bridges the gap from theoretical evaluation criteria to practical, automated assessment suitable for continuous integration and compliance workflows.

Key alignment:
- **8 domains** map to the threat model and control categories in the paper
- **T1/T2/T3 tiers** implement the evidence hierarchy (design → implementation → adversarial)
- **Deterministic floor + LLM ceiling** reflects the paper's scoring methodology
- **Evidence bundles** support the reproducibility requirements in the benchmark

## Scanner Manifest (Container Deployment)

When ASOPB runs inside the `adept-release-scanner` Docker image, a **scanner manifest**
(`scanner_manifest.json`) declares the blessed versions of all tools and packages. A
pre-scan self-test (`scanner_selftest.py`) validates the runtime environment against this
manifest before any evaluation begins.

The manifest tracks:
- External binaries (grype, trivy, trufflehog, promptfoo, semgrep)
- Python packages (bandit, pip-audit, gitxray, asopb, vulture, detect-secrets, ...)
- Config files (.grype.yaml, .trivyignore)
- All scanner/pipeline scripts
- Egress policy (air-gap enforcement, blessed LLM endpoints for red-team pass)

The self-test gates the pipeline: if critical checks fail (missing binaries, broken imports,
evaluator still has stubs), the pipeline exits before scanning.

For details on maintaining the manifest, see `scripts/release/README.md`.

## Contributing

We welcome contributions! See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for:
- Development setup
- How to add scanners, analyzers, domain evaluators
- LLM skill development
- Red-team plugin authoring
- Testing requirements

## License

ASOPB is licensed under the BSD 2-Clause License. See [LICENSE](LICENSE) for details.

## Citation

If you use ASOPB in research or production, please cite:

```bibtex
@inproceedings{asopb2025,
  title={{ASOPB}: {A}gentic {S}ecurity and {O}perations {P}erformance {B}enchmark},
  author={ASOPB Contributors},
  booktitle={Security and Privacy of Machine Learning (SaTML)},
  year={2026},
  note={Available at https://github.com/pnnl/adept-agentic}
}
```

## Support

- GitHub Issues: https://github.com/pnnl/adept-agentic/issues
- Documentation: https://github.com/pnnl/adept-agentic#readme
- Security Report: See SECURITY.md
