# ADEPT Documentation Guidelines and Policy

**Last Updated**: 2026-01-19
**Status**: Active Policy

---

## Purpose

This document establishes guidelines for maintaining clean, organized, and navigable documentation across the ADEPT platform. These guidelines ensure that users can quickly find information without wading through implementation details in top-level documents.

---

## Core Principles

### 1. **Separation of Concerns**

Documentation should be organized by **audience and purpose**, not by **implementation timeline**:

- **Top-level docs**: High-level navigation and quick reference
- **Onboarding guides**: Best practices, features, and HOWTOs
- **Detailed docs**: Implementation details, test results, and technical specifications

### 2. **Progressive Disclosure**

Users should be able to:
1. Get an overview quickly (top-level docs)
2. Learn how to use features (onboarding guides)
3. Dive deep when needed (subdirectory docs)

### 3. **Single Source of Truth**

Each piece of information should exist in **one primary location** and be **referenced** from other locations, not duplicated.

---

## Documentation Hierarchy

### Tier 1: Top-Level Navigation (`docs/*.md`)

**Purpose**: High-level overviews with references to detailed documentation

**Scope**:
- Brief summaries (2-5 sentences)
- Links to detailed documentation
- Navigation aids for finding information
- Feature availability and status

**Anti-Patterns** (❌ DO NOT INCLUDE):
- ❌ Detailed implementation steps
- ❌ Complete test results and metrics
- ❌ Line-by-line code changes
- ❌ Comprehensive bug analysis
- ❌ Extensive technical specifications

**Examples**:

✅ **GOOD** (High-level with references):
```markdown
### Session 33: Streamlit v2 Integration Testing & E2E Fixture Fixes
**Branch**: `feature-contextwindow-and-sessionmgmt-integration-add-session-navigation`

Established comprehensive testing infrastructure for streamlit_app_v2: integration tests (database, auth), E2E fixture fixes, and critical bug fixes (PostgreSQL type casting, WCAG accessibility).

**Detailed Documentation**: See `testing/SESSION33_FINAL_STATUS.md` and 10 related session files (11 documents, 3,600+ lines total)
```

❌ **BAD** (Too detailed for top-level):
```markdown
### Session 33: Streamlit v2 Integration Testing & E2E Fixture Fixes

**Accomplishments**:
- ✅ **Phase 2 Integration Tests**: 10/10 database tests passing (100%), 2/8 auth tests passing (25% as expected)
  - Real PostgreSQL integration with UUID-based test isolation
  - Real Keycloak authentication integration
  - Schema fixes (message_role, message_content, message_index)
  - Foreign key cascades and transaction handling
- ✅ **Phase 3 E2E Fixture Fix**: 100% fixture navigation success (20/20 tests)
  - Fixed Playwright `.count() > 0` check + 5-second render wait
  - Enhanced logging for visibility into navigation flow
  - All tests successfully navigate to Session Manager page
[... 50+ more lines of detailed implementation ...]
```

**Top-Level Files**:
- `README.md` - Documentation index and navigation
- `ROADMAP.md` - Planned features and completed milestones (high-level)
- `IMPLEMENTATION_STATUS_CHECKPOINT.md` - Current sprint status (consider splitting into subdirectories)

---

### Tier 2: Onboarding Guides (`docs/PLATFORM_*.md`, `docs/DOMAIN_*.md`)

**Purpose**: Help users learn how to **use** the platform effectively

**Scope**:
- Quick start guides
- Essential commands reference
- Best practices and patterns
- Feature overviews
- HOWTO guides
- Troubleshooting common issues
- References to detailed documentation

**Anti-Patterns** (❌ DO NOT INCLUDE):
- ❌ Detailed test implementation strategies
- ❌ Comprehensive bug fix analyses
- ❌ Line-by-line code walkthroughs
- ❌ Extensive implementation timelines
- ❌ Complete session summaries

**Examples**:

✅ **GOOD** (Essential commands and best practices):
```markdown
## Testing and Validation

### Test Execution Commands

```bash
# Run all validation tests
make validate

# Service-specific validation
make validate-data                    # Data-plane authentication
make validate-mgmt                   # Management-plane operations
```

### Testing Best Practices

**Key Principles** (Sessions 22, 33):
- Use container-based testing with read-only mounts (`:ro`)
- Use ephemeral `/tmp` storage for test dependencies
- Tests MUST use `agentic_framework_network` with internal service names
- Default test credentials: `notebook-user` / `notebook-password`

**Detailed Testing Documentation**: See `docs/testing/` for comprehensive testing strategies, Session 33 integration test infrastructure (11 files, 3,600+ lines), test runbooks, and best practices.
```

