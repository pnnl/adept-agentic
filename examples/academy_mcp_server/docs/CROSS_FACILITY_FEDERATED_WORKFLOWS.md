# Cross-Facility Federated Workflows: Auth, Compute, and Data Flows

**Date**: 2026-03-30
**Branch**: `fix-nginx-streaming-for-openai-endpoint-add-rc-famous`
**Related**: [A2A Workshop](../../a2a-workshop/README.md) | [Globus Tools Proposal](GLOBUS_TOOLS_PROPOSAL.md) | [Session Tracker](SESSION_TRACKER_GLOBUS_SPIFFE_SLURM.md)

---

## Facility Overview

Four facilities participate in the federated ADEPT ecosystem. Each has distinct capabilities and connectivity patterns.

```mermaid
graph TB
    subgraph "Facility 1: EMSL On-Premise"
        EMSL_ADEPT["ADEPT Stack<br/>(Full 3-Tier)"]
        EMSL_INSTRUMENTS["Instruments<br/>(Mass Spec, NMR, Cryo-EM)"]
    end

    subgraph "Facility 2: AWS Cloud"
        AWS_ADEPT["ADEPT Stack<br/>(Full 3-Tier)"]
        AWS_GPU["GPU Instances<br/>(p4d, g5)"]
    end

    subgraph "Facility 3: RC Compute Facility"
        RC_ADEPT["ADEPT Stack<br/>(Full 3-Tier)"]
        RC_SLURM["Slurm HPC Cluster"]
        RC_GLOBUS_EP["Globus Endpoint<br/>(Mapped Collection)"]
    end

    subgraph "Facility 4: ALCF (Argonne)"
        ALCF_GLOBUS_EP["Globus Endpoint<br/>(Polaris/Aurora)"]
        ALCF_COMPUTE["Globus Compute<br/>Endpoint"]
        ALCF_ACADEMY["Academy Agents<br/>(via ADEPT)"]
    end

    EMSL_ADEPT <-->|"A2A Protocol<br/>(HTTPS)"| AWS_ADEPT
    EMSL_ADEPT <-->|"A2A Protocol<br/>(HTTPS)"| RC_ADEPT
    AWS_ADEPT <-->|"A2A Protocol<br/>(HTTPS)"| RC_ADEPT
    RC_ADEPT -->|"Slurm REST API<br/>(JWT Auth)"| RC_SLURM
    RC_ADEPT -->|"Globus SDK<br/>(OAuth2)"| RC_GLOBUS_EP
    RC_GLOBUS_EP <-->|"Globus Transfer<br/>(GridFTP/HTTPS)"| ALCF_GLOBUS_EP
    RC_ADEPT -->|"Globus Compute<br/>(OAuth2)"| ALCF_COMPUTE
    AWS_ADEPT -->|"Globus SDK<br/>(Token Exchange)"| ALCF_COMPUTE
```

### Facility Capabilities Matrix

| Capability | EMSL (On-Prem) | AWS Cloud | RC (HPC) | ALCF (Argonne) |
|-----------|:-:|:-:|:-:|:-:|
| ADEPT Stack (3-Tier) | Y | Y | Y | Y (Academy) |
| A2A Gateway Mesh | Y | Y | Y | -- |
| Globus Transfer Endpoint | -- | -- | Y | Y |
| Globus Compute Endpoint | -- | -- | -- | Y |
| Slurm HPC Cluster | -- | -- | Y | -- |
| SPIFFE/SPIRE Workload Identity | -- | -- | Y | -- |
| Keycloak IdP | Y | Y | Y | Y |
| Globus Auth Federation | -- | -- | Y | Y |

### Identity Chain (End-to-End)

```mermaid
flowchart LR
    A["Institution<br/>SAML/OIDC"] --> B["Globus Auth<br/>(Federation Broker)"]
    B --> C["Keycloak<br/>(ADEPT IdP)"]
    C --> D["ADEPT JWT<br/>(Agent Gateway)"]
    D --> E["IdentityMapper"]
    E --> F["Slurm Username"]
    E --> G["Globus Access Token<br/>(Token Exchange)"]
```

---

## Scenario 1: EMSL to AWS Cloud (Pure ADEPT A2A)

**Facilities**: EMSL (on-premise) + AWS Cloud (ADEPT-only)
**Protocol**: A2A over HTTPS
**Use Case**: A researcher at EMSL needs GPU-accelerated inference (e.g., protein structure prediction) available only on AWS GPU instances. EMSL's ADEPT delegates the task to AWS ADEPT via A2A.

### 1A. Auth Flow

```mermaid
sequenceDiagram
    participant User as Researcher<br/>(EMSL)
    participant KC_E as Keycloak<br/>(EMSL)
    participant GW_E as Agent Gateway<br/>(EMSL)
    participant REG_E as Gateway Registry<br/>(EMSL)
    participant GW_A as Agent Gateway<br/>(AWS)
    participant KC_A as Keycloak<br/>(AWS)
    participant ORCH_A as Orchestration<br/>(AWS)

    Note over User,KC_E: Step 1: User authenticates locally
    User->>KC_E: ROPC or OIDC login
    KC_E-->>User: Keycloak JWT (EMSL)

    Note over GW_E,REG_E: Step 2: EMSL discovers AWS peer
    GW_E->>REG_E: GET /v1/gateway-registry?tags=gpu
    REG_E-->>GW_E: [{alias: "aws-gateway", public_url: "https://aws-ip/v1"}]

    Note over GW_E,GW_A: Step 3: A2A delegation with dual tokens
    GW_E->>GW_A: POST /v1/responses/chat/completions<br/>Authorization: Bearer <A2A_SERVICE_TOKEN><br/>Body: {user_token: "<EMSL_JWT>", messages: [...]}

    Note over GW_A,KC_A: Step 4: AWS validates A2A service token
    GW_A->>KC_A: Validate A2A_SERVICE_TOKEN<br/>(or check Redis/SERVICE_API_KEYS)
    KC_A-->>GW_A: Valid (groups: gateway-service)

    Note over GW_A,KC_A: Step 5: AWS validates forwarded user token
    GW_A->>GW_A: validate_jwt_multi_stack(EMSL_JWT)
    GW_A->>GW_A: kid not in local JWKS
    GW_A->>KC_E: Fetch A2A_TRUSTED_PEER_JWKS_URLS<br/>(EMSL Keycloak JWKS endpoint)
    KC_E-->>GW_A: JWKS with EMSL signing keys
    GW_A->>GW_A: Verify EMSL_JWT signature ✓

    Note over GW_A,ORCH_A: Step 6: Request proceeds with user context
    GW_A->>ORCH_A: Forward request<br/>X-User-ID: researcher@emsl<br/>X-User-Groups: notebook-users
    ORCH_A-->>GW_A: Streaming response (SSE)
    GW_A-->>GW_E: Forward SSE stream
    GW_E-->>User: Final response
```

