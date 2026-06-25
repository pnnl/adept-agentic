# Quickstart: Instantiate Your Own MCP Server

This guide walks you through creating a new MCP server from this template.

## Prerequisites

- Docker and docker-compose installed
- Python 3.11+ for local development
- Basic understanding of MCP protocol and ADEPT architecture

---

## Step 1: Copy the Template

```bash
# From the ADEPT repository root
cp -r examples/mcp_server_template examples/my_new_mcp

cd examples/my_new_mcp
```

---

## Step 2: Replace Placeholder Tokens

Run the following sed command to replace all `{{PLACEHOLDER}}` tokens with your project values:

```bash
# Define your values — IMPORTANT: check port allocation to avoid clashes!
#
# ===================================================================
# Port Allocation Registry — ALL host ports across the ADEPT stack.
# Check this BEFORE assigning ports to avoid collisions.
# ===================================================================
#
# --- Core ADEPT stack (deployment/local/docker-compose/) ---
#   nginx_proxy:          80, 443              (HTTP/HTTPS ingress)
#   postgres:             5432                  (primary database)
#   postgres_rag:         5433                  (RAG database)
#   n8n:                  5678                  (workflow automation)
#   redis:                6379                  (core Redis)
#   vector_db_server:     8001                  (ChromaDB)
#   mcp_server:           8080                  (built-in MCP tools)
#   hpc_mcp_server:       8081                  (HPC MCP tools)
#   sandbox_mcp_server:   8082                  (sandbox execution)
#   agent_gateway:        8083                  (API gateway)
#   orchestration_svc:    8084                  (orchestration — multi-stack only)
#   keycloak:             8180, 9000            (IAM HTTP + management)
#   streamlit_app:        8501                  (Streamlit v1)
#   agent_gw_mgmt_ui:    8502                  (management UI)
#   streamlit_app_v2:     8503                  (Streamlit v2)
#   jupyterlab:           8888                  (notebook)
#   openwebui:            8902                  (chat UI)
#   gateway_registry:     8086                  (service discovery)
#   ragflow:              9380                  (RAGFlow API — optional)
#
# --- External MCP servers (examples/) ---
#   slurm_hpc:       MCP=8002  HTTP=9820  HTTPS=9821
#   opentrons:       MCP=9003
#   academy:         MCP=9004  HTTP=9020  HTTPS=9021  Redis=6384
#   biofoundation:   MCP=9009  HTTP=9020  HTTPS=9021  Redis=6382
#   vfm:             MCP=9010  HTTP=9030  HTTPS=9031  Redis=6383
#   aws:             HTTP=9830  HTTPS=9831
#
# --- Next available (for new servers) ---
#   MCP=9011  HTTP=9040  HTTPS=9041  Redis=6385
#
# NOTE: academy and biofoundation share HTTP/HTTPS=9020/9021.
# They cannot run simultaneously unless one is reassigned.
# ===================================================================
#
export NAME="mynew"                          # Lowercase, no spaces (e.g., "proteinfolding")
export NAME_UPPER="MYNEW"                    # Uppercase version (e.g., "PROTEINFOLDING")
export DISPLAY_NAME="My New"                 # Human-readable name
export DESCRIPTION="Domain-specific tools"   # Docstring description
export MCP_PORT="9011"                       # Container port (see registry above)
export PROXY_HTTP_PORT="9040"                # Nginx HTTP host port
export PROXY_HTTPS_PORT="9041"               # Nginx HTTPS host port
export REDIS_HOST_PORT="6385"                # Redis host port
export TOOL_COUNT="2"                        # Number of tools (initially 2: example + get_job_status)
export REGISTRY="your-registry.example.com/org"  # Helm: container registry
export INGRESS_HOST="mynew.example.com"      # Helm: ingress hostname

# Run sed replacement (Linux — use -i '' on macOS)
find . -type f \( -name "*.py" -o -name "*.md" -o -name "*.yaml" -o -name "*.yml" \
  -o -name "*.toml" -o -name "*.txt" -o -name "*.sh" -o -name "*.tpl" \
  -o -name ".env.example" -o -name "Makefile" -o -name "*.template" \) \
  -exec sed -i \
    -e "s/{{NAME_UPPER}}/$NAME_UPPER/g" \
    -e "s/{{NAME}}/$NAME/g" \
    -e "s/{{DISPLAY_NAME}}/$DISPLAY_NAME/g" \
    -e "s/{{DESCRIPTION}}/$DESCRIPTION/g" \
    -e "s/{{MCP_PORT}}/$MCP_PORT/g" \
    -e "s/{{PROXY_HTTP_PORT}}/$PROXY_HTTP_PORT/g" \
    -e "s/{{PROXY_HTTPS_PORT}}/$PROXY_HTTPS_PORT/g" \
    -e "s/{{REDIS_HOST_PORT}}/$REDIS_HOST_PORT/g" \
    -e "s/{{TOOL_COUNT}}/$TOOL_COUNT/g" \
    -e "s|{{REGISTRY}}|$REGISTRY|g" \
    -e "s/{{INGRESS_HOST}}/$INGRESS_HOST/g" \
    {} +
```

---

## Step 3: Rename Directories and Files

```bash
# Rename package directory
mv template_mcp ${NAME}_mcp

# Rename deployment test file
mv tests/test_template_deployment.py tests/test_${NAME}_deployment.py

# Rename registration script
mv scripts/register_template_tools.py scripts/register_${NAME}_tools.py

# Rename tools (keep example_tool.py and get_job_status.py as-is initially)
# Add your domain-specific tools later
```

---

## Step 4: Validate Skeleton Structure

