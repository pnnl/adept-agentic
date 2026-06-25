# Versioning and Releases

## Overview

ADEPT uses Calendar Versioning (CalVer) to provide clear temporal context for each release. Two packages are published in lockstep: `agentic-framework-pkg` (platform services) and `agentic-framework-sdk` (client SDK). Their versions are always kept in sync.

## Version Scheme

The version format is:

```
MAJOR.MINOR.YYYYMMDD
```

| Component | Meaning | Example |
|-----------|---------|---------|
| MAJOR | Breaking API changes | `2.0.20260529` |
| MINOR | Feature additions (backward-compatible) | `1.1.20260529` |
| YYYYMMDD | Calendar date of the release | `1.0.20260529` |

Both packages share the same version string. A single `bumpversion` invocation updates `pyproject.toml` in both packages simultaneously.

## Release Lifecycle

The release pipeline follows a strict 9-step sequence:

1. **Version bump** -- update both packages with matching `YYYYMMDD` date.
2. **Squash-merge** -- merge the parent feature branch into `main`.
3. **Tag** -- create `v<version>` tag on the merge commit.
4. **Stage** -- run `make stage` to produce a clean release tree via `git archive` + `rsync`.
5. **ASOPB scan** -- run the 7-pass security scanner against the staged tree (Pipeline ASPI >= 95 publish gate).
6. **Dry-run** -- execute `--dry-run` publish to validate artifact structure.
7. **Publish** -- manual-only step; never automated.
8. **Tag released** -- create `released-<version>` tag after successful publish.
9. **GitHub Release** -- attach release notes and changelog.

!!! warning "Publish is never automated"
    Step 7 (Publish) requires explicit human approval. The `/prepare-release` skill walks steps 4-6 but never executes publish.

## Content Filtering

The `.publish-exclude` file contains 231 rsync exclusion rules that strip internal-only content from the staged release tree. Categories of excluded content include:

- Development documentation and session reports
- Internal deployment configurations
- Test fixtures and log files
- Credential templates and secrets infrastructure
- CI/CD pipeline definitions

The staging process uses:

```bash
git archive HEAD | tar -x -C /tmp/adept-release-stage
rsync -a --exclude-from=.publish-exclude /tmp/adept-release-stage/ /tmp/adept-release-final/
```

## ASPI Gate

Every release must pass the ASPI (Agentic Security Posture Index) gate with a composite score of **95 or higher** (Pipeline ASPI publish gate). The scan runs in an air-gapped Docker container against the staged tree -- not the working directory.

If the Pipeline ASPI score falls below 95, the release is blocked until findings are remediated or excluded via `.publish-exclude`.

## Tagging Convention

| Tag Pattern | Meaning |
|-------------|---------|
| `v1.0.20260529` | Version tag on squash-merge commit |
| `released-1.0.20260529` | Confirms successful publication |

Tags are lightweight (not annotated) and pushed to the primary remote only after all gates pass.