**Key Auth Mechanisms**:
- **A2A service token**: Long-lived (365-day) bearer token with `gateway-service` group, generated via `01_generate_a2a_token.sh`
- **Cross-VM JWKS federation**: `A2A_TRUSTED_PEER_JWKS_URLS` in AWS `.env` points to EMSL's Keycloak JWKS endpoint
- **Dual token pattern**: Service token authenticates gateway-to-gateway; user token preserves researcher identity

### 1B. Data Flow

```mermaid
sequenceDiagram
    participant User as Researcher
    participant ORCH_E as Orchestration<br/>(EMSL)
    participant MCP_E as MCP Server<br/>(EMSL)
    participant GW_E as Agent Gateway<br/>(EMSL)
    participant GW_A as Agent Gateway<br/>(AWS)
    participant ORCH_A as Orchestration<br/>(AWS)
    participant MCP_A as MCP Server<br/>(AWS)

    Note over User,MCP_E: Step 1: User uploads data locally
    User->>ORCH_E: POST /v1/files (upload dataset.csv)
    ORCH_E->>MCP_E: Store in /data/uploaded_files/{session}/

    Note over ORCH_E,GW_A: Step 2: A2A delegation includes file content
    ORCH_E->>GW_E: A2A delegate with file reference
    GW_E->>GW_A: POST /v1/responses/chat/completions<br/>messages: [{role: "user", content: "Analyze attached data..."}]

    Note over GW_A,MCP_A: Step 3: AWS processes with GPU tools
    GW_A->>ORCH_A: Forward to orchestration
    ORCH_A->>MCP_A: Execute GPU inference<br/>(sandbox_mcp_server)
    MCP_A-->>ORCH_A: Results (predictions, plots)

    Note over ORCH_A,User: Step 4: Results stream back via A2A
    ORCH_A-->>GW_A: SSE stream with results
    GW_A-->>GW_E: Forward SSE
    GW_E-->>ORCH_E: A2A response
    ORCH_E-->>User: Display results
```

**Data Movement**: File content is embedded in A2A message bodies (no shared filesystem). For large datasets, Scenario 3 (Globus Transfer) is preferred.

### 1C. Compute Flow

```mermaid
sequenceDiagram
    participant User as Researcher
    participant Agent_E as ADEPT Agent<br/>(EMSL)
    participant Registry as Gateway Registry<br/>(EMSL)
    participant Agent_A as ADEPT Agent<br/>(AWS)
    participant Sandbox as Sandbox MCP<br/>(AWS GPU)

    Note over User,Agent_E: Step 1: User requests GPU workload
    User->>Agent_E: "Run AlphaFold prediction<br/>on this protein sequence"

    Note over Agent_E,Registry: Step 2: Agent discovers GPU peer
    Agent_E->>Registry: Query peers with tag:gpu
    Registry-->>Agent_E: aws-gateway (capabilities: [gpu, sandbox])

    Note over Agent_E,Agent_A: Step 3: Delegate to AWS
    Agent_E->>Agent_A: A2A delegate:<br/>"Run AlphaFold on sequence MKWVTF..."

    Note over Agent_A,Sandbox: Step 4: AWS executes locally
    Agent_A->>Sandbox: execute_code(python_script,<br/>image="alphafold:latest")
    Sandbox-->>Agent_A: PDB structure file + confidence scores

    Note over Agent_A,User: Step 5: Results return via A2A
    Agent_A-->>Agent_E: A2A response with results
    Agent_E-->>User: "AlphaFold prediction complete.<br/>pLDDT: 92.3, structure attached."
```

**Compute Characteristics**:
- No Globus involvement (pure ADEPT A2A)
- AWS sandbox_mcp_server provides isolated Docker execution with GPU passthrough
- Suitable for workloads under ~100MB data transfer

---

## Scenario 2: EMSL to RC (ADEPT A2A + Slurm HPC)

**Facilities**: EMSL (on-premise) + RC (ADEPT + Slurm HPC)
**Protocol**: A2A over HTTPS + Slurm REST API
**Use Case**: A researcher at EMSL submits a large-scale molecular dynamics simulation to RC's Slurm HPC cluster. The job requires hundreds of CPU cores and runs for hours.

### 2A. Auth Flow

