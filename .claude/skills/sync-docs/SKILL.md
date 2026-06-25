---
name: sync-docs
description: Check documentation parity across public Pages, internal wiki, CLAUDE.md/CLAUDE.public.md, and skill registry — detects drift, stale content, safety violations, and missing skill entries
disable-model-invocation: true
allowed-tools: Bash(grep *) Bash(find *) Bash(diff *) Bash(wc *) Bash(ls *) Bash(git *) Bash(make *) Bash(python3 *) Read Glob Grep
---

You are assisting an ADEPT developer with cross-repository documentation synchronization and safety validation. This skill checks parity across three dimensions and reports drift, stale content, and content safety violations.

Do not use emojis in any output.

## Arguments

```
/sync-docs [--target pages|wiki|claude|all] [--fix] [--dry-run]
```

| Flag | Default | Behavior |
|------|---------|----------|
| `--target` | `all` | Which checks to run |
| `--fix` | off | Propose edits (always requires user confirmation before writing) |
| `--dry-run` | off | Report issues without suggesting fixes |

If no arguments provided, run all checks with `--dry-run` behavior (report only).

---

## Check 1: Pages Parity (`--target pages`)

Validates that `docs/public-site/` content is consistent with staged-tree-eligible sources and passes safety checks.

### Step 1a: Nav completeness

```bash
# Extract all .md files referenced in mkdocs.yml nav
grep -oP '(?<=: ).*\.md' docs/public-site/mkdocs.yml | while read f; do
  if [ ! -f "docs/public-site/docs/$f" ]; then
    echo "MISSING: docs/public-site/docs/$f"
  fi
done
```

Report any nav entries with missing files.

### Step 1b: Source eligibility

For each page in `docs/public-site/docs/`, verify that no content was derived from `.publish-exclude`-blocked sources. This is a structural check — look for references to excluded doc paths:

```bash
# Check for references to internal-only doc paths
grep -rniE "(implementation-plans|implementation-reports|bugfixes|session-summaries|implementation-summaries)" docs/public-site/docs/
```

If any hits, flag them as potential source eligibility violations.

### Step 1c: Prohibited pattern scan (CRITICAL)

```bash
# Standard safety patterns
grep -rniE -f scripts/release/prohibited_patterns.txt docs/public-site/docs/

# Extended internal reference check
grep -rniE "(SESSION_[0-9]+|session [0-9]+[^a-z]|\.pnl\.gov|\.pnnl\.gov)" docs/public-site/docs/

# Credential patterns
grep -rniE "(sk-[a-zA-Z0-9]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN (RSA |EC )?PRIVATE KEY)" docs/public-site/docs/
```

Report ALL hits. Any match in the prohibited pattern scan is a **FAIL** that must be resolved before deployment.

### Step 1d: Staleness check

Compare page modification dates against source doc dates:

```bash
# Find pages not modified in the last 30 days while source docs changed
for page in $(find docs/public-site/docs -name "*.md" -type f); do
  page_date=$(git log -1 --format="%ct" -- "$page" 2>/dev/null || echo 0)
  echo "$page_date $page"
done | sort -n | head -10
```

Flag pages whose content predates significant source changes.

---

## Check 2: CLAUDE.md vs CLAUDE.public.md Parity (`--target claude`)

Ensures `CLAUDE.public.md` stays in sync with `CLAUDE.md` structurally (without leaking sensitive content).

### Step 2a: Section heading extraction

```bash
# Extract H2 headings from both files
grep "^## " CLAUDE.md | sort > /tmp/claude_internal_headings.txt
grep "^## " CLAUDE.public.md | sort > /tmp/claude_public_headings.txt

# Diff headings
diff /tmp/claude_internal_headings.txt /tmp/claude_public_headings.txt
```

Report:
- **Missing sections**: H2 headings in CLAUDE.md that have no counterpart in CLAUDE.public.md (may need a public-safe version added)
- **Extra sections**: H2 headings in CLAUDE.public.md that don't exist in CLAUDE.md (may be stale)

