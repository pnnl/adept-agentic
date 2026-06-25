# ADEPT Framework Documentation

**1,100+ markdown files** covering architecture, deployment, security, testing, and implementation history for the Secure, Extensible Multi-Cloud Agentic Platform.

**GitHub Wiki**: [pnnl/adept-agentic/wiki](https://github.com/pnnl/adept-agentic/wiki) — curated navigation layer with role-based onboarding, architecture overviews, and hands-on walkthroughs.

---

## Start Here: Choose Your Role

### Domain Scientists
**[DOMAIN_SME_VIBE_CODING_GUIDE.md](DOMAIN_SME_VIBE_CODING_GUIDE.md)** — Natural language "vibe coding" patterns, RAG-powered literature search, metabolic modeling case studies, and first-session walkthrough via Streamlit.

### Platform Engineers
**[PLATFORM_AI_ENGINEER_ONBOARDING.md](PLATFORM_AI_ENGINEER_ONBOARDING.md)** — Docker Compose quick start, three-tier architecture deep dive, development workflow, testing strategies, and troubleshooting.

### System Administrators
**[SYSTEMS_ADMINISTRATOR_ONBOARDING.md](SYSTEMS_ADMINISTRATOR_ONBOARDING.md)** — Keycloak management, credential architecture, OAuth2 redirect URI registration, network segmentation, and service health management.

### Security Engineers / New Developers
**[ASOPB and Release Pipeline Tutorial](tutorials/DEVELOPER_ONBOARDING_ASOPB_AND_RELEASE.md)** — AWS EC2 provisioning, ASOPB security scanning, ASPI scoring, scanning arbitrary codebases, MCP server development with security best practices, and the release pipeline.

### CLI Quick Setup
**[CLI Bootstrap Guide](guides/CLI_BOOTSTRAP_GUIDE.md)** — Configure the `afk` CLI in one command. Auto-detects environment, discovers gateway/Keycloak URLs, authenticates, and saves a working config.

---

## Directory Map

### Core Reference

| Directory | Files | Contents |
|-----------|-------|----------|
| [architecture/](architecture/) | 127 | System design, API architecture, integration strategies |
| [security/](security/) | 11 | Security architecture, network segmentation, RBAC |
| [compliance/](compliance/) | 4 | LLM provider policies, compliance matrices, DPA templates |
| [api/](api/) | 5 | API reference (presigned URLs, endpoints) |

### Deployment & Infrastructure

| Directory | Files | Contents |
|-----------|-------|----------|
| [deployment/](deployment/) | 14 | Docker Compose, Kubernetes/Helm, build guides |
| [infrastructure/](infrastructure/) | 3 | Ansible orchestration, ALB/WAF, CDK application stack |
| [configuration/](configuration/) | 6 | Environment variables, service configuration |

### Guides & Tutorials

| Directory | Files | Contents |
|-----------|-------|----------|
| [guides/](guides/) | 13 | RAG workflows, CLI bootstrap, OAuth2 management, A2A demo |
| [tutorials/](tutorials/) | 1 | ASOPB security scanning, release pipeline, MCP server development |
| [workshop/](workshop/) | 14 | Presentation outlines, LangGraph tutorial, A2A workshop, diagram generation |
| [user-guides/](user-guides/) | 2 | End-user documentation |

### Testing

| Directory | Files | Contents |
|-----------|-------|----------|
| [testing/](testing/) | 93 | Test strategy, Docker execution reference, contract testing, session test reports |
| [test-reports/](test-reports/) | 18 | Validation results and test run logs |

### Implementation History

| Directory | Files | Contents |
|-----------|-------|----------|
| [implementation-reports/](implementation-reports/) | 164 | Session-by-session implementation reports |
| [implementation-plans/](implementation-plans/) | 313 | Design plans, roadmaps, migration strategies |
| [bugfixes/](bugfixes/) | 36 | Root cause analysis and fix documentation |
| [fixes/](fixes/) | 120 | Bug fixes, issue analyses, resolution documentation |
| [session-summaries/](session-summaries/) | 10 | Development session archives |

### Other

| Directory | Files | Contents |
|-----------|-------|----------|
| [presentations/](presentations/) | 4 | Training materials, onboarding decks |
| [whitepaper/](whitepaper/) | 4 | Academic papers and technical whitepapers |
| [observability/](observability/) | 6 | Langfuse integration, logging architecture |
| [database-schema/](database-schema/) | 3 | PostgreSQL schema documentation |
| [archive/](archive/) | 1 | Deprecated docs preserved for reference |

---

## Top-Level Documents

| File | Purpose |
|------|---------|
| [PLATFORM_AI_ENGINEER_ONBOARDING.md](PLATFORM_AI_ENGINEER_ONBOARDING.md) | Platform engineer onboarding guide |
| [DOMAIN_SME_VIBE_CODING_GUIDE.md](DOMAIN_SME_VIBE_CODING_GUIDE.md) | Domain scientist vibe coding guide |
| [SYSTEMS_ADMINISTRATOR_ONBOARDING.md](SYSTEMS_ADMINISTRATOR_ONBOARDING.md) | System administrator onboarding guide |
| [ROADMAP.md](ROADMAP.md) | Project roadmap and future work |
| [CHANGELOG.md](CHANGELOG.md) | Version history and release notes |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | Current known issues and workarounds |
| [BACKLOG.md](BACKLOG.md) | Feature backlog |
| [DOCUMENTATION_GUIDELINES.md](DOCUMENTATION_GUIDELINES.md) | Standards for writing and organizing docs |
| [GITHUB_WIKI_PROPOSAL.md](GITHUB_WIKI_PROPOSAL.md) | Wiki structure proposal and contributor process specs |

---

## Examples and Workshops

Hands-on examples live in [`examples/`](../examples/) at the project root:

| Example | What It Demonstrates |
|---------|---------------------|
| [demo-bootstrap/](../examples/demo-bootstrap/) | Production two-VM deployment with Let's Encrypt SSL |
| [a2a-workshop/](../examples/a2a-workshop/) | A2A multi-cloud federation between independent ADEPT instances |
| [mcp_tools/](../examples/mcp_tools/) | Building external MCP tools (stdio and HTTP transport) |
| [academy_mcp_server/](../examples/academy_mcp_server/) | Academy federated agent integration |
| [opentrons_mcp_server/](../examples/opentrons_mcp_server/) | OpenTrons liquid handling lab automation |
| [emsl_sandbox/](../examples/emsl_sandbox/) | Hybrid-cloud sandbox on-premises (Rocky 9 + AWS SSH tunnel) |
| [emsl_chatgem/](../examples/emsl_chatgem/) | Full on-premises stack (~25 services, rootless Podman) |
| [slurm_hpc/](../examples/slurm_hpc/) | Slurm HPC cluster integration with FastMCP |

Workshop presentation materials and diagram generation: [docs/workshop/INDEX.md](workshop/INDEX.md)

Interactive Jupyter notebooks: [`notebooks/`](../notebooks/) (14 notebooks for setup, end-user, developer, and operator audiences)

---

## Documentation Standards

### File Naming Conventions

| Pattern | Use For |
|---------|---------|
| `UPPERCASE_WITH_UNDERSCORES.md` | Major documents, guides, status files |
| `lowercase-with-hyphens.md` | Configuration, technical implementation files |
| `SESSION_XX_*.md` | Session-specific implementation or bugfix reports |
| `*_GUIDE.md` | User guides and tutorials |
| `*_ARCHITECTURE.md` | Architecture and design documents |
| `*_PLAN.md` | Planning and roadmap documents |
| `*_ANALYSIS.md` | Technical analysis and investigation reports |

### Directory Organization

- **Top-level**: Only primary onboarding guides, roadmap, changelog, and known issues
- **Subdirectories**: Organized by category (architecture, deployment, testing, etc.)
- **Session reports**: `implementation-reports/` for features, `bugfixes/` for fixes
- **Historical content**: `archive/` or `session-summaries/`

### Contributing Documentation

See [DOCUMENTATION_GUIDELINES.md](DOCUMENTATION_GUIDELINES.md) for full standards, and the wiki [Contributing to ADEPT](https://github.com/pnnl/adept-agentic/wiki/Contributing-to-ADEPT) page for the contribution workflow.

---

## External Resources

- **GitHub (PNNL)**: https://github.com/pnnl/adept-agentic
- **GitHub Wiki**: https://github.com/pnnl/adept-agentic/wiki
- **Model Context Protocol (MCP)**: https://modelcontextprotocol.io/
- **LangGraph**: https://langchain-ai.github.io/langgraph/
- **Keycloak**: https://www.keycloak.org/documentation

---

*Last Updated: 2026-03-05*