```mermaid
sequenceDiagram
    participant User as Researcher<br/>(EMSL)
    participant KC_E as Keycloak<br/>(EMSL)
    participant GW_E as Agent Gateway<br/>(EMSL)
    participant GW_R as Agent Gateway<br/>(RC)
    participant NGINX_S as slurm_nginx_proxy<br/>(RC)
    participant OAUTH as oauth2_proxy<br/>(RC)
    participant MCP_S as Slurm MCP Server<br/>(RC)
    participant IDMAP as IdentityMapper<br/>(RC)
    participant SPIRE as SPIRE Agent<br/>(RC)
    participant BRIDGE as JWT Bridge<br/>(RC)
    participant SLURM as slurmrestd<br/>(RC)

    Note over User,KC_E: Step 1: User authenticates at EMSL
    User->>KC_E: ROPC login
    KC_E-->>User: Keycloak JWT (sub: researcher@emsl)

    Note over GW_E,GW_R: Step 2: A2A delegation to RC
    GW_E->>GW_R: A2A delegate<br/>Service token + EMSL user JWT

    Note over GW_R,OAUTH: Step 3: RC validates and forwards
    GW_R->>GW_R: Validate EMSL JWT via peer JWKS
    GW_R->>NGINX_S: Forward to Slurm proxy
    NGINX_S->>OAUTH: JWT Bearer passthrough<br/>(SKIP_JWT_BEARER_TOKENS=true)

    Note over MCP_S,IDMAP: Step 4: Identity mapping
    OAUTH->>MCP_S: Request with X-Auth-Request-User header
    MCP_S->>IDMAP: Resolve identity
    IDMAP->>IDMAP: Priority chain:<br/>1. slurm_username claim? No<br/>2. Static map? researcher@emsl → rsmith<br/>3. Email prefix? rsmith

    Note over SPIRE,BRIDGE: Step 5: SPIFFE workload identity (if enabled)
    MCP_S->>SPIRE: Fetch JWT-SVID<br/>(audience: slurmrestd)
    SPIRE-->>MCP_S: RS256 JWT-SVID<br/>(sub: spiffe://pnnl.adept.slurm/slurm-mcp-server)
    MCP_S->>BRIDGE: translate(jwt_svid)
    BRIDGE->>BRIDGE: Decode RS256 → Map SPIFFE ID → Mint HS256
    BRIDGE-->>MCP_S: HS256 JWT (sun: rsmith)

    Note over MCP_S,SLURM: Step 6: Job submission as mapped user
    MCP_S->>SLURM: POST /slurm/v0.0.41/job/submit<br/>Authorization: Bearer <HS256_JWT><br/>X-SLURM-USER-NAME: rsmith
    SLURM-->>MCP_S: {job_id: 12345}
    MCP_S-->>User: "Job 12345 submitted to RC cluster"
```

**Key Auth Mechanisms**:
- **A2A service token + JWKS federation**: Same as Scenario 1 for gateway-to-gateway
- **IdentityMapper 6-level chain**: Maps Globus/Keycloak identity to local Slurm username
- **SPIFFE JWT-SVID**: Workload identity from SPIRE agent (if `SPIFFE_ENABLED=true`)
- **JWT Bridge**: Translates RS256 SPIFFE JWT to HS256 Slurm JWT (slurmrestd limitation)
- **oauth2_proxy passthrough**: `SKIP_JWT_BEARER_TOKENS=true` allows Bearer tokens through nginx

### 2B. Data Flow

```mermaid
sequenceDiagram
    participant User as Researcher
    participant Agent_E as ADEPT Agent<br/>(EMSL)
    participant Agent_R as ADEPT Agent<br/>(RC)
    participant MCP_S as Slurm MCP<br/>(RC)
    participant SLURM as Slurm Cluster<br/>(RC)
    participant FS as Shared Filesystem<br/>(/scratch)

    Note over User,Agent_E: Step 1: User provides input files
    User->>Agent_E: "Run GROMACS simulation<br/>with these topology files"

    Note over Agent_E,Agent_R: Step 2: A2A delegation with data
    Agent_E->>Agent_R: A2A delegate with file content<br/>embedded in message body

    Note over Agent_R,FS: Step 3: Stage data to scratch
    Agent_R->>FS: Write input files to<br/>/scratch/rsmith/session_xxx/

    Note over MCP_S,SLURM: Step 4: Submit Slurm job
    Agent_R->>MCP_S: slurm_submit_job<br/>(script refs /scratch/rsmith/session_xxx/)
    MCP_S->>SLURM: POST /slurm/v0.0.41/job/submit
    SLURM-->>MCP_S: {job_id: 12345}

    Note over SLURM,FS: Step 5: Job runs on compute nodes
    SLURM->>FS: Read inputs from /scratch/
    SLURM->>FS: Write outputs to /scratch/rsmith/results/

    Note over Agent_R,User: Step 6: Collect results
    Agent_R->>MCP_S: slurm_get_job_details(12345)
    MCP_S-->>Agent_R: COMPLETED
    Agent_R->>FS: Read /scratch/rsmith/results/
    Agent_R-->>Agent_E: A2A response with results
    Agent_E-->>User: "Simulation complete. Energy: -42.3 kJ/mol"
```

**Data Movement**: For datasets small enough to embed in A2A messages (~100MB), data flows through message bodies. For larger datasets, see Scenario 3 which uses Globus Transfer.

### 2C. Compute Flow

```mermaid
sequenceDiagram
    participant User as Researcher
    participant Agent_E as ADEPT Agent<br/>(EMSL)
    participant Registry as Gateway Registry<br/>(EMSL)
    participant Agent_R as ADEPT Agent<br/>(RC)
    participant MCP_S as Slurm MCP<br/>(RC)
    participant SLURM as slurmrestd<br/>(RC)

    Note over User,Agent_E: Step 1: Request HPC workload
    User->>Agent_E: "Run GROMACS MD simulation<br/>with 256 cores for 48 hours"

    Note over Agent_E,Registry: Step 2: Discover HPC peer
    Agent_E->>Registry: Query peers with tag:hpc,slurm
    Registry-->>Agent_E: rc-gateway (capabilities: [hpc, slurm, gpu])

    Note over Agent_E,Agent_R: Step 3: Delegate to RC
    Agent_E->>Agent_R: A2A delegate: "Submit GROMACS job..."

    Note over Agent_R,SLURM: Step 4: RC submits to Slurm
    Agent_R->>MCP_S: slurm_submit_job({<br/>  script: "#!/bin/bash\n#SBATCH -N 8\n#SBATCH -t 48:00:00\ngmx mdrun ...",<br/>  partition: "normal"<br/>})
    MCP_S->>SLURM: POST /slurm/v0.0.41/job/submit
    SLURM-->>MCP_S: {job_id: 12345}

    Note over Agent_R,SLURM: Step 5: Poll for completion
    loop Every 60 seconds
        Agent_R->>MCP_S: slurm_get_job_details(12345)
        MCP_S->>SLURM: GET /slurm/v0.0.41/job/12345
        SLURM-->>MCP_S: {state: "RUNNING", elapsed: "12:34:56"}
    end
    SLURM-->>MCP_S: {state: "COMPLETED"}

    Note over Agent_R,User: Step 6: Return results
    Agent_R-->>Agent_E: "Job 12345 completed in 36h 12m.<br/>Output: /scratch/rsmith/results/"
    Agent_E-->>User: Results summary
```