Not all internal sections need public counterparts — the following are intentionally omitted from CLAUDE.public.md:
- Credential management sections
- VM/host-specific details (RC, EMSL, EC2)
- Internal sprint/session references
- Port mappings with internal container names

### Step 2b: Safety validation on CLAUDE.public.md

```bash
# CLAUDE.public.md must NEVER contain these patterns
grep -nE -f scripts/release/prohibited_patterns.txt CLAUDE.public.md
grep -nE -f scripts/release/prohibited_patterns_structural.txt CLAUDE.public.md
```

Any match is a **CRITICAL FAIL** — CLAUDE.public.md is published directly to the public repo.

### Step 2c: Feature coverage

Check that key architectural features documented in CLAUDE.md have at least a brief mention in CLAUDE.public.md:

```bash
# Key features that should appear in both (search for keywords)
for keyword in "Response API" "Assistants API" "Multi-Agent" "A2A" "MCP" "Keycloak" "LangGraph" "ASOPB"; do
  internal=$(grep -ci "$keyword" CLAUDE.md)
  public=$(grep -ci "$keyword" CLAUDE.public.md)
  if [ "$public" -eq 0 ] && [ "$internal" -gt 0 ]; then
    echo "MISSING in CLAUDE.public.md: '$keyword' (appears $internal times in CLAUDE.md)"
  fi
done
```

---

## Check 2b: README.md vs README.public.md Parity (`--target readme`)

Ensures `README.public.md` stays in sync with `README.md` structurally without referencing internal-only example stacks or resources excluded by `.publish-exclude`.

### Step 2b-a: Section heading extraction

```bash
# Extract H2 headings from both files
grep "^## " README.md | sort > /tmp/readme_internal_headings.txt
grep "^## " README.public.md | sort > /tmp/readme_public_headings.txt

# Diff headings
diff /tmp/readme_internal_headings.txt /tmp/readme_public_headings.txt
```

Report:
- **Missing sections**: H2 headings in README.md that have no counterpart in README.public.md
- **Extra sections**: H2 headings in README.public.md that don't exist in README.md (may be stale)

### Step 2b-b: Safety validation on README.public.md

```bash
# README.public.md must NEVER reference excluded example stacks
grep -nE "(biofoundation_mcp_server|vfm_mcp_server|emsl_sandbox|rc_famous|emsl_chatgem)" README.public.md

# Must NEVER contain internal org references
grep -nE -f scripts/release/prohibited_patterns.txt README.public.md

# Must NEVER reference internal-only paths
grep -nE -f scripts/release/prohibited_patterns_structural.txt README.public.md
```

Any match is a **CRITICAL FAIL** — README.public.md replaces README.md in the public repo via the publish pipeline swap.

### Step 2b-c: Example Stacks table validation

The "Example Stacks" table in README.public.md must only reference directories that survive `.publish-exclude` filtering:

```bash
# Extract example stack paths from README.public.md
grep -oP '\[.*?\]\((examples/[^)]+)/?\)' README.public.md | grep -oP 'examples/[^)]+' | while read dir; do
  # Check if directory would be excluded by .publish-exclude
  if grep -q "^- /$dir/" .publish-exclude; then
    echo "FAIL: README.public.md references excluded stack: $dir"
  else
    echo "OK: $dir (not excluded)"
  fi
done
```

### Step 2b-d: Feature parity

Key capability bullet points should match between internal and public README:

```bash
# Compare Key Capabilities bullet count
internal_bullets=$(grep -c "^- \*\*" README.md)
public_bullets=$(grep -c "^- \*\*" README.public.md)
echo "Internal: $internal_bullets capability bullets"
echo "Public: $public_bullets capability bullets"
if [ "$internal_bullets" -ne "$public_bullets" ]; then
  echo "WARNING: Bullet count mismatch — review for intentional omissions"
fi
```

---

## Check 2c: Onboarding Doc Parity (`--target onboarding`)