```bash
# Check that all placeholders were replaced
grep -r "{{" . --include="*.py" --include="*.md" --include="*.yaml"
# Expected: No results (if any remain, re-run sed with correct values)

# Verify package imports
python -c "import ${NAME}_mcp; print(${NAME}_mcp.__version__)"
# Expected: 0.1.0

# Run Tier 1 unit tests (no Docker needed)
pytest tests/test_imports.py tests/test_config.py -v
# Expected: All tests pass
```

---

## Step 5: Create Data Directories

```bash
# Create required data directories
mkdir -p data/input data/output data/results data/models

# Set permissions (if needed for Docker volume mounts)
chmod -R 777 data/
```

---

## Step 6: Add Your Domain Logic

### 6.1 Define Your Tools

Edit `${NAME}_mcp/tools/example_tool.py` or create new tool files:

```python
from pydantic import BaseModel, Field
from fastmcp import FastMCP

mcp = FastMCP("${DISPLAY_NAME}")

class MyToolInput(BaseModel):
    input_data: str = Field(..., description="Input data for processing")
    param1: int = Field(default=10, description="Processing parameter")
    # Framework fields (auto-injected, exclude from schema):
    mcp_session_id: str = Field(default="", exclude=True)
    user_context: dict = Field(default_factory=dict, exclude=True)

@mcp.tool()
async def my_tool(input_data: str, param1: int = 10, **kwargs) -> dict:
    """Process input data with custom logic."""
    session_id = kwargs.get("mcp_session_id", "unknown")
    user = kwargs.get("user_context", {})

    # Your domain logic here
    result = f"Processed {input_data} with param1={param1}"

    return {
        "success": True,
        "result": result,
        "session_id": session_id,
    }
```

### 6.2 Update Tool Count

After adding tools, update `TOOL_COUNT` in:
- `.env.example`
- `tests/test_schema_discovery.py`
- `tests/test_tool_registration.py`

### 6.3 Add Dependencies

Edit `requirements.txt` and add domain-specific libraries:
```
# Example: for bioinformatics
biopython>=1.81
numpy>=1.24
pandas>=2.0
```

---

## Step 7: Deploy with Docker Compose

### 7.1 Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your values
vim .env
```

### 7.2 Build and Start Services

```bash
# Build images
docker compose build

# Start all services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f ${NAME}_mcp_server
```

### 7.3 Verify Deployment

```bash
# Test MCP server health
curl http://localhost:${MCP_PORT}/health

# Test via nginx proxy
curl http://localhost:80/health

# Run integration tests
make test-integration
```

### 7.4 Register Tools with ADEPT

```bash
# Register tools in ADEPT Redis
python scripts/register_${NAME}_tools.py --register

# Verify registration
docker exec ${NAME}_redis redis-cli KEYS "tool:${NAME}_*"

# Run registration tests
make test-registration
```

---

## Step 8: Deploy to Kubernetes (Optional)

### 8.1 Build and Push Images

```bash
# Build production image
docker build -t your-registry.io/${NAME}-mcp:v0.1.0 .

# Push to registry
docker push your-registry.io/${NAME}-mcp:v0.1.0
```

### 8.2 Update Kubernetes Manifests

Edit `k8s/mcp-server-deployment.yaml`:
```yaml
spec:
  template:
    spec:
      containers:
      - name: ${NAME}-mcp-server
        image: your-registry.io/${NAME}-mcp:v0.1.0
        env:
        - name: ${NAME_UPPER}_PORT
          value: "${MCP_PORT}"
        # Add other env vars from .env.example
```

### 8.3 Deploy to Cluster

```bash
# Apply Kubernetes manifests
kubectl apply -f k8s/

# Check deployment status
kubectl get pods -l app=${NAME}-mcp-server

# View logs
kubectl logs -l app=${NAME}-mcp-server -f
```

---

## Next Steps

1. **Add Domain Logic**: Implement your tool functions in `${NAME}_mcp/tools/`
2. **Add Tests**: Create Tier 4 CLI E2E tests in `tests/test_cli_e2e_*.py`
3. **Update Documentation**: Edit README.md with your tool descriptions
4. **Performance Tuning**: Adjust worker processes, timeouts in docker-compose.yaml
5. **Monitoring**: Integrate with ADEPT observability stack (Langfuse, Prometheus)

---

## Troubleshooting

### Issue: Containers won't start
```bash
# Check logs for errors
docker compose logs ${NAME}_mcp_server

# Common fixes:
# 1. Port conflict - change ${MCP_PORT} in .env
# 2. Missing data directories - run Step 5
# 3. Bad environment variable - check .env syntax
```

### Issue: Tests fail with "Module Not Found"
```bash
# Ensure PYTHONPATH is set
export PYTHONPATH="${PWD}:${PYTHONPATH}"

# Or install package in editable mode
pip install -e .
```

### Issue: Tools not appearing in ADEPT
```bash
# Check MCP server health
curl http://localhost:${MCP_PORT}/health

# Verify tools/list endpoint
curl -X POST http://localhost:${MCP_PORT}/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# Re-register tools
python scripts/register_${NAME}_tools.py --delete
python scripts/register_${NAME}_tools.py --register
```

---

## Additional Resources

- **Testing Guide**: See `tests/TESTING.md` for detailed testing strategies
- **Architecture Docs**: See `../../docs/architecture/` for ADEPT framework architecture
- **MCP Protocol**: https://modelcontextprotocol.io/docs
- **FastMCP Docs**: https://github.com/jlowin/fastmcp

---

## Support

For issues or questions:
1. Check `tests/TESTING.md` troubleshooting section
2. Review ADEPT framework documentation in `../../docs/`
3. Open an issue in the ADEPT repository