---

## Scenario 3: AWS Cloud to RC with Globus Data Staging

**Facilities**: AWS Cloud (ADEPT) + RC (ADEPT + Globus + Slurm)
**Protocol**: A2A + Globus Transfer + Slurm REST
**Use Case**: A cloud-based analysis pipeline needs to stage 500GB of genomics data from a Globus collection to RC's scratch filesystem, run a Nextflow pipeline on Slurm, then transfer results back to a cloud storage endpoint.

### 3A. Auth Flow

```mermaid
sequenceDiagram
    participant User as Researcher<br/>(AWS)
    participant KC_A as Keycloak<br/>(AWS)
    participant Agent_A as ADEPT Agent<br/>(AWS)
    participant GlobusAuth as Globus Auth
    participant KC_R as Keycloak<br/>(RC)
    participant Agent_R as ADEPT Agent<br/>(RC)
    participant GlobusMgr as GlobusClientManager<br/>(Academy MCP)

    Note over User,KC_A: Step 1: User authenticates (Globus-federated)
    User->>KC_A: OIDC login via Globus IdP
    KC_A->>GlobusAuth: OIDC Authorization Code Flow
    GlobusAuth-->>KC_A: id_token + refresh_token
    KC_A->>KC_A: Store Globus refresh_token<br/>(storeToken: true)
    KC_A-->>User: Keycloak JWT<br/>(claim: globus_identity)

    Note over Agent_A,KC_R: Step 2: A2A to RC with user context
    Agent_A->>Agent_R: A2A delegate<br/>(service token + user JWT)
    Agent_R->>Agent_R: Validate user JWT via peer JWKS

    Note over Agent_R,GlobusMgr: Step 3: Token exchange for Globus
    Agent_R->>KC_R: POST /token<br/>grant_type=urn:ietf:params:oauth:grant-type:token-exchange<br/>subject_token=<user_jwt><br/>requested_issuer=globus
    KC_R->>KC_R: Retrieve stored Globus refresh_token
    KC_R->>GlobusAuth: Refresh Globus access token
    GlobusAuth-->>KC_R: New Globus access_token<br/>(scoped: transfer.api.globus.org)
    KC_R-->>Agent_R: Globus access_token

    Note over GlobusMgr,GlobusMgr: Step 4: Globus SDK with user's token
    Agent_R->>GlobusMgr: get_transfer_client(user_token=globus_token)
    GlobusMgr->>GlobusMgr: AccessTokenAuthorizer(globus_token)
    GlobusMgr-->>Agent_R: TransferClient (user-scoped)
```

**Key Auth Mechanisms**:
- **Globus-federated Keycloak login**: User authenticates via institution SAML → Globus Auth → Keycloak OIDC IdP
- **RFC 8693 token exchange**: Keycloak exchanges user JWT for Globus access token using stored refresh token
- **User-scoped Globus operations**: All Globus API calls use the researcher's identity (data access governed by Globus ACLs)

### 3B. Data Flow

```mermaid
sequenceDiagram
    participant User as Researcher
    participant Agent_A as ADEPT Agent<br/>(AWS)
    participant Agent_R as ADEPT Agent<br/>(RC)
    participant Academy as Academy MCP<br/>(Globus Tools)
    participant GlobusAPI as Globus Transfer<br/>API
    participant SrcEP as Source Endpoint<br/>(Cloud Storage)
    participant DstEP as RC Endpoint<br/>(/scratch)
    participant MCP_S as Slurm MCP<br/>(RC)
    participant SLURM as Slurm Cluster

    Note over User,Agent_A: Step 1: User initiates pipeline
    User->>Agent_A: "Stage genomics data from<br/>NCBI collection to RC,<br/>run variant calling pipeline"

    Note over Agent_A,Agent_R: Step 2: A2A delegate to RC
    Agent_A->>Agent_R: A2A delegate with instructions

    Note over Agent_R,GlobusAPI: Step 3: Pre-job data staging via Globus
    Agent_R->>Academy: globus_search_endpoints("NCBI SRA")
    Academy-->>Agent_R: source_ep_uuid
    Agent_R->>Academy: globus_submit_transfer(<br/>  source=ncbi_ep,<br/>  dest=rc_ep,<br/>  items=[{"/sra/SRR12345/": "/scratch/user/sra/"}],<br/>  sync_level=checksum<br/>)
    Academy->>GlobusAPI: POST /v0.10/transfer
    GlobusAPI-->>Academy: {task_id: "transfer-uuid-1"}

    Note over Academy,DstEP: Step 4: Wait for staging completion
    Agent_R->>Academy: globus_wait_for_task("transfer-uuid-1", timeout=3600)
    GlobusAPI->>SrcEP: GridFTP/HTTPS transfer
    SrcEP->>DstEP: 500GB data staged to /scratch/
    Academy-->>Agent_R: SUCCEEDED (500GB, 45 min)

    Note over MCP_S,SLURM: Step 5: Submit Slurm job
    Agent_R->>MCP_S: slurm_submit_job(<br/>  script: "nextflow run variant_calling.nf<br/>    --input /scratch/user/sra/"<br/>)
    MCP_S->>SLURM: Submit job
    SLURM-->>MCP_S: {job_id: 67890}

    Note over SLURM,DstEP: Step 6: Job completes
    SLURM->>SLURM: Run pipeline (4 hours)
    SLURM-->>MCP_S: COMPLETED

    Note over Academy,SrcEP: Step 7: Post-job result transfer
    Agent_R->>Academy: globus_submit_transfer(<br/>  source=rc_ep,<br/>  dest=user_cloud_ep,<br/>  items=[{"/scratch/user/results/": "/results/variant_calling/"}]<br/>)
    Academy->>GlobusAPI: POST /v0.10/transfer
    GlobusAPI->>DstEP: Transfer results back
    DstEP->>SrcEP: Results to cloud storage
    Academy-->>Agent_R: SUCCEEDED

    Agent_R-->>Agent_A: "Pipeline complete. Results at /results/variant_calling/"
    Agent_A-->>User: Summary with result paths
```