❌ **BAD** (Too detailed for onboarding):
```markdown
## Testing and Validation

### Session 33: Streamlit v2 Testing Infrastructure (2026-01-19)

**Status**: ✅ ALL OBJECTIVES COMPLETE AND VALIDATED

Session 33 established comprehensive testing infrastructure for streamlit_app_v2 with integration tests, E2E fixture fixes, and critical bug fixes.

#### Integration Tests

**Database Integration Tests** (`tests/integration/streamlit_app_v2/test_database_integration.py`):
- 10/10 tests passing (100%) against real PostgreSQL
- CRUD operations with UUID-based test isolation
- Transaction handling (commit, rollback)
[... detailed implementation continues for 100+ lines ...]
```

**Onboarding Guide Files**:
- `PLATFORM_AI_ENGINEER_ONBOARDING.md` - Platform engineers guide
- `DOMAIN_SME_VIBE_CODING_GUIDE.md` - Domain scientists guide
- `INFRASTRUCTURE_ENGINEER_K8S_ONBOARDING.md` - DevOps/K8s guide

---

### Tier 3: Detailed Documentation (`docs/*/`)

**Purpose**: Provide comprehensive technical specifications, implementation details, and test results

**Scope**:
- Complete implementation plans
- Detailed test results and metrics
- Line-by-line code changes
- Comprehensive bug analyses
- Technical architecture deep dives
- Session summaries with full context
- Performance benchmarks
- Migration guides

**Organization by Subdirectory**:

| Subdirectory | Contents |
|-------------|----------|
| `architecture/` | System design, integration strategies, technical architecture |
| `testing/` | Test strategies, runbooks, session test results, test infrastructure |
| `deployment/` | Deployment guides, infrastructure setup, build instructions |
| `fixes/` | Bug fixes, issue analyses, resolution documentation |
| `implementation-plans/` | Roadmaps, migration plans, refactoring strategies |
| `compliance/` | Security, compliance, LLM provider policies |
| `guides/` | User guides and implementation tutorials |
| `session-summaries/` | Historical session archives and records |
| `presentations/` | Training materials and onboarding decks |
| `checkpoints/` | Implementation milestones and WIP summaries |

**Example Structure**:

```
docs/testing/
├── SESSION33_FINAL_STATUS.md                        # Complete status (457 lines)
├── SESSION33_PHASE2_INTEGRATION_TESTS_PLAN.md       # Implementation plan (462 lines)
├── SESSION33_PHASE2_INTEGRATION_TESTS_REPORT.md     # Completion report (450+ lines)
├── SESSION33_PHASE3_E2E_FIXTURE_FIX_PLAN.md        # E2E fixture plan (450+ lines)
├── SESSION33_PHASE3_E2E_FIXTURE_FIX_REPORT.md      # E2E fixture report (450+ lines)
├── SESSION33_STREAMLIT_LOGS_ANALYSIS.md            # Bug analysis (420 lines)
├── SESSION33_ACCESSIBILITY_FIX.md                  # WCAG fix (381 lines)
├── SESSION33_COMPLETE_SUMMARY.md                   # Full summary (593 lines)
├── SESSION33_VALIDATION_SUMMARY.md                 # Post-push validation (331 lines)
└── SESSION33_E2E_FIXTURE_VALIDATION_RESULTS.md     # E2E results (431 lines)
```

---

## File Naming Conventions

### Case Conventions

- **UPPERCASE_WITH_UNDERSCORES.md** - Major documents, guides, and status files
  - Examples: `README.md`, `ROADMAP.md`, `PLATFORM_AI_ENGINEER_ONBOARDING.md`
- **lowercase-with-hyphens.md** - Configuration and technical implementation files
  - Examples: `agent-gateway-keycloak-design.md`, `local-development.md`

### Suffix Conventions

- `*_FIX.md` - Bug fix and resolution documentation
- `*_PLAN.md` - Planning and roadmap documents
- `*_GUIDE.md` - User guides and tutorials
- `*_ANALYSIS.md` - Technical analysis and investigation reports
- `*_REPORT.md` - Completion reports and validation results
- `*_STATUS.md` - Status summaries and checkpoints
- `SESSION_XX_*.md` - Session-specific documentation

---

## Content Guidelines

### For Top-Level Documents (README.md, ROADMAP.md)

