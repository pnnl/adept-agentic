# Code Review Process

## Overview

ADEPT uses a structured review process combining automated analysis with human judgment. All changes flow through pull requests with required checks before merge.

## Creating PRs

Pull requests are created using the GitHub CLI with a standardized format:

```bash
gh pr create --title "feat(scope): short description" --body "$(cat <<'EOF'
## Summary
- Primary change description
- Secondary change if applicable

## Test plan
- [ ] Unit tests pass
- [ ] E2E validation target succeeds
- [ ] No regression in existing tests
EOF
)"
```

!!! tip "PR title conventions"
    Keep titles under 70 characters. Use Conventional Commit format (`type(scope): description`). Put details in the body, not the title.

## Review Process

Every PR goes through the following stages:

1. **CI checks** -- lint, unit tests, and ASOPB scan run automatically.
2. **Automated review** -- Copilot analyzes the diff for common issues.
3. **Human review** -- a maintainer reviews architecture, correctness, and completeness.
4. **Approval** -- at least one approving review is required before merge.

## Finding Classification

Review findings are categorized by severity:

| Classification | Meaning | Action Required |
|---------------|---------|-----------------|
| SECURITY | Potential vulnerability or credential exposure | Must fix before merge |
| CORRECTNESS | Logic error, race condition, or data loss risk | Must fix before merge |
| STYLE | Naming, formatting, or idiomatic concerns | Fix or justify with comment |

!!! warning "Security findings are blocking"
    Any finding classified as SECURITY blocks the PR until resolved. This includes hardcoded secrets, missing input validation, and authentication bypasses.

## Addressing Findings

When a reviewer leaves a finding:

1. **Acknowledge** -- respond to the comment indicating you understand the concern.
2. **Fix or explain** -- either push a fix commit or explain why the current approach is correct.
3. **Request re-review** -- after addressing all findings, request another review pass.

Do not resolve conversations yourself. The reviewer who raised the finding resolves it after verifying the fix.

## Conversation Resolution

The conversation resolution protocol ensures nothing is missed:

- **Reviewer raises** -- creates a review comment on a specific line or file.
- **Author responds** -- pushes a fix or provides justification.
- **Reviewer resolves** -- marks the conversation as resolved after verification.
- **Merge gate** -- all conversations must be resolved before merge is allowed.

This pattern prevents findings from being silently dismissed and maintains a clear audit trail of what was raised, how it was addressed, and who verified the resolution.