**Data Staging Pattern**:
1. **Pre-job**: `globus_submit_transfer` → `globus_wait_for_task` → data on `/scratch`
2. **Job execution**: Slurm reads from `/scratch`, writes results to `/scratch`
3. **Post-job**: `globus_submit_transfer` → results back to user's endpoint

### 3C. Compute Flow

```mermaid
sequenceDiagram
    participant User as Researcher
    participant Agent_A as ADEPT Agent<br/>(AWS)
    participant Agent_R as ADEPT Agent<br/>(RC)
    participant Academy as Academy MCP<br/>(Globus Tools)
    participant MCP_S as Slurm MCP
    participant SLURM as slurmrestd

    Note over User,Agent_R: Steps 1-2: Auth + A2A (see 3A)
    User->>Agent_A: "Run variant calling on SRR12345"
    Agent_A->>Agent_R: A2A delegate

    Note over Agent_R,Academy: Step 3: Pre-job staging
    Agent_R->>Academy: globus_submit_transfer(...)
    Agent_R->>Academy: globus_wait_for_task(...)
    Academy-->>Agent_R: Data staged ✓

    Note over Agent_R,SLURM: Step 4: Orchestrate HPC job
    Agent_R->>MCP_S: slurm_submit_job(variant_calling.nf)
    MCP_S->>SLURM: Submit (256 cores, 8h walltime)
    SLURM-->>MCP_S: job_id: 67890

    Note over Agent_R,SLURM: Step 5: Monitor job
    loop Poll every 5 min
        Agent_R->>MCP_S: slurm_get_job_details(67890)
        MCP_S->>SLURM: GET job status
    end
    SLURM-->>MCP_S: COMPLETED

    Note over Agent_R,Academy: Step 6: Post-job collection
    Agent_R->>Academy: globus_submit_transfer(results back)
    Agent_R->>Academy: globus_wait_for_task(...)

    Agent_R-->>Agent_A: "Complete. VCF at /results/"
    Agent_A-->>User: Results summary
```

---

## Scenario 4: RC to ALCF (Globus Compute at DOE Facility)

**Facilities**: RC (ADEPT + Globus) + ALCF (Globus Compute endpoint on Polaris/Aurora)
**Protocol**: Globus SDK (Compute + Transfer)
**Use Case**: RC's ADEPT orchestrates a large-scale AI training job on ALCF's Polaris supercomputer using Globus Compute, with data staged via Globus Transfer.

### 4A. Auth Flow

```mermaid
sequenceDiagram
    participant User as Researcher<br/>(RC)
    participant KC_R as Keycloak<br/>(RC, Globus IdP)
    participant Agent_R as ADEPT Agent<br/>(RC)
    participant TokenExch as globus_token_exchange.py
    participant GlobusAuth as Globus Auth
    participant GlobusMgr as GlobusClientManager
    participant ALCF_EP as ALCF Globus<br/>Compute Endpoint

    Note over User,KC_R: Step 1: User logs in via Globus-federated Keycloak
    User->>KC_R: OIDC login (Globus IdP)
    KC_R-->>User: Keycloak JWT<br/>(globus_identity: user@anl.gov)

    Note over Agent_R,GlobusAuth: Step 2: Token exchange for Globus Compute scope
    Agent_R->>TokenExch: exchange_token(keycloak_jwt,<br/>scope="compute.api.globus.org")
    TokenExch->>KC_R: POST /token (grant_type=token-exchange)
    KC_R->>GlobusAuth: Refresh token for Compute scope
    GlobusAuth-->>KC_R: access_token (compute-scoped)
    KC_R-->>TokenExch: Globus Compute access_token
    TokenExch-->>Agent_R: Token ready

    Note over GlobusMgr,ALCF_EP: Step 3: Globus Compute client with user identity
    Agent_R->>GlobusMgr: get_compute_client(user_token=globus_token)
    Note over GlobusMgr: AccessTokenAuthorizer<br/>User's ALCF allocation identity
    GlobusMgr-->>Agent_R: ComputeClient

    Note over Agent_R,ALCF_EP: Step 4: Submit to ALCF endpoint
    Agent_R->>ALCF_EP: globus_compute_submit(<br/>  endpoint=alcf_polaris_uuid,<br/>  function=registered_func_uuid,<br/>  args={...}<br/>)
    Note over ALCF_EP: ALCF validates user's<br/>allocation via Globus identity
    ALCF_EP-->>Agent_R: {task_id: "compute-uuid"}
```

**Key Auth Mechanisms**:
- **Globus identity federation**: User's institutional identity → Globus Auth → Keycloak → ADEPT JWT
- **Token exchange for Compute scope**: RFC 8693 exchange gets Compute-scoped Globus token
- **ALCF allocation check**: Globus Compute endpoint validates user has active ALCF allocation via their Globus identity
- **No SPIFFE needed**: Globus Compute handles workload identity at the facility level

### 4B. Data Flow