**DO**:
- ✅ Provide navigation to detailed documentation
- ✅ Use 2-5 sentence summaries for each topic
- ✅ Link to subdirectory documentation for details
- ✅ Focus on "what" and "where to find more"
- ✅ Update regularly with new features (high-level only)

**DON'T**:
- ❌ Include detailed implementation steps
- ❌ Duplicate content from subdirectories
- ❌ Add complete test results or metrics
- ❌ Include comprehensive technical specifications
- ❌ Write multi-paragraph explanations

### For Onboarding Guides

**DO**:
- ✅ Provide essential commands and examples
- ✅ Explain best practices and patterns
- ✅ Reference detailed documentation
- ✅ Include troubleshooting for common issues
- ✅ Focus on "how to use" and "how to contribute"

**DON'T**:
- ❌ Include session-by-session implementation details
- ❌ Duplicate detailed test strategies
- ❌ Add comprehensive bug fix analyses
- ❌ Include complete migration timelines

### For Detailed Documentation (Subdirectories)

**DO**:
- ✅ Provide comprehensive technical details
- ✅ Include complete test results and metrics
- ✅ Document all implementation steps
- ✅ Explain architectural decisions
- ✅ Include code examples and line references
- ✅ Add session-specific context

**DON'T**:
- ❌ Try to summarize for casual readers
- ❌ Worry about length (these are deep-dive docs)

---

## Documentation Workflow

### When Adding New Documentation

1. **Determine the Appropriate Tier**:
   - Is this high-level navigation? → Top-level docs
   - Is this a how-to guide? → Onboarding guides
   - Is this detailed implementation? → Subdirectory docs

2. **Create Documentation in the Right Location**:
   - Implementation plans → `docs/implementation-plans/`
   - Test results → `docs/testing/`
   - Bug fixes → `docs/fixes/`
   - Architecture → `docs/architecture/`
   - Session summaries → `docs/session-summaries/`

3. **Add High-Level References**:
   - Update `docs/README.md` with a 2-5 sentence summary + link
   - Update `docs/ROADMAP.md` if it's a planned feature (high-level only)
   - Update relevant onboarding guide with command reference (if applicable)

4. **Cross-Reference Related Docs**:
   - Link to related architecture documents
   - Reference relevant fixes or implementations
   - Point to applicable guides or tutorials

### Example Workflow: Session 33 Integration Tests

**Step 1: Create Detailed Documentation** (Tier 3):
```bash
# Create 11 comprehensive files in docs/testing/
docs/testing/SESSION33_FINAL_STATUS.md                    (457 lines)
docs/testing/SESSION33_PHASE2_INTEGRATION_TESTS_PLAN.md   (462 lines)
[... 9 more detailed files ...]
```

**Step 2: Add High-Level Reference** (Tier 1):
```markdown
# In docs/README.md - "Recent Documentation Updates" section:

### 2026-01-19: Session 33 - Streamlit v2 Integration Testing & E2E Fixture Fixes
**Branch**: `feature-contextwindow-and-sessionmgmt-integration-add-session-navigation`

Established comprehensive testing infrastructure for streamlit_app_v2: integration tests (database, auth), E2E fixture fixes, and critical bug fixes.

**Detailed Documentation**: See `testing/SESSION33_FINAL_STATUS.md` and 10 related session files (11 documents, 3,600+ lines total)
```

**Step 3: Update ROADMAP** (Tier 1):
```markdown
# In docs/ROADMAP.md - "Active Implementation Plans" section:

### Session 33: Streamlit v2 Integration Testing & E2E Fixture Fixes (COMPLETE)

**Status**: ✅ **ALL OBJECTIVES COMPLETE AND VALIDATED**

**Objective**: Establish comprehensive testing infrastructure for streamlit_app_v2 including integration tests (database, auth), E2E fixture fixes, and critical bug fixes.

**Results**: 38 tests created (32 passing, 84%), 11 comprehensive documentation files (3,600+ lines), 2 critical bugs fixed and validated.

**Detailed Documentation**: See `docs/testing/SESSION33_FINAL_STATUS.md` and 10 related session files for complete implementation details, test results, key learnings, and recommendations.
```