Ensures each role-based onboarding document has a public variant with proper redaction. These docs are linked from README.public.md and must exist in the published tree without internal references.

### Onboarding Docs Registry

| Internal Path | Public Variant Required | Redaction Level |
|---------------|------------------------|-----------------|
| `docs/PLATFORM_AI_ENGINEER_ONBOARDING.md` | YES (`.public.md`) | Heavy — IPs, SESSION refs |
| `docs/DOMAIN_SME_VIBE_CODING_GUIDE.md` | YES (`.public.md`) | Light — internal URLs and paths |
| `docs/SYSTEMS_ADMINISTRATOR_ONBOARDING.md` | YES (`.public.md`) | Heavy — IPs, hostnames, SESSION refs |
| `docs/tutorials/DEVELOPER_ONBOARDING_ASOPB_AND_RELEASE.md` | YES (`.public.md`) | Moderate — internal references |
| `docs/deployment/INFRASTRUCTURE_ENGINEER_K8S_ONBOARDING.md` | NO (safe as-is) | None — 0 sensitive hits |

### Step 2c-a: Public variant existence

```bash
# Check that each required public variant exists
ONBOARDING_DOCS=(
  "docs/PLATFORM_AI_ENGINEER_ONBOARDING"
  "docs/DOMAIN_SME_VIBE_CODING_GUIDE"
  "docs/SYSTEMS_ADMINISTRATOR_ONBOARDING"
  "docs/tutorials/DEVELOPER_ONBOARDING_ASOPB_AND_RELEASE"
)

for doc in "${ONBOARDING_DOCS[@]}"; do
  if [ ! -f "${doc}.public.md" ]; then
    echo "MISSING: ${doc}.public.md"
  else
    echo "OK: ${doc}.public.md exists"
  fi
done

# K8s doc needs no variant — verify it has 0 sensitive hits
grep -ciE -f scripts/release/prohibited_patterns.txt \
  docs/deployment/INFRASTRUCTURE_ENGINEER_K8S_ONBOARDING.md || echo "OK: 0 sensitive hits"
```

### Step 2c-b: Safety validation on public variants

```bash
# Public variants must NEVER contain these patterns
for variant in docs/*.public.md docs/tutorials/*.public.md; do
  if [ -f "$variant" ]; then
    hits=$(grep -ciE -f scripts/release/prohibited_patterns.txt "$variant" || true)
    if [ "$hits" -gt 0 ]; then
      echo "FAIL: $variant has $hits sensitive hits"
      grep -nE -f scripts/release/prohibited_patterns.txt "$variant" | head -5
    else
      echo "PASS: $variant (0 sensitive hits)"
    fi
  fi
done
```

Any match is a **CRITICAL FAIL** -- public variants are swapped into the published tree.

### Step 2c-c: Section heading parity

```bash
# Verify public variants maintain structural coverage (same H2 headings)
for doc in "${ONBOARDING_DOCS[@]}"; do
  if [ -f "${doc}.md" ] && [ -f "${doc}.public.md" ]; then
    internal_h2=$(grep -c "^## " "${doc}.md")
    public_h2=$(grep -c "^## " "${doc}.public.md")
    if [ "$internal_h2" -ne "$public_h2" ]; then
      echo "DRIFT: ${doc} — internal has $internal_h2 H2 sections, public has $public_h2"
    else
      echo "PASS: ${doc} — $internal_h2 H2 sections in both"
    fi
  fi
done
```

Section count mismatches are WARNINGs, not FAILs -- some internal sections (e.g., detailed Ansible inventories with real hostnames) may be intentionally condensed in the public variant.

### Step 2c-d: .publish-exclude coverage

Verify that internal onboarding docs are excluded and public variants are not:

```bash
# Internal versions should be excluded
for doc in "${ONBOARDING_DOCS[@]}"; do
  if grep -q "^- /${doc}.md" .publish-exclude; then
    echo "OK: ${doc}.md excluded from publish"
  else
    echo "MISSING EXCLUDE: ${doc}.md not in .publish-exclude"
  fi
done

# Public variants should be explicitly included
for doc in "${ONBOARDING_DOCS[@]}"; do
  if grep -q "^+ /${doc}.public.md" .publish-exclude; then
    echo "OK: ${doc}.public.md included in publish"
  else
    echo "MISSING INCLUDE: ${doc}.public.md not whitelisted in .publish-exclude"
  fi
done

# K8s doc should NOT be excluded (safe as-is, whitelisted directly)
if grep -q "^+ /docs/deployment/INFRASTRUCTURE_ENGINEER_K8S_ONBOARDING.md" .publish-exclude; then
  echo "OK: K8s onboarding whitelisted directly (no variant needed)"
else
  echo "MISSING: K8s onboarding doc not whitelisted"
fi
```

### .publish-exclude Artifact Lifecycle

When adding or modifying public variants, follow this checklist to keep `.publish-exclude` in sync:

**Adding a new public variant:**
1. Create the `*.public.md` file with redactions applied
2. Add `+ /<path-to-variant>.public.md` in the appropriate section of `.publish-exclude`
3. Add `- /<path-to-internal-version>.md` to exclude the internal version
4. Verify ordering: includes (`+`) must appear BEFORE the catch-all exclude (`- /docs/**`)
5. Run `/sync-docs --target onboarding` to confirm parity

**Removing a public variant** (e.g., internal doc becomes safe):
1. Delete the `*.public.md` file
2. Remove the `+ /<path>.public.md` include rule
3. Remove the `- /<path>.md` exclude rule (or replace with a direct `+` include if the internal version is now clean)
4. If the internal doc is clean, add `+ /<path>.md` to whitelist it directly

**rsync merge-file format reference** (`.publish-exclude`):
- `+ /path` — explicitly include (overrides later excludes)
- `- /path` — explicitly exclude
- First matching rule wins (order matters)
- `**` matches any depth of subdirectories
- Final `- /docs/**` is the catch-all that excludes everything not explicitly included
- Internal docs with `*.public.md` variants: the swap in `publish-to-public.sh` Step 3b renames them after rsync applies
- Non-.md variants (`Makefile.public`, `*.public.yaml`): also swapped in Step 3b (Makefile.public -> Makefile, *.public.yaml -> *.yaml)

**Current public variant registry** (keep this in sync with the Onboarding Docs Registry table above):

| Variant File | Replaces (via swap) | .publish-exclude Rule |
|--------------|--------------------|-----------------------|
| `docs/PLATFORM_AI_ENGINEER_ONBOARDING.public.md` | `docs/PLATFORM_AI_ENGINEER_ONBOARDING.md` | `+ /docs/PLATFORM_AI_ENGINEER_ONBOARDING.public.md` |
| `docs/DOMAIN_SME_VIBE_CODING_GUIDE.public.md` | `docs/DOMAIN_SME_VIBE_CODING_GUIDE.md` | `+ /docs/DOMAIN_SME_VIBE_CODING_GUIDE.public.md` |
| `docs/SYSTEMS_ADMINISTRATOR_ONBOARDING.public.md` | `docs/SYSTEMS_ADMINISTRATOR_ONBOARDING.md` | `+ /docs/SYSTEMS_ADMINISTRATOR_ONBOARDING.public.md` |
| `docs/tutorials/DEVELOPER_ONBOARDING_ASOPB_AND_RELEASE.public.md` | `docs/tutorials/DEVELOPER_ONBOARDING_ASOPB_AND_RELEASE.md` | `+ /docs/tutorials/DEVELOPER_ONBOARDING_ASOPB_AND_RELEASE.public.md` |
| `docs/api/README.public.md` | `docs/api/README.md` | `+ /docs/api/README.public.md` |
| `devtools/AWS_VM_DEPLOYMENT_GUIDE.public.md` | `devtools/AWS_VM_DEPLOYMENT_GUIDE.md` | `+ /devtools/AWS_VM_DEPLOYMENT_GUIDE.public.md` |
| `deployment/README.public.md` | `deployment/README.md` | `+ /deployment/README.public.md` |
| `devtools/skypilot/README.public.md` | `devtools/skypilot/README.md` | `+ /devtools/skypilot/README.public.md` |
| `devtools/skypilot/ONBOARDING.public.md` | `devtools/skypilot/ONBOARDING.md` | `+ /devtools/skypilot/ONBOARDING.public.md` |
| `devtools/skypilot/Makefile.public` | `devtools/skypilot/Makefile` | `+ /devtools/skypilot/Makefile.public` |
| `devtools/skypilot/tasks/deploy-adept-cloud.public.yaml` | `devtools/skypilot/tasks/deploy-adept-cloud.yaml` | `+ /devtools/skypilot/tasks/deploy-adept-cloud.public.yaml` |
| `README.public.md` | `README.md` | (root-level, always included) |
| `CLAUDE.public.md` | `CLAUDE.md` | (root-level, always included) |