```mermaid
sequenceDiagram
    participant Agent_R as ADEPT Agent<br/>(RC)
    participant Academy as Academy MCP<br/>(Globus Tools)
    participant GlobusXfer as Globus Transfer<br/>API
    participant RC_EP as RC Endpoint<br/>(/scratch)
    participant ALCF_EP as ALCF Endpoint<br/>(Eagle FS)
    participant GlobusComp as Globus Compute<br/>API
    participant Polaris as ALCF Polaris<br/>(Compute)

    Note over Agent_R,Academy: Step 1: Stage training data to ALCF
    Agent_R->>Academy: globus_submit_transfer(<br/>  source=rc_ep,<br/>  dest=alcf_eagle_ep,<br/>  items=[{"/scratch/training_data/": "/eagle/project/training/"}]<br/>)
    Academy->>GlobusXfer: POST /transfer
    GlobusXfer->>RC_EP: Read training data
    RC_EP->>ALCF_EP: Transfer 2TB via GridFTP
    GlobusXfer-->>Academy: {task_id: "xfer-1"}

    Agent_R->>Academy: globus_wait_for_task("xfer-1", timeout=7200)
    Academy-->>Agent_R: SUCCEEDED (2TB, 90 min)

    Note over Agent_R,Polaris: Step 2: Submit compute job
    Agent_R->>Academy: globus_compute_submit(<br/>  endpoint=alcf_polaris_uuid,<br/>  function=training_func_uuid,<br/>  args={data_path: "/eagle/project/training/",<br/>        epochs: 100, nodes: 32}<br/>)
    Academy->>GlobusComp: Submit function
    GlobusComp->>Polaris: Execute on 32 nodes
    GlobusComp-->>Academy: {task_id: "compute-1"}

    Note over Agent_R,Polaris: Step 3: Poll compute result
    loop Every 5 min
        Agent_R->>Academy: globus_compute_get_task("compute-1")
    end
    Polaris-->>GlobusComp: Result (model weights, metrics)
    GlobusComp-->>Academy: {result: {accuracy: 0.97, path: "/eagle/project/output/"}}

    Note over Agent_R,RC_EP: Step 4: Transfer results back to RC
    Agent_R->>Academy: globus_submit_transfer(<br/>  source=alcf_eagle_ep,<br/>  dest=rc_ep,<br/>  items=[{"/eagle/project/output/": "/scratch/results/"}]<br/>)
    ALCF_EP->>RC_EP: Transfer model weights back
    Academy-->>Agent_R: SUCCEEDED

    Agent_R-->>Agent_R: "Training complete. Accuracy: 97%.<br/>Model at /scratch/results/"
```

### 4C. Compute Flow

```mermaid
sequenceDiagram
    participant User as Researcher
    participant Agent_R as ADEPT Agent<br/>(RC)
    participant Academy as Academy MCP
    participant GlobusComp as Globus Compute API
    participant ALCF as ALCF Polaris

    Note over User,Agent_R: Step 1: User requests ALCF compute
    User->>Agent_R: "Train the transformer model<br/>on Polaris with 32 nodes"

    Note over Agent_R,Academy: Step 2: Register function (if needed)
    Agent_R->>Academy: globus_compute_register_function(<br/>  code="def train(data_path, epochs, nodes):...",<br/>  function_name="transformer_training"<br/>)
    Academy->>GlobusComp: Register function
    GlobusComp-->>Academy: {function_id: "func-uuid"}

    Note over Agent_R,ALCF: Step 3: Submit to ALCF
    Agent_R->>Academy: globus_compute_submit(<br/>  endpoint=alcf_polaris_uuid,<br/>  function=func-uuid,<br/>  args={data_path: "/eagle/...", epochs: 100}<br/>)
    Academy->>GlobusComp: Submit
    GlobusComp->>ALCF: Schedule on Polaris PBS

    Note over Agent_R,ALCF: Step 4: Monitor execution
    loop Poll status
        Agent_R->>Academy: globus_compute_get_task(task_id)
        Academy->>GlobusComp: GET /tasks/{task_id}
    end
    ALCF-->>GlobusComp: Execution complete
    GlobusComp-->>Academy: {status: "success", result: {...}}

    Academy-->>Agent_R: Results
    Agent_R-->>User: "Training complete on Polaris.<br/>32 nodes, 4.2 hours, accuracy 97%"
```

---

## Scenario 5: EMSL to ALCF via RC (Multi-Hop Federated Workflow)

**Facilities**: EMSL (origin) → RC (intermediary, Globus-enabled) → ALCF (compute target)
**Protocol**: A2A (EMSL→RC) + Globus SDK (RC→ALCF)
**Use Case**: An EMSL researcher needs to run a compute-intensive cryo-EM reconstruction on ALCF's Aurora GPU cluster. EMSL has no Globus endpoint, so RC acts as the Globus-enabled intermediary.

### 5A. Auth Flow (Multi-Hop)

```mermaid
sequenceDiagram
    participant User as Researcher<br/>(EMSL)
    participant KC_E as Keycloak<br/>(EMSL)
    participant GW_E as Gateway<br/>(EMSL)
    participant GW_R as Gateway<br/>(RC)
    participant KC_R as Keycloak<br/>(RC)
    participant GlobusAuth as Globus Auth
    participant ALCF as ALCF Globus<br/>Compute

    Note over User,KC_E: Hop 1: EMSL authentication
    User->>KC_E: Login (local IdP)
    KC_E-->>User: EMSL Keycloak JWT

    Note over GW_E,GW_R: Hop 2: A2A to RC
    GW_E->>GW_R: A2A delegate<br/>(service token + user JWT)
    GW_R->>GW_R: Validate EMSL JWT<br/>(peer JWKS federation)

    Note over KC_R,GlobusAuth: Hop 3: Globus token for ALCF
    GW_R->>KC_R: Token exchange<br/>(EMSL JWT → Globus token)
    Note over KC_R: Option A: User has Globus-linked Keycloak account<br/>→ Use stored refresh token<br/>Option B: Service-level Globus client credentials<br/>→ ClientCredentialsAuthorizer
    KC_R->>GlobusAuth: Get Compute-scoped token
    GlobusAuth-->>KC_R: Globus access_token

    Note over GW_R,ALCF: Hop 4: Globus Compute at ALCF
    GW_R->>ALCF: globus_compute_submit(<br/>  endpoint=alcf_aurora_uuid)
    Note over ALCF: Validates Globus identity<br/>against ALCF allocation
```

**Auth Complexity**: Three distinct auth domains are bridged:
1. **EMSL Keycloak** → A2A service token → **RC Keycloak** (JWKS federation)
2. **RC Keycloak** → RFC 8693 token exchange → **Globus Auth** (stored refresh token)
3. **Globus Auth** → Compute scope → **ALCF** (allocation-based access)

### 5B. End-to-End Data + Compute Flow

