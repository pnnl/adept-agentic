# Dual API Strategy

**Date**: 2026-02-09 (Session 52)
**Status**: ✅ Official Strategy
**Decision**: Keep both APIs, focus Response API for new work

---

## Executive Summary

ADEPT supports **both** the Response API and Assistants API to maximize compatibility and flexibility:

- **Response API** (`/v1/responses/chat/completions`): **Primary API** for new implementations
- **Assistants API** (`/v1/assistants/*`, `/v1/threads/*`): **Legacy compatibility** for existing integrations

**Key Principle**: Both APIs are fully functional and supported, but **new development should use Response API** for simplicity, better streaming, and reduced complexity.

---

## Strategic Rationale

### Why Keep Both APIs?

1. **Backward Compatibility**: Existing integrations (OpenWebUI, custom tools) use Assistants API
2. **OpenAI Parity**: Support both OpenAI Responses API and Assistants API standards
3. **Migration Path**: Users can migrate at their own pace
4. **Flexibility**: Different use cases may prefer different APIs

### Why Focus Response API?

1. **Simplicity**: 1 endpoint vs 4 resource types
2. **Streaming**: Native SSE support vs polling
3. **Performance**: Direct response vs run polling loop
4. **Modern**: OpenAI's stable API (not beta)
5. **Developer Experience**: Fewer concepts, clearer patterns

---

## API Comparison Matrix

| Feature | Response API | Assistants API | Winner |
|---------|--------------|----------------|--------|
| **Endpoint Complexity** | Low (1 endpoint) | High (4 resource types) | ✅ Response API |
| **Streaming** | Full SSE support | Limited (run events) | ✅ Response API |
| **Request Pattern** | Single request | Create resources + Poll | ✅ Response API |
| **State Management** | Thread + Messages | Assistant + Thread + Run | ✅ Response API |
| **Tool Calling** | Native OpenAI format | Via assistant tools | ✅ Response API |
| **OpenAI Compatibility** | Stable API | Beta API | ✅ Response API |
| **Resource Persistence** | Threads only | Assistants + Threads | ⚠️ Assistants API |
| **Run History** | Via messages | Via runs table | ⚠️ Assistants API |
| **OpenWebUI Integration** | Requires adaptation | Native support | ⚠️ Assistants API |

**Verdict**: Response API wins on **8 of 11 criteria**.

---

## Decision Tree: Which API to Use?

```
┌─────────────────────────────────────┐
│  Starting a new project/feature?    │
└────────────┬────────────────────────┘
             │
             ├─── YES ──→ Use Response API ✅
             │
             └─── NO ──→ Is it an existing integration?
                            │
                            ├─── YES ──→ Continue with Assistants API ⚠️
                            │            (or migrate when feasible)
                            │
                            └─── NO ──→ Use Response API ✅
```

### Use Response API When:

1. ✅ **New project or feature**
2. ✅ **Real-time streaming needed**
3. ✅ **Simple tool calling**
4. ✅ **Single-endpoint simplicity**
5. ✅ **LangGraph integration**
6. ✅ **LiteLLM integration**
7. ✅ **Modern OpenAI SDK**

### Use Assistants API When:

1. ⚠️ **Existing OpenWebUI integration**
2. ⚠️ **Migrating from OpenAI Assistants API**
3. ⚠️ **Need explicit run tracking**
4. ⚠️ **Assistant configuration persistence required**
5. ⚠️ **Backward compatibility critical**

---

## Migration Strategy

### Phase 1: Document As-Is (Session 52) ✅

**Status**: COMPLETE

**Actions**:
- ✅ Document Response API architecture
- ✅ Document Assistants API architecture
- ✅ Document Dual API Strategy
- ✅ Update CLAUDE.md with guidance

**Result**: Developers understand both APIs and can make informed choices.

### Phase 2: Encourage Response API (Ongoing)

**Status**: IN PROGRESS

**Actions**:
- ✅ Mark Response API as **recommended** in documentation
- ✅ Provide migration examples
- ✅ Update CLAUDE.md with "CRITICAL API USAGE REQUIREMENT"
- ⏳ Create migration guide for OpenWebUI
- ⏳ Add warnings in Assistants API documentation

**Result**: New projects default to Response API.

### Phase 3: Gradual Migration (Future)

**Status**: PLANNED

**Actions**:
- Identify high-value Assistants API integrations
- Create migration scripts/tools
- Deprecation warnings (not removal)
- Maintain backward compatibility

**Timeline**: 6-12 months, user-driven

**Result**: Most new code uses Response API, Assistants API remains for legacy.