**Directly whitelisted (no variant needed — 0 sensitive hits):**
- `docs/deployment/INFRASTRUCTURE_ENGINEER_K8S_ONBOARDING.md`
- `docs/deployment/SWARM_MULTI_STACK_DEPLOYMENT_GUIDE.md`
- `docs/deployment/BATCH_DEPLOYMENT_EXECUTIVE_SUMMARY.md`

**Binary file exclusions:**
- `devtools/ADEPT_AWS_Deployment_Guide.pptx` — internal presentation with PNNL-specific content

**Excluded directories (internal-only, no public value):**
- `docs/testing/` — internal test logs, session validation reports
- `docs/testing-strategy/` — internal test proposals
- `docs/user-guides/` — placeholder docs, not informative for external users

---

## Check 3: Wiki Parity (`--target wiki`)

Skipped in public release — wiki is internal to the development team.

---

## Check 4: Skill Registry Parity (`--target skills`)

Compares the set of skills defined in `.claude/skills/` against all documentation locations that list skills. Detects missing entries after a new skill is added.

### Step 4a: Discover defined skills

```bash
# Extract all skill names from SKILL.md frontmatter
for dir in .claude/skills/*/; do
  if [ -f "$dir/SKILL.md" ]; then
    name=$(grep '^name:' "$dir/SKILL.md" | head -1 | sed 's/name: *//')
    desc=$(grep '^description:' "$dir/SKILL.md" | head -1 | sed 's/description: *//')
    echo "$name|$desc"
  fi
done | sort > /tmp/defined_skills.txt

echo "Defined skills: $(wc -l < /tmp/defined_skills.txt)"
cat /tmp/defined_skills.txt
```

### Step 4b: Check each documentation location

Compare the defined skill list against each location that maintains a skills table:

```bash
# Location 1: CLAUDE.md skills table
grep '| `/[a-z-]*`' CLAUDE.md | sed 's/.*`\///' | sed 's/`.*//' | sort > /tmp/claude_md_skills.txt

# Location 2: CLAUDE.public.md
grep -oP '/[a-z][-a-z]*' CLAUDE.public.md | sed 's|^/||' | sort -u > /tmp/claude_public_skills.txt

# Location 3: docs/development/CODE_HYGIENE.md
grep '| `/[a-z-]*`' docs/development/CODE_HYGIENE.md | sed 's/.*`\///' | sed 's/`.*//' | sort > /tmp/code_hygiene_skills.txt

# Location 4: docs/public-site/docs/developer-tools/claude-code-skills.md
grep '| `/[a-z-]*`' docs/public-site/docs/developer-tools/claude-code-skills.md | sed 's/.*`\///' | sed 's/`.*//' | sort > /tmp/pages_skills.txt

# Location 5: Wiki (if available)
if [ -f "temp/<repo>.wiki/Claude-Code-Skills-and-SDLC.md" ]; then
  grep -oP '/[a-z][-a-z]*' temp/<repo>.wiki/Claude-Code-Skills-and-SDLC.md | sed 's|^/||' | sort -u > /tmp/wiki_skills.txt