```mermaid
sequenceDiagram
    participant User as Researcher<br/>(EMSL)
    participant Agent_E as ADEPT Agent<br/>(EMSL)
    participant Agent_R as ADEPT Agent<br/>(RC)
    participant Academy as Academy MCP<br/>(Globus Tools)
    participant MCP_S as Slurm MCP<br/>(RC)
    participant RC_EP as RC Globus EP
    participant ALCF_EP as ALCF Globus EP
    participant ALCF_Comp as ALCF Compute

    Note over User,Agent_E: Phase 1: Request from EMSL
    User->>Agent_E: "Reconstruct cryo-EM dataset<br/>(200GB micrographs) on Aurora"

    Note over Agent_E,Agent_R: Phase 2: A2A to RC (Globus intermediary)
    Agent_E->>Agent_R: A2A delegate with<br/>micrograph file references

    Note over Agent_R,RC_EP: Phase 3: Stage data EMSL → RC
    Agent_R->>Agent_R: Receive data via A2A<br/>(or user uploads to RC separately)
    Agent_R->>Agent_R: Write to /scratch/user/cryo/

    Note over Academy,ALCF_EP: Phase 4: Stage data RC → ALCF
    Agent_R->>Academy: globus_submit_transfer(<br/>  source=rc_ep, dest=alcf_ep,<br/>  items=[{"/scratch/user/cryo/": "/eagle/cryo/"}])
    RC_EP->>ALCF_EP: 200GB via Globus Transfer
    Agent_R->>Academy: globus_wait_for_task(...)
    Academy-->>Agent_R: SUCCEEDED

    Note over Agent_R,ALCF_Comp: Phase 5: Run on ALCF Aurora
    Agent_R->>Academy: globus_compute_submit(<br/>  endpoint=alcf_aurora_uuid,<br/>  function=cryoem_reconstruct_uuid,<br/>  args={input: "/eagle/cryo/", gpus: 64})
    ALCF_Comp-->>Academy: {task_id: "compute-1"}

    Note over Agent_R,ALCF_Comp: Phase 6: Poll and collect
    loop Poll every 10 min
        Agent_R->>Academy: globus_compute_get_task("compute-1")
    end
    ALCF_Comp-->>Academy: {result: {resolution: "3.2Å"}}

    Note over Academy,RC_EP: Phase 7: Results ALCF → RC → EMSL
    Agent_R->>Academy: globus_submit_transfer(<br/>  source=alcf_ep, dest=rc_ep,<br/>  items=[{"/eagle/cryo/output/": "/scratch/results/"}])
    Agent_R->>Academy: globus_wait_for_task(...)

    Agent_R-->>Agent_E: A2A response with results
    Agent_E-->>User: "Reconstruction complete: 3.2Å resolution.<br/>Results on RC at /scratch/results/"
```

---

## Scenario 6: Full Federated Meta-Orchestration (All 4 Facilities)

**Facilities**: All four — EMSL + AWS + RC + ALCF
**Protocol**: A2A + Globus Transfer + Globus Compute + Slurm
**Use Case**: A multi-facility drug discovery pipeline: (1) EMSL generates proteomics data, (2) AWS runs ML inference for target identification, (3) RC runs molecular dynamics on Slurm, (4) ALCF runs large-scale docking simulations on Polaris.

### 6A. Meta-Orchestration Architecture

```mermaid
graph TB
    subgraph "Phase 1: Data Generation"
        EMSL["EMSL<br/>(Instruments)"]
        EMSL_ADEPT["EMSL ADEPT<br/>(Data Collection)"]
        EMSL --> EMSL_ADEPT
    end

    subgraph "Phase 2: ML Inference"
        AWS_ADEPT["AWS ADEPT<br/>(GPU Inference)"]
        AWS_SANDBOX["Sandbox MCP<br/>(AlphaFold, ESM)"]
        AWS_ADEPT --> AWS_SANDBOX
    end

    subgraph "Phase 3: MD Simulation"
        RC_ADEPT["RC ADEPT<br/>(Orchestrator)"]
        RC_SLURM["Slurm HPC<br/>(GROMACS)"]
        RC_GLOBUS["Globus Endpoint<br/>(/scratch)"]
        RC_ADEPT --> RC_SLURM
        RC_ADEPT --> RC_GLOBUS
    end

    subgraph "Phase 4: Docking"
        ALCF_COMPUTE["ALCF Compute<br/>(Polaris)"]
        ALCF_GLOBUS["ALCF Endpoint<br/>(Eagle FS)"]
        ALCF_COMPUTE --> ALCF_GLOBUS
    end

    EMSL_ADEPT -->|"A2A:<br/>proteomics data"| AWS_ADEPT
    AWS_ADEPT -->|"A2A:<br/>target structures"| RC_ADEPT
    RC_GLOBUS -->|"Globus Transfer:<br/>MD trajectories"| ALCF_GLOBUS
    RC_ADEPT -->|"Globus Compute:<br/>docking job"| ALCF_COMPUTE
    ALCF_GLOBUS -->|"Globus Transfer:<br/>docking results"| RC_GLOBUS
    RC_ADEPT -->|"A2A:<br/>final results"| EMSL_ADEPT
```

### 6B. End-to-End Sequence

```mermaid
sequenceDiagram
    participant User as Researcher<br/>(EMSL)
    participant E as ADEPT<br/>(EMSL)
    participant A as ADEPT<br/>(AWS)
    participant R as ADEPT<br/>(RC)
    participant S as Slurm<br/>(RC)
    participant G as Globus<br/>Transfer
    participant C as Globus<br/>Compute (ALCF)

    Note over User,E: Phase 1: Data Generation (EMSL)
    User->>E: "Run drug discovery pipeline<br/>on proteomics dataset XYZ"
    E->>E: Collect proteomics data<br/>from mass spec instruments

    Note over E,A: Phase 2: ML Inference (AWS)
    E->>A: A2A delegate:<br/>"Identify drug targets<br/>in proteomics data"
    A->>A: AlphaFold structure prediction<br/>(GPU sandbox)
    A->>A: ESM protein embeddings
    A-->>E: Target structures + binding sites

    Note over E,R: Phase 3: MD Simulation (RC Slurm)
    E->>R: A2A delegate:<br/>"Run GROMACS MD on<br/>top 5 target-ligand complexes"
    R->>S: slurm_submit_job<br/>(512 cores, 72h walltime)
    S-->>R: MD trajectories complete

    Note over R,G: Phase 4: Stage data RC → ALCF
    R->>G: globus_submit_transfer<br/>(RC /scratch → ALCF /eagle)
    G-->>R: 50GB staged to ALCF

    Note over R,C: Phase 5: Docking (ALCF Polaris)
    R->>C: globus_compute_submit<br/>(docking function, 128 nodes)
    C-->>R: Docking scores + poses

    Note over C,G: Phase 6: Collect results
    R->>G: globus_submit_transfer<br/>(ALCF /eagle → RC /scratch)
    G-->>R: Results back on RC

    Note over R,User: Phase 7: Aggregate and return
    R-->>E: A2A: "Pipeline complete.<br/>Top hit: Compound X,<br/>binding energy: -12.3 kcal/mol"
    E-->>User: Final drug discovery report
```