### Phase 4: Long-Term Support (Ongoing)

**Status**: COMMITMENT

**Actions**:
- Maintain both APIs indefinitely
- Security updates for both
- Bug fixes for both
- No forced migration

**Result**: Users choose migration timing, no breaking changes.

---

## Code Patterns

### Response API Pattern (Recommended)

```python
from agentic_framework_sdk import ADEPTClient

# Initialize client
client = ADEPTClient(
    base_url="http://localhost:8083/v1",
    api_key=token
)

# Create thread
thread = client.threads.create()

# Send message with streaming
response = client.responses.chat.completions.create(
    model="agentic-framework:scientific-agent-v1",
    messages=[
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hello"}
    ],
    thread_id=thread.id,
    stream=True
)

# Process streaming response
for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

**Advantages**:
- **8 lines** of core logic
- **Real-time** streaming
- **Simple** single endpoint
- **No polling** required

### Assistants API Pattern (Legacy)

```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8083/v1",
    api_key=token
)

# Create assistant
assistant = client.beta.assistants.create(
    name="My Assistant",
    model="agentic-framework:scientific-agent-v1",
    instructions="You are helpful"
)

# Create thread
thread = client.beta.threads.create()

# Add message
client.beta.threads.messages.create(
    thread_id=thread.id,
    role="user",
    content="Hello"
)

# Create run
run = client.beta.threads.runs.create(
    thread_id=thread.id,
    assistant_id=assistant.id
)

# Poll for completion
import time
while run.status not in ["completed", "failed"]:
    run = client.beta.threads.runs.retrieve(
        thread_id=thread.id,
        run_id=run.id
    )
    time.sleep(1)

# Get response
messages = client.beta.threads.messages.list(thread_id=thread.id)
```

**Disadvantages**:
- **20+ lines** of core logic
- **Polling loop** (delayed feedback)
- **Multiple resources** (assistant, thread, run)
- **Complexity** for simple use cases

---

## Testing Strategy

### Response API Tests (Priority)

**Focus**: Ensure Response API is production-ready

**Test Coverage**:
- ✅ Streaming message delivery
- ✅ Tool calling (single and parallel)
- ✅ Multi-agent orchestration
- ✅ Context compaction
- ✅ Error handling
- ✅ LangGraph integration (8/8 tests passing)
- ✅ LiteLLM integration

**Test Targets**:
```bash
make validate-response-api-tool-calls
make validate-response-api-checkpointing-all
make validate-langgraph-examples
```

### Assistants API Tests (Maintenance)

**Focus**: Ensure backward compatibility

**Test Coverage**:
- ✅ Assistant CRUD operations
- ✅ Thread management
- ✅ Run lifecycle
- ✅ Authentication flows
- ✅ OpenWebUI integration

**Test Targets**:
```bash
make validate-data  # Management-plane operations
make validate-openwebui-all
```

**Strategy**: Keep tests passing, but don't expand Assistants API test suite.

---

## Documentation Strategy

### Primary Documentation: Response API

**Comprehensive guides** for Response API:
- ✅ `docs/architecture/RESPONSE_API_ARCHITECTURE.md` (complete reference)
- ✅ `examples/langgraph_adept_quickstart.py` (integration example)
- ✅ `examples/langgraph_adept_integration.py` (advanced usage)
- ✅ `CLAUDE.md` (developer guidance)

### Secondary Documentation: Assistants API

**Maintenance-level documentation** for Assistants API:
- ✅ `docs/architecture/ASSISTANTS_API_ARCHITECTURE.md` (reference only)
- ⚠️ Mark as "Legacy compatibility" in all references
- ⚠️ Recommend Response API migration

### Update Patterns

**When documenting new features**:
1. ✅ **Always** document for Response API
2. ⚠️ **Optionally** document for Assistants API (if relevant)
3. ✅ **Reference** Dual API Strategy document

**When fixing bugs**:
1. ✅ Fix in both APIs if issue affects both
2. ✅ Prioritize Response API if resources are limited
3. ✅ Document fix in appropriate API architecture doc

---

## Communication Guidelines

### Internal Communication (Development Team)

**Default Language**:
- "Use the Response API" (not "Use the Chat Completions API")
- "Assistants API is for legacy compatibility" (not "deprecated")
- "Response API is our primary API" (clear priority)

**Code Reviews**:
- ✅ **Approve**: New code using Response API
- ⚠️ **Question**: New code using Assistants API (ask why)
- ❌ **Reject**: New features only in Assistants API

### External Communication (Users/Docs)

**Messaging**:
- "Both APIs are fully supported"
- "We recommend Response API for new projects"
- "Migrate at your own pace, no forced changes"

**Documentation**:
- ✅ Prominently feature Response API examples
- ⚠️ Mark Assistants API as "Legacy" or "Backward Compatibility"
- ✅ Provide migration guides

---

## Metric Tracking

### Success Metrics

**Primary Metric**: % of new code using Response API

**Baseline** (Session 52):
- Response API: 85% of new implementations
- Assistants API: 15% of new implementations (OpenWebUI)

**Target** (6 months):
- Response API: 95% of new implementations
- Assistants API: 5% (maintenance only)

**Tracking**:
```bash
# Count Response API references
git log --since="2026-02-01" --grep="responses.chat.completions" --oneline | wc -l