else
  echo "(wiki not cloned)" > /tmp/wiki_skills.txt
fi
```

### Step 4c: Report drift

For each documentation location, report skills that are defined but missing from that location:

```bash
DEFINED=$(cut -d'|' -f1 /tmp/defined_skills.txt)

echo "=== Skill Registry Parity ==="
for loc in claude_md claude_public code_hygiene pages wiki; do
  file="/tmp/${loc}_skills.txt"
  if [ -f "$file" ]; then
    missing=$(comm -23 <(echo "$DEFINED") "$file")
    if [ -n "$missing" ]; then
      echo "DRIFT in $loc: missing $(echo "$missing" | wc -l) skills:"
      echo "$missing" | sed 's/^/  - /'
    else
      echo "PASS: $loc (all skills listed)"
    fi
  fi
done
```

### Step 4d: Skill count consistency

Check that numeric skill counts in prose match the actual count:

```bash
SKILL_COUNT=$(wc -l < /tmp/defined_skills.txt)

# Check for count claims in docs
grep -rn "[0-9]* Claude Code skill" CLAUDE.md CLAUDE.public.md docs/public-site/docs/developer-tools/claude-code-skills.md 2>/dev/null | while read line; do
  claimed=$(echo "$line" | grep -oP '\d+(?= Claude Code skill)')
  if [ -n "$claimed" ] && [ "$claimed" -ne "$SKILL_COUNT" ]; then
    echo "COUNT MISMATCH: $line (actual: $SKILL_COUNT)"
  fi
done
```

### Not all skills need to appear everywhere

Some skills are internal-only or context-specific. The following locations have different coverage expectations:

| Location | Expected Coverage |
|----------|-------------------|
| `CLAUDE.md` | ALL skills (authoritative internal reference) |
| `CLAUDE.public.md` | Subset — omit skills that reference internal infra |
| `CODE_HYGIENE.md` | Security/scanning skills only (subset) |
| Public-site skills page | All user-facing skills |
| Wiki skills page | All skills (mirrors CLAUDE.md) |

When reporting drift, flag missing skills but note if a location is expected to be a subset. The developer decides whether to add or intentionally omit.

---

## Check 5: OpenAPI Spec Parity (`--target openapi`)

Validates that committed OpenAPI specs match the live API surface and contain no prohibited patterns.

### Step 5a: Spec drift detection

Requires ADEPT stack running (`make start`).

```bash
python3 docs/api/generate_openapi.py --check
```

If this exits non-zero, the committed specs have drifted from the live services.

Report:
- Number of paths in committed spec vs live
- Whether regeneration is needed

### Step 5b: Prohibited pattern scan

```bash
python3 docs/api/generate_openapi.py --scan --dry-run
```

Both `openapi.json` and `openapi-admin.json` must pass with 0 prohibited patterns. These files ship directly to the public repo (no `.public.md` variant needed).

### Step 5c: Version parity

```bash
# OpenAPI spec version should match the CalVer in pyproject.toml
SPEC_VERSION=$(python3 -c "import json; print(json.load(open('docs/api/openapi.json'))['info']['version'])")
PKG_VERSION=$(grep '^version' pyproject.toml | head -1 | grep -oP '"\K[^"]+')
if [ "$SPEC_VERSION" != "$PKG_VERSION" ]; then
  echo "DRIFT: openapi.json version ($SPEC_VERSION) != pyproject.toml ($PKG_VERSION)"
else
  echo "PASS: versions match ($SPEC_VERSION)"
fi
```

### Step 5d: README changelog currency

```bash
# docs/api/README.md and README.public.md should reference the current version
CURRENT_VERSION=$(grep '^version' pyproject.toml | head -1 | grep -oP '"\K[^"]+')
for readme in docs/api/README.md docs/api/README.public.md; do
  if grep -q "$CURRENT_VERSION" "$readme"; then
    echo "PASS: $readme references $CURRENT_VERSION"
  else
    echo "DRIFT: $readme missing changelog entry for $CURRENT_VERSION"
  fi