### 6C. Auth Flow Summary (All Hops)

```mermaid
flowchart TD
    subgraph "Auth Domain 1: ADEPT Keycloak"
        KC_E["Keycloak EMSL"]
        KC_A["Keycloak AWS"]
        KC_R["Keycloak RC"]
        KC_E <-->|"JWKS Federation"| KC_A
        KC_E <-->|"JWKS Federation"| KC_R
        KC_A <-->|"JWKS Federation"| KC_R
    end

    subgraph "Auth Domain 2: A2A Service Tokens"
        ST_EA["Service Token<br/>EMSL→AWS"]
        ST_ER["Service Token<br/>EMSL→RC"]
        ST_AR["Service Token<br/>AWS→RC"]
    end

    subgraph "Auth Domain 3: Globus"
        GA["Globus Auth<br/>(Federation Broker)"]
        GT["Token Exchange<br/>(RFC 8693)"]
        GC["Globus Compute<br/>Scope"]
        GX["Globus Transfer<br/>Scope"]
        KC_R -->|"stored refresh_token"| GT
        GT --> GA
        GA --> GC
        GA --> GX
    end

    subgraph "Auth Domain 4: Slurm HPC"
        IM["IdentityMapper"]
        JB["JWT Bridge<br/>(RS256→HS256)"]
        SR["slurmrestd"]
        KC_R --> IM
        IM --> JB
        JB --> SR
    end

    subgraph "Auth Domain 5: SPIFFE (Optional)"
        SPIRE["SPIRE Agent"]
        SVID["JWT-SVID"]
        SPIRE --> SVID
        SVID --> JB
    end
```

| Hop | Source | Destination | Auth Mechanism | Token Type |
|-----|--------|-------------|----------------|------------|
| 1 | User | EMSL Keycloak | ROPC or OIDC | Keycloak JWT |
| 2 | EMSL GW | AWS GW | A2A service token + peer JWKS | Bearer + JWT |
| 3 | AWS GW | RC GW | A2A service token + peer JWKS | Bearer + JWT |
| 4 | RC Agent | Globus Auth | RFC 8693 token exchange | Globus access_token |
| 5 | RC Agent | Globus Transfer | AccessTokenAuthorizer | Globus OAuth2 |
| 6 | RC Agent | Globus Compute (ALCF) | AccessTokenAuthorizer | Globus OAuth2 |
| 7 | RC Agent | slurmrestd | IdentityMapper + JWT Bridge | HS256 JWT |
| 8 | SPIRE Agent | JWT Bridge (optional) | Workload API | RS256 JWT-SVID |

---

## Scenario Summary Matrix

| Scenario | Facilities | Auth | Data Transport | Compute | Complexity |
|----------|-----------|------|----------------|---------|------------|
| 1. Pure A2A | EMSL ↔ AWS | Keycloak JWT + A2A tokens + JWKS federation | A2A message body | AWS sandbox (GPU) | Low |
| 2. A2A + Slurm | EMSL → RC | + IdentityMapper + SPIFFE + JWT Bridge | A2A message body + /scratch | Slurm HPC | Medium |
| 3. Globus Staging | AWS → RC | + Globus token exchange (RFC 8693) | Globus Transfer (GridFTP) | Slurm HPC | Medium-High |
| 4. Globus Compute | RC → ALCF | + Globus Compute scope + ALCF allocation | Globus Transfer | Globus Compute (Polaris) | Medium |
| 5. Multi-Hop | EMSL → RC → ALCF | A2A + token exchange + Globus | A2A + Globus Transfer | Globus Compute | High |
| 6. Full Pipeline | All 4 | All mechanisms combined | A2A + Globus Transfer | Sandbox + Slurm + Globus Compute | Very High |

---

## Implementation Status

| Component | Status | Reference |
|-----------|--------|-----------|
| A2A Gateway Mesh (Scenarios 1-2) | **Production** | [A2A Workshop](../../a2a-workshop/README.md) |
| Globus 28 MCP Tools (Scenarios 3-6) | **Implemented** | [Globus Tools Proposal](GLOBUS_TOOLS_PROPOSAL.md) |
| Globus Token Exchange (Scenarios 3-6) | **Implemented** | `src/.../core/globus_token_exchange.py` |
| Slurm MCP Server (Scenarios 2-3) | **Implemented** | `examples/slurm_hpc/` |
| SPIFFE/SPIRE Phase 0-2 (Scenario 2) | **Implemented** | `examples/slurm_hpc/docs/SPIFFE_IMPLEMENTATION_TRACKER.md` |
| IdentityMapper (Scenario 2) | **Implemented** | `examples/slurm_hpc/slurm_mcp_server/slurm_mcp/identity_mapper.py` |
| JWT Bridge RS256→HS256 (Scenario 2) | **Implemented** | `examples/slurm_hpc/slurm_mcp_server/slurm_mcp/jwt_bridge.py` |
| Globus Compute at ALCF (Scenario 4) | **Tools Ready** | Needs ALCF endpoint UUID + allocation |
| Full Meta-Orchestration (Scenario 6) | **Design** | Requires all components integrated |
| SPIFFE Phase 3-4 (Production) | **Not Started** | Needs live SPIRE infra + OPA policies |