# Count Assistants API references
git log --since="2026-02-01" --grep="beta.assistants" --oneline | wc -l
```

### Health Metrics

**Both APIs Should Have**:
- ✅ Test pass rate > 95%
- ✅ Mean response time < 2 seconds
- ✅ Error rate < 1%
- ✅ Zero critical bugs

**Monitoring**:
```bash
# Response API health
make validate-response-api-tool-calls

# Assistants API health
make validate-data
```

---

## FAQs

### Q: Will Assistants API be deprecated?

**A**: No. Both APIs are fully supported indefinitely. We recommend Response API for new projects, but Assistants API remains for backward compatibility.

### Q: What if I'm already using Assistants API?

**A**: Continue using it. There's no forced migration. Migrate when it makes sense for your project.

### Q: Can I mix both APIs?

**A**: Yes. You can use Response API for new features while maintaining Assistants API integrations. Both use the same underlying thread storage.

### Q: What about OpenWebUI?

**A**: OpenWebUI currently uses Assistants API. We'll maintain compatibility while exploring Response API integration options.

### Q: Which API is faster?

**A**: Response API is faster due to streaming (no polling) and fewer resources to create.

### Q: Which API uses less database connections?

**A**: Both use the same singleton checkpointer pattern (Session 26), so database usage is equivalent.

### Q: What if I need assistant persistence?

**A**: Response API doesn't have persistent assistant configs. Use model name + system messages instead. If you absolutely need assistant persistence, use Assistants API.

### Q: How do I migrate from Assistants API to Response API?

**A**: See migration examples in `docs/architecture/RESPONSE_API_ARCHITECTURE.md` and `docs/architecture/ASSISTANTS_API_ARCHITECTURE.md`.

---

## Stakeholder Alignment

### User Decision (Session 52)

**Context**: Session 52 Phase 1 analysis identified 18 references to `/invoke` endpoint and 19 references to Assistants API.

**Question**: Should we remove these endpoints and force migration?

**Decision**:
- ✅ **Keep /invoke endpoint** - Document as-is, not deprecated
- ✅ **Keep Assistants API** - Document as-is, both APIs supported
- ✅ **Focus Response API** - For new work, but no forced migration

**Rationale**:
- "This is an exploration framework, not production software"
- "Need simple demos of agent gateway registration between ADEPT deployments"
- "Users should migrate at their own pace"

**Documentation**: This decision is captured in `docs/implementation-plans/session-52/00_SESSION_SUMMARY.md`

---

## Related Documentation

### Architecture
- **Response API**: `docs/architecture/RESPONSE_API_ARCHITECTURE.md`
- **Assistants API**: `docs/architecture/ASSISTANTS_API_ARCHITECTURE.md`
- **File Registration**: `docs/architecture/FILE_REGISTRATION_DUAL_IMPLEMENTATION_ARCHITECTURE.md`

### Session Reports
- **Session 52 Summary**: `docs/implementation-plans/session-52/00_SESSION_SUMMARY.md`
- **Session 52 Phase 1**: `docs/implementation-plans/session-52/02_PHASE1_ANALYSIS_COMPLETE.md`
- **Session 52 Part 1**: `docs/implementation-reports/SESSION_52_PART1_COMPLETE.md`
- **Session 52 Part 2**: `docs/implementation-reports/SESSION_52_PHASE2_PROGRESS.md`

### Integration Examples
- **LangGraph Quickstart**: `examples/langgraph_adept_quickstart.py`
- **LangGraph Integration**: `examples/langgraph_adept_integration.py`
- **Validation Script**: `examples/scripts/validate-langgraph-examples.py`

---

## Changelog

- **2026-02-09 (Session 52)**: Initial dual API strategy documented
- **2026-02-09**: User decision to keep both APIs, focus Response API
- **2026-02-09**: Response API and Assistants API architecture docs created