**Step 4: Update Onboarding Guide** (Tier 2):
```markdown
# In docs/PLATFORM_AI_ENGINEER_ONBOARDING.md - "Testing and Validation" section:

## Testing and Validation

### Test Execution Commands

```bash
# Integration tests (Session 33+)
make validate-session33-phase2-database  # Database integration tests
make validate-session33-phase2-auth      # Auth integration tests
```

### Testing Best Practices

**Key Principles** (Sessions 22, 33):
- Use container-based testing with read-only mounts (`:ro`)
- Tests MUST use `agentic_framework_network` with internal service names

**Detailed Testing Documentation**: See `docs/testing/` for comprehensive testing strategies, Session 33 integration test infrastructure (11 files, 3,600+ lines), test runbooks, and best practices.
```

---

## Review Checklist

Before committing documentation, verify:

### For Top-Level Docs (README.md, ROADMAP.md)
- [ ] Summary is 2-5 sentences maximum
- [ ] Links to detailed documentation are present
- [ ] No detailed implementation steps included
- [ ] No complete test results or metrics included
- [ ] Focuses on navigation and high-level status

### For Onboarding Guides
- [ ] Provides essential commands only
- [ ] Explains best practices concisely
- [ ] References detailed documentation
- [ ] No detailed test strategies included
- [ ] No session-by-session implementation details
- [ ] Focuses on "how to use" not "how it was built"

### For Detailed Documentation (Subdirectories)
- [ ] File is in the appropriate subdirectory
- [ ] Comprehensive technical details included
- [ ] Cross-references to related docs present
- [ ] Front matter includes status and date
- [ ] Filename follows naming conventions

---

## Enforcement

### Code Review Guidelines

When reviewing documentation pull requests, verify:

1. **Hierarchy Compliance**: Documentation is in the correct tier
2. **No Duplication**: Information exists in one primary location
3. **Proper References**: Top-level docs reference detailed docs
4. **File Naming**: Follows established conventions
5. **Cross-References**: Related docs are linked

### Periodic Audits

Quarterly review to ensure:
- Top-level docs remain concise (< 500 lines total)
- Subdirectories are properly organized
- Cross-references are up-to-date
- No information duplication exists

---

## Migration Guide for Existing Documentation

If you find documentation violating these guidelines:

1. **Identify the Issue**:
   - Top-level doc too detailed?
   - Onboarding guide includes implementation details?
   - Detailed doc in wrong subdirectory?

2. **Move Content to Appropriate Location**:
   - Extract detailed content to subdirectory
   - Replace with high-level summary + link
   - Update cross-references

3. **Example Migration**:
   ```bash
   # Before: 100 lines of detailed test results in README.md

   # After:
   # 1. Create docs/testing/SESSION33_FINAL_STATUS.md (457 lines of detail)
   # 2. Replace in README.md with:
   #    "Session 33 established comprehensive testing infrastructure.
   #     **Detailed Documentation**: See testing/SESSION33_FINAL_STATUS.md"
   ```

---

## Questions and Exceptions

### When to Deviate from Guidelines

Rare exceptions may be justified when:
- Documentation is under 200 lines total (small projects)
- Prototype/proof-of-concept documentation (temporary)
- Emergency hotfix documentation (should be cleaned up later)

### Contact

For questions about these guidelines or exceptions, consult:
- Platform engineering team lead
- Documentation maintainer
- Technical writer (if available)

---

## Appendix: Real-World Examples

### Example 1: Session 33 Documentation (Correct Implementation)

**Tier 1 (README.md)** - 4 lines:
```markdown
### 2026-01-19: Session 33 - Streamlit v2 Integration Testing & E2E Fixture Fixes
Established comprehensive testing infrastructure for streamlit_app_v2: integration tests (database, auth), E2E fixture fixes, and critical bug fixes.

**Detailed Documentation**: See `testing/SESSION33_FINAL_STATUS.md` and 10 related session files (11 documents, 3,600+ lines total)
```

**Tier 2 (PLATFORM_AI_ENGINEER_ONBOARDING.md)** - 20 lines:
```markdown
## Testing and Validation

### Test Execution Commands
[Essential commands only]

### Testing Best Practices
[Key principles with references to detailed docs]
```

**Tier 3 (docs/testing/)** - 11 files, 3,600+ lines:
- `SESSION33_FINAL_STATUS.md` (457 lines) - Complete status
- `SESSION33_PHASE2_INTEGRATION_TESTS_PLAN.md` (462 lines) - Plan
- `SESSION33_PHASE2_INTEGRATION_TESTS_REPORT.md` (450+ lines) - Report
- [... 8 more detailed files ...]

---

**Document Version**: 1.0
**Last Updated**: 2026-01-19
**Approved By**: Platform Engineering Team
**Next Review**: 2026-04-19 (Quarterly)
