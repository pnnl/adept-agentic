# Globus Tool Prompt Examples

Natural language prompts for exercising the 28 Globus MCP tools via the ADEPT Response API or agentic CLI.

**Date**: 2026-03-31
**Tools**: 28 (Transfer: 11, Search: 6, Compute: 5, Flows: 4, Groups: 2)
**Auth**: Dual mode — user token delegation (per-user) or client credentials (service-level)

---

## 1. Transfer Workflows (11 tools)

### Basic File Operations

```
List the contents of /shared/data/ on Globus endpoint ddb59aef-6d04-11e5-ba46-22000b92c6ec
```
*Tool: `globus_list_directory_tool`*

```
Create a new directory /results/experiment-2026-03/ on endpoint abc-123-def
```
*Tool: `globus_mkdir_tool`*

```
Rename /shared/data/old_name.csv to new_name.csv on endpoint abc-123-def
```
*Tool: `globus_rename_tool`*

### Data Transfer

```
Transfer all files from endpoint A path /results/run1/ to endpoint B path /incoming/run1/
Use source endpoint ddb59aef-6d04-11e5-ba46-22000b92c6ec and destination endpoint ddb59af0-6d04-11e5-ba46-22000b92c6ec.
```
*Tool: `globus_submit_transfer_tool`*

```
Delete the files output_1.csv and output_2.csv from endpoint abc-123 path /tmp/cleanup/
```
*Tool: `globus_submit_delete_tool`*

### Task Management

```
Check the status of Globus transfer task 12345678-abcd-1234-abcd-123456789012
```
*Tool: `globus_get_task_tool`*

```
Show me my last 5 Globus transfer tasks
```
*Tool: `globus_list_tasks_tool`*

```
Cancel task 12345678-abcd — it's transferring to the wrong endpoint
```
*Tool: `globus_cancel_task_tool`*

```
Wait for task 12345678-abcd to complete, checking every 10 seconds for up to 5 minutes
```
*Tool: `globus_wait_for_task_tool`*

### Endpoint Discovery

```
Search for Globus endpoints related to "PNNL" or "Pacific Northwest"
```
*Tool: `globus_search_endpoints_tool`*

```
Find the Globus Tutorial Endpoint so I can test a transfer
```
*Tool: `globus_search_endpoints_tool`*

---

## 2. Search Workflows (6 tools)

### Querying Indexes

```
Search the Materials Data Facility (index 1a57bbe5-5272-477f-9d31-343b8258b7a5) for "copper oxide" datasets, limit 10 results
```
*Tool: `globus_search_query_tool`*

```
Scroll through all entries in search index idx-456 starting from marker "abc123", 50 entries per page
```
*Tool: `globus_search_scroll_tool`*

### Index Management

```
Ingest these 3 entries into search index idx-456:
- Subject "experiment-001": {"title": "Copper Oxide XRD", "author": "Smith", "date": "2026-03-30"}
- Subject "experiment-002": {"title": "Iron Sulfide SAXS", "author": "Jones", "date": "2026-03-30"}
- Subject "experiment-003": {"title": "Gold Nanoparticle TEM", "author": "Lee", "date": "2026-03-30"}
```
*Tool: `globus_ingest_entries_tool`*

```
Get the full metadata for subject "experiment-001" in search index idx-456
```
*Tool: `globus_get_search_subject_tool`*

```
Delete subject "experiment-001" from search index idx-456 — the data was retracted
```
*Tool: `globus_delete_search_subject_tool`*

```
List all Globus Search indices I have access to
```
*Tool: `globus_list_search_indices_tool`*

---

## 3. Compute Workflows (5 tools) — DOE LCF Federation

### Submitting Remote Functions

```
Submit function func-789 to the ALCF Polaris compute endpoint ep-alcf-uuid with arguments [100, 200, 300]
```
*Tool: `globus_compute_submit_tool`*

```
Run the data analysis function (func-analysis-uuid) on NERSC Perlmutter endpoint ep-nersc-uuid with kwargs {"input_path": "/global/cfs/data/experiment.h5", "output_path": "/global/cfs/results/"}
```
*Tool: `globus_compute_submit_tool`*

### Task Monitoring

```
Check if my compute task task-abc-123 has completed and get the result
```
*Tool: `globus_compute_get_task_tool`*

### Endpoint Management

```
Get the status of the ALCF Polaris Globus Compute endpoint ep-alcf-uuid — is it online?
```
*Tool: `globus_compute_get_endpoint_tool`*