done
```

---

## Output Format

Present results as a table per check:

```
## Pages Parity Report

| Check | Status | Issues |
|-------|--------|--------|
| Nav completeness | PASS | 0 missing files |
| Source eligibility | PASS | 0 violations |
| Prohibited patterns | FAIL | 2 hits (see below) |
| Staleness | WARN | 3 pages >30 days stale |

### Prohibited Pattern Hits (MUST FIX)
- docs/public-site/docs/architecture/overview.md:45: contains internal IP
- docs/public-site/docs/deployment/docker-compose.md:12: contains internal hostname

## CLAUDE.md Parity Report

| Check | Status | Issues |
|-------|--------|--------|
| Section coverage | WARN | 2 new sections missing public counterpart |
| Safety validation | PASS | 0 prohibited patterns |
| Feature coverage | PASS | All keywords present |

## Wiki Parity Report

| Check | Status | Issues |
|-------|--------|--------|
| Sidebar coverage | PASS | All pages exist |
| Version references | WARN | 1 stale version |
| URL check | PASS | 0 broken links |

## Onboarding Doc Parity Report

| Check | Status | Issues |
|-------|--------|--------|
| Public variant existence | PASS | 4/4 variants exist |
| Safety validation | PASS | 0 sensitive hits in variants |
| Section heading parity | WARN | 1 doc has fewer H2 sections (intentional) |
| .publish-exclude coverage | PASS | All internal versions excluded |

## Skill Registry Parity Report

| Location | Status | Missing |
|----------|--------|---------|
| CLAUDE.md | PASS | 0 |
| CLAUDE.public.md | WARN | 1 (internal-only, may be intentional) |
| CODE_HYGIENE.md | PASS | 0 (subset — security skills only) |
| Public-site skills page | DRIFT | 1: `review-pr` |
| Wiki skills page | PASS | 0 |

### Skill Count Mismatches
- docs/public-site/docs/developer-tools/claude-code-skills.md:1 says "21 skills" (actual: 22)
```

---

## Fix Mode (`--fix`)

When `--fix` is passed:

1. For **prohibited pattern hits**: Propose specific edits to remove/redact the sensitive content
2. For **stale pages**: Show the diff between current page content and what the staged source says
3. For **CLAUDE.public.md drift**: Propose new sections or updates based on CLAUDE.md changes
4. For **skill registry drift**: Propose table row additions to each location missing a skill, using the skill's `name` and `description` from its SKILL.md frontmatter
5. For **onboarding doc drift**: Propose creation of missing `.public.md` variants using the redaction patterns (replace IPs with `<your-server-ip>`, hostnames with `<your-hostname>`, internal references with placeholders)

**CRITICAL**: NEVER auto-apply fixes. Always present proposed changes and wait for explicit developer confirmation before writing any file.

---

## Integration with Build System

The skill complements (does not replace) the build system validation:

```
/sync-docs (development time)     — catches drift BEFORE committing
make validate (pre-commit)        — ASOPB scan catches patterns that slip through
deploy-docs.yml (CI)              — builds only from committed public repo content
```

Recommended workflow:
1. Run `/sync-docs` before starting documentation work
2. Make edits to public-site pages
3. Run `/sync-docs --target pages` to verify changes
4. Run `cd docs/public-site && make validate` for ASOPB gate
5. Commit and push

---

## Makefile Integration

Suggest adding this target to `docs/public-site/Makefile` (task S7 from implementation plan):

```makefile
sync-check:
	@echo "Running documentation sync checks..."
	@grep -rniE -f scripts/release/prohibited_patterns.txt docs/ && \
		(echo "FAIL: Prohibited patterns found"; exit 1) || \
		echo "PASS: No prohibited patterns"
	@grep -rniE "(SESSION_[0-9]+|\.pnl\.gov|\.pnnl\.gov)" docs/ && \
		(echo "FAIL: Internal references found"; exit 1) || \
		echo "PASS: No internal references"
```