```
List all Globus Compute endpoints available to me
```
*Tool: `globus_compute_list_endpoints_tool`*

### Function Registration

```
Register this Python function for remote execution on Globus Compute:

def analyze_spectra(file_path, threshold=0.5):
    import numpy as np
    data = np.load(file_path)
    peaks = data[data > threshold]
    return {"peak_count": len(peaks), "max_intensity": float(peaks.max())}
```
*Tool: `globus_compute_register_function_tool`*

---

## 4. Flows Workflows (4 tools)

### Flow Discovery

```
List my available Globus automation flows
```
*Tool: `globus_list_flows_tool`*

### Flow Execution

```
Run the "Data Pipeline" flow (flow-id-123) with these inputs:
- source_endpoint: ep-pnnl-uuid
- destination_endpoint: ep-alcf-uuid
- source_path: /data/experiment-2026/
- destination_path: /eagle/project/incoming/
Label it "PNNL-to-ALCF data staging for March 2026 experiment"
```
*Tool: `globus_run_flow_tool`*

### Flow Monitoring

```
Check the status of flow run run-uuid-456 — has it completed all steps?
```
*Tool: `globus_get_flow_run_tool`*

```
Cancel flow run run-uuid-456 — the destination endpoint went offline
```
*Tool: `globus_cancel_flow_run_tool`*

---

## 5. Groups Workflows (2 tools)

```
List all Globus groups I belong to
```
*Tool: `globus_list_groups_tool`*

```
Get details about group grp-pnnl-scientists — how many members does it have?
```
*Tool: `globus_get_group_tool`*

---

## 6. Multi-Tool Workflow Prompts

These prompts exercise multiple tools in a single conversation turn.

### Data Staging + Compute (Transfer → Wait → Compute)

```
I need to run an analysis on ALCF Polaris. First, transfer my input data from PNNL endpoint
(ep-pnnl-uuid) path /data/experiment.h5 to ALCF endpoint (ep-alcf-uuid) path /eagle/incoming/.
Wait for the transfer to complete, then submit function func-analyze-uuid to the ALCF compute
endpoint (ep-compute-uuid) with kwargs {"input": "/eagle/incoming/experiment.h5"}.
Report the compute task ID when submitted.
```

### Search + Transfer (Discover → Stage)

```
Search the Materials Data Facility for "lithium battery cathode" datasets published in 2025.
For the first result, find which Globus endpoint hosts the data and list the files in its
data directory. Then transfer the .h5 files to my PNNL endpoint (ep-pnnl-uuid) path /incoming/mdf/.
```

### Endpoint Discovery + Directory Listing

```
Find a Globus endpoint at EMSL, list the /shared/ directory, and tell me what datasets
are available. Search for endpoints with "EMSL" in the name.
```

### Flow + Monitoring

```
Run the "Multi-Facility Pipeline" flow (flow-multi-uuid) with source=ep-pnnl and dest=ep-alcf.
Then check the run status every 30 seconds until it completes or fails. Report the final status
and any error details.
```

---

## 7. Auth Context Prompts

These prompts demonstrate the dual auth modes.

### User Token Delegation (per-user Globus access)

```
Using my Globus identity, list my personal Globus groups and check which compute endpoints
I have access to at ALCF. Use my delegated token for these operations.
```
*Auth: User's Keycloak JWT → RFC 8693 token exchange → Globus AccessTokenAuthorizer*

### Service Credentials (system-level operations)

```
As the ADEPT service account, check the status of the PNNL shared data endpoint and verify
it's online and accepting transfers.
```
*Auth: ACADEMY_GLOBUS_CLIENT_ID/SECRET → ClientCredentialsAuthorizer*

---

## 8. Testing These Prompts

### Via Response API (curl)

```bash
# Get JWT token
TOKEN=$(curl -s -X POST http://keycloak:8180/realms/master/protocol/openid-connect/token \
  -d "grant_type=password&client_id=login-client&username=admin&password=admin" | jq -r '.access_token')

# Send prompt
curl -X POST http://agent_gateway:8081/v1/responses/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agentic-framework:scientific-agent-v1",
    "messages": [{"role": "user", "content": "Search for Globus endpoints related to PNNL"}],
    "stream": false,
    "max_tokens": 2000
  }'
```

### Via agentic CLI

```bash
agentic chat --message "List my available Globus automation flows" \
  --username admin --password admin
```

### Via Smoke Test

```bash
cd examples/academy_mcp_server
make smoke-test
```
