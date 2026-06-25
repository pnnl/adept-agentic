# ADEPT Vibe Coding Guide for Domain Scientists

## Welcome Systems Biology Modelers & Domain Experts!

This guide helps you leverage ADEPT as an AI-powered "vibe coding" environment where you can interactively develop models, analyze data, and create computational workflows with natural language guidance. Think of it as having an expert programmer sitting next to you, helping you code in real-time.

## Table of Contents
0. [Prerequisites: AWS VM Deployment](#prerequisites-aws-vm-deployment)
1. [What is Vibe Coding?](#what-is-vibe-coding)
2. [Getting Started with Streamlit](#getting-started-with-streamlit)
3. [File Management & Organization](#file-management--organization)
4. [RAG-Powered Literature & Code Understanding](#rag-powered-literature--code-understanding)
5. [The Coding Agent - Your AI Partner](#the-coding-agent---your-ai-partner)
6. [Sandbox Execution Environment](#sandbox-execution-environment)
7. [Practical Workflows](#practical-workflows)
8. [Current Limitations & Workarounds](#current-limitations--workarounds)
9. [Tips for Effective Vibe Coding](#tips-for-effective-vibe-coding)

---

## Prerequisites: AWS VM Deployment

**Before starting vibe coding**, you need a running ADEPT environment. This guide assumes you have completed the infrastructure deployment.

### Required Pre-Work

**If you haven't deployed your ADEPT environment yet**, complete the following steps first:

**[AWS VM Deployment Guide](../devtools/AWS_VM_DEPLOYMENT_GUIDE.md)** (~15-20 minutes)

This comprehensive guide covers:
1. **AWS EC2 Instance Provisioning** with CDK
   - t3.2xlarge instance (8 vCPU, 32GB RAM)
   - 100GB root + 500GB data volumes
   - Auto-generated SSH key management

2. **Bootstrap ADEPT Framework**
   - Repository clone and virtual environment setup
   - Dependency installation with UV package manager
   - Environment configuration

3. **VS Code Remote Development** (Choose your preferred method)
   - **Method 1**: SSH Config with automatic port forwarding (recommended for daily use)
   - **Method 2**: VS Code Ports Panel with dynamic tunneling (flexible for testing)
   - Complete `.ssh/config` example with all 9 service ports
   - Step-by-step UI guide with GitHub OAuth setup

4. **Service Startup & Validation**
   - Docker compose stack deployment (15 containers)
   - Health check validation
   - Access verification for all interfaces

### Environment Verification Checklist

Before proceeding with this vibe coding guide, verify your environment:

- [ ] **EC2 Instance Running**: `aws ec2 describe-instances --instance-ids <YOUR_INSTANCE_ID>`
- [ ] **SSH/VS Code Connected**: Can access remote files at `<your-adept-workspace>/`
- [ ] **Port Forwarding Active**: Can access http://localhost:8503 in your browser
- [ ] **ADEPT Stack Running**: All 15 containers healthy
  ```bash
  ssh <your-instance>
  cd <your-adept-workspace>
  docker ps --format "table {{.Names}}\t{{.Status}}"
  ```
- [ ] **Services Validated**: `make validate-service-health` passes
- [ ] **Login Successful**: Can login to Streamlit v2 (notebook-user / notebook-password)

### Expected Running Services

When your environment is ready, you should have these services accessible via port forwarding:

| Port | Service | Purpose | Access URL |
|------|---------|---------|------------|
| **8503** | **Streamlit v2** | **Primary vibe coding interface** | http://localhost:8503 |
| 8888 | JupyterLab | Notebook development | http://localhost:8888 |
| 8501 | Streamlit UI | Legacy interface | http://localhost:8501 |
| 8083 | Agent Gateway | API endpoint | http://localhost:8083 |
| 8180 | Keycloak | Authentication server | http://localhost:8180 |
| 8080 | MCP Server | Main tool server | http://localhost:8080 |
| 8081 | HPC MCP Server | HPC workflows | http://localhost:8081 |
| 8082 | Sandbox MCP | Code execution | http://localhost:8082 |
| 8086 | Gateway Registry | Service discovery | http://localhost:8086 |

### Troubleshooting Pre-Work Issues

If you encounter issues during deployment, refer to the troubleshooting section in the [AWS VM Deployment Guide](../devtools/AWS_VM_DEPLOYMENT_GUIDE.md#troubleshooting), which covers:
- CDK bootstrap failures
- SSH connection issues
- Cloud-init timeout problems
- Docker permission errors
- Port forwarding not working
- Service startup failures

### Ready to Start?

Once all checkboxes above are complete, you're ready to proceed with vibe coding!

**Next Section**: [What is Vibe Coding?](#what-is-vibe-coding) - Learn the collaborative AI programming approach that makes ADEPT powerful.

---

## What is Vibe Coding?

**Vibe coding** is a collaborative programming style where you describe what you want in natural language, and AI helps you:
- Generate code snippets and complete programs
- Debug and refine existing code
- Explore datasets interactively
- Create visualizations on-the-fly
- Build models iteratively

In ADEPT, this happens through:
- **Natural language instructions** → Working code
- **Uploaded papers/datasets** → Contextual understanding via RAG
- **Live execution** → Immediate feedback
- **Iterative refinement** → Progressive improvement

---

## Getting Started with Streamlit v2 (Port 8503)

### Streamlit v2: Your Vibe Coding Interface

**ADEPT's Streamlit v2** is the primary interface for domain scientists to engage in vibe coding. It provides a ChatGPT-like experience with powerful file handling and code execution capabilities.

### Access the Interface
1. **Navigate to: http://localhost:8503** **Important: Port is 8503, not 8501**
2. **Login with:** `notebook-user` / `notebook-password`
3. **Interface Components:**
   - Chat conversation area (main panel)
   - File upload zone (sidebar or top)
   - Session history (if enabled)
   - Response streaming with real-time updates

### Key Features of Streamlit v2

#### 1. **OpenAI-Compatible Chat Interface**
- Fully compatible with OpenAI's Assistant API
- Supports streaming responses for immediate feedback
- Maintains conversation context across messages
- Tool calling visualization (see what tools AI uses)

#### 2. **Session-Based Isolation**
- Each browser session gets a unique workspace
- Files are isolated between users/sessions
- Persistent across page refreshes
- Clean workspace for each new project

#### 3. **Multi-Modal Capabilities**
- Upload and analyze images (PNG, JPG, SVG)
- Process various data formats (CSV, JSON, Excel)
- Handle scientific formats (FASTA, PDB, GenBank)
- PDF document analysis and extraction

### Your First Vibe Coding Session

Start with these progressive examples:

#### Example 1: Basic Data Analysis
```markdown
You: "I'm uploading a CSV file with gene expression data. Can you load it and show me basic statistics?"

AI: "I'll help you analyze your gene expression data. Let me load the file and provide statistics..."
[Executes code in sandbox, shows pandas describe() output]
```

#### Example 2: Metabolic Modeling
```markdown
You: "Create a simple metabolic model for glycolysis using COBRApy"

AI: "I'll create a glycolysis model for you. This will include the main reactions from glucose to pyruvate..."
[Generates complete Python code, executes it, shows pathway visualization]
```

#### Example 3: Literature-Informed Analysis
```markdown
You: "I've uploaded 3 papers on CRISPR. Based on these, help me design a gene knockout strategy for improving ethanol production in E. coli"

AI: "I'll analyze the uploaded papers and design a knockout strategy. Let me first index the papers..."
[Creates RAG index, extracts relevant methods, generates strategy with code]
```

### Real-Time Vibe Coding Workflow

The Streamlit v2 interface enables a fluid vibe coding experience:

1. **Upload Phase**
   - Drag & drop your files
   - AI automatically detects file types
   - Files are processed and indexed if needed

2. **Exploration Phase**
   ```markdown
   "What's in this dataset?"
   "Show me the first 10 rows"
   "Are there any missing values?"
   "What's the distribution of the target variable?"
   ```

3. **Analysis Phase**
   ```markdown
   "Perform PCA on the gene expression data"
   "Create a heatmap of correlations"
   "Run differential expression analysis"
   "Generate a volcano plot"
   ```

4. **Modeling Phase**
   ```markdown
   "Build a metabolic model for this pathway"
   "Optimize for maximum product yield"
   "What genes should I knock out?"
   "Simulate growth under different conditions"
   ```

5. **Refinement Phase**
   ```markdown
   "Can you add error bars to that plot?"
   "Save the results to a CSV file"
   "Generate a report summarizing the findings"
   "Create a function I can reuse for this analysis"
   ```

### Session Management
- **Session ID**: Visible in the URL or session info
- **File Location**: `/app/data/uploaded_files/sessions/streamlit_[session_id]/`
- **Persistence**: Sessions maintained for 24 hours (configurable)
- **Export**: Download generated code and results anytime

### Advanced Streamlit v2 Features

#### Tool Visibility & Transparency
When you interact with the AI, you can see exactly what tools are being used:
```markdown
Using tool: ProcessUploadedFile
Using tool: ExecuteCode
Using tool: SaveToFile
```

#### Multi-Agent Collaboration
You can request specialized agents for complex tasks:
```markdown
You: "Create a team with a Python developer and a data scientist to analyze this proteomics data"

AI: "I'll create a multi-agent team for your proteomics analysis..."
[Creates specialized agents with different expertise]
```

#### Real-Time Code Execution
Watch your code execute in real-time with the sandbox:
```markdown
You: "Run the optimization and show me progress updates"

AI: "I'll run the optimization with verbose output..."
[Shows live output as code executes]
```

### Streamlit v2 vs Other Interfaces

| Feature | Streamlit v2 (8503) | JupyterLab (8888) | OpenWebUI (3000) |
|---------|-------------------|-------------------|------------------|
| **Best For** | Interactive vibe coding | Notebook development | LLM experimentation |
| **File Upload** | Yes - Drag & drop | Yes - File browser | Limited |
| **RAG Support** | Full | Manual | No |
| **Code Execution** | Sandbox | Kernel | No |
| **Session Isolation** | Per-user | Shared | Per-chat |
| **Tool Calling** | Visible | Hidden | No |
| **Multi-Agent** | Supported | No | No |

### Tips for Effective Streamlit v2 Usage

1. **Start Simple, Build Complexity**
   - Begin with data exploration
   - Add analysis incrementally
   - Refine visualizations iteratively

2. **Use Natural Language**
   - Describe your goal, not the implementation
   - Ask for explanations when needed
   - Request modifications conversationally

3. **Leverage Session Persistence**
   - Your work is saved automatically
   - Reference previous results: "Using the model we created earlier..."
   - Build on existing code: "Modify the function to also calculate..."

4. **Monitor Tool Usage**
   - Watch which tools are being called
   - Understand the workflow
   - Learn from the AI's approach

---

## File Management & Organization

### File System Structure

```
/app/data/uploaded_files/
├── sessions/
│   └── streamlit_[your_session_id]/    # Your private workspace
│       ├── uploaded_file.csv           # Files you upload
│       ├── generated_model.py          # Code ADEPT creates
│       └── analysis_results.pkl        # Saved results
└── shared/                             # ADEPT-wide shared files
    ├── reference_genomes/
    ├── protein_databases/
    └── literature_corpus/
```

### File Upload Capabilities

#### Supported File Types
- **Data**: CSV, TSV, Excel, Parquet, JSON, HDF5
- **Code**: Python, R, MATLAB, Julia, C++
- **Documents**: PDF, Word, Markdown, LaTeX
- **Bioinformatics**: FASTA, FASTQ, GenBank, PDB, VCF
- **Images**: PNG, JPG, SVG (for analysis)
- **Archives**: ZIP, TAR.GZ (auto-extraction)

#### Upload Methods
1. **Drag & Drop**: Drop files directly onto the upload area
2. **Multi-file**: Upload up to 5 files simultaneously
3. **Folder Registration**: Reference existing folders on the system

### File Processing Tools

#### ListUploadedFiles
Shows all files in your session:
```
"List all files I've uploaded in this session"
```

#### ProcessUploadedFile
Extract and analyze file contents:
```
"Process the systems_biology_paper.pdf and summarize the key models"
```

#### RegisterLocalFile
Reference files from other locations:
```
"Register the file /app/data/shared/protein_database.fasta for analysis"
```

#### CreateRAGIndex
Index files for semantic search:
```
"Create a searchable index of all Python files in my session"
```

---

## RAG-Powered Literature & Code Understanding

### How RAG Works in ADEPT

RAG (Retrieval-Augmented Generation) allows ADEPT to:
1. **Index** your uploaded documents/code
2. **Understand** domain-specific content
3. **Reference** relevant sections when answering
4. **Generate** contextually-aware code

### Setting Up RAG for Your Domain

#### Step 1: Upload Your Corpus
```
"I'm uploading 10 papers on metabolic modeling. Please index them for reference."
```

#### Step 2: Create Domain-Specific Index
```
"Create a RAG index of all uploaded PDFs focusing on enzyme kinetics"
```

#### Step 3: Query Your Knowledge Base
```
"Based on the papers I uploaded, what's the best approach for modeling ATP synthesis?"
```

### RAG Limitations (Current State)

**Known Issues**:
- Large PDFs (>10MB) may cause token overflow
- ChromaDB indexing sometimes fails silently
- Session synchronization can lose file references
- Max 10,000 tokens returned per query

**Workarounds**:
- Split large documents into smaller sections
- Verify index creation with "List my RAG indexes"
- Re-upload files if references are lost
- Ask for summaries rather than full content

---

## The Coding Agent - Your AI Partner

### Multi-Agent Collaboration

ADEPT can spawn specialized coding agents:

```python
"Create a team with a Python developer and a data scientist to analyze this RNA-seq data"
```

This creates:
- **Python Developer**: Focuses on clean, efficient code
- **Data Scientist**: Handles statistical analysis and ML

### Coding Agent Capabilities

#### What It Can Do
- Generate complete Python scripts
- Create data analysis pipelines
- Build mathematical models (ODEs, PDEs)
- Develop visualization code
- Write unit tests
- Debug existing code
- Optimize performance
- Add documentation

#### Example Coding Requests

**Systems Biology Modeling**:
```
"Create a Python class for simulating Michaelis-Menten enzyme kinetics with:
- Adjustable Km and Vmax parameters
- Time-course simulation
- Plotting capabilities
- Parameter fitting from experimental data"
```

**Data Analysis Pipeline**:
```
"Build a complete analysis pipeline for my proteomics data that:
1. Loads the CSV file
2. Normalizes intensities
3. Performs statistical testing
4. Creates volcano plots
5. Exports significant proteins"
```

**Model Optimization**:
```
"Take this ODE model and:
- Add stochastic noise terms
- Implement parameter sensitivity analysis
- Create a parameter sweep function
- Generate phase portraits"
```

### Code Generation Best Practices

1. **Be Specific**: Include details about inputs, outputs, and constraints
2. **Iterate**: Start simple, then add complexity
3. **Verify**: Always test generated code in the sandbox
4. **Document**: Ask for docstrings and comments
5. **Modularize**: Request functions/classes, not monolithic scripts

---

## Sandbox Execution Environment

### The Execution Sandbox

ADEPT provides a secure Python environment for running code:
- **Isolated**: Each execution is containerized
- **Stateful**: Variables persist within a session
- **Safe**: Can't harm the host system
- **Fast**: Near-instant execution for most tasks

### Running Code

#### Simple Execution
```
"Run this code:
import pandas as pd
df = pd.read_csv('my_data.csv')
print(df.describe())"
```

#### Installing Packages
```
"Install scipy and scikit-learn, then import them"
```

#### Saving Results
```
"Save the processed dataframe as 'results.csv' in my session folder"
```

### Sandbox Capabilities

#### Available Libraries
- **Data Science**: pandas, numpy, scipy, scikit-learn
- **Visualization**: matplotlib, seaborn, plotly
- **Biology**: Biopython, scikit-bio
- **Modeling**: SymPy, ODEint, PyDSTool
- **Stats**: statsmodels, pingouin
- **ML**: TensorFlow, PyTorch (limited)

#### Visualization Support
Generated plots are automatically displayed:
```python
"Create a scatter plot of gene expression vs protein abundance with:
- Log scale on both axes
- Color by cell type
- Add trend line
- Include R-squared value"
```

#### Data Persistence
- Session variables persist between code blocks
- Files saved to session folder are accessible
- Results can be downloaded through the UI

### Sandbox Limitations

**Current Restrictions**:
- 2-minute timeout per execution
- 2GB memory limit
- No internet access during execution
- GPU not available
- Some compiled libraries may not work

**Workarounds**:
- Break long computations into chunks
- Use sampling for large datasets
- Pre-download required data
- Use CPU-friendly alternatives to GPU code

---

## Practical Workflows

### Workflow 1: Literature-Informed Model Building

1. **Upload Papers**:
```
"I'm uploading 5 papers on circadian rhythm models"
```

2. **Create Knowledge Base**:
```
"Index these papers and extract all ODE models mentioned"
```

3. **Generate Base Model**:
```
"Based on the papers, create a Python implementation of the Goodwin oscillator model"
```

4. **Extend Model**:
```
"Add light input forcing to the model based on Smith et al. 2019"
```

5. **Analyze**:
```
"Run parameter sensitivity analysis and identify key control points"
```

### Real Example: Metabolic Engineering with COBRApy

Here's an actual vibe coding session for genome-scale metabolic modeling:

#### Initial Request
```
"We would like to use cobrapy for our simulation. Based on the E. coli iML1515
genome-scale model, develop python code where the oxygen uptake rate is 0
(anaerobic conditions) and maximize cell growth using FBA. Please provide FVA results."
```

#### AI-Generated Solution
```python
#!/usr/bin/env python3
"""Anaerobic growth simulation for E. coli iML1515 using COBRApy"""

import cobra
from cobra.flux_analysis import flux_variability_analysis
import pandas as pd

# Load the iML1515 model
model = cobra.io.load_json_model("iML1515_GP/iML1515.json")

# Set anaerobic conditions (oxygen uptake = 0)
model.reactions.EX_o2_e.lower_bound = 0
model.reactions.EX_o2_e.upper_bound = 0

# Perform FBA to maximize growth
solution = model.optimize()
print(f"Anaerobic growth rate: {solution.objective_value:.4f} h^-1")

# Perform FVA to analyze flux variability
fva_results = flux_variability_analysis(model, fraction_of_optimum=0.9)

# Identify variable reactions
variable_rxns = fva_results[
    (fva_results['maximum'] - fva_results['minimum']) > 1e-6
]
print(f"Number of variable reactions: {len(variable_rxns)}")

# Export results
fva_results.to_csv("anaerobic_fva_results.csv")
```

#### Evolution Through Vibe Coding
The simple request evolved into:
1. **Phase 1**: Basic FBA/FVA script (above)
2. **Phase 2**: Docker containerization for reproducibility
3. **Phase 3**: Automated report generation with visualizations
4. **Phase 4**: Complete pipeline with 50+ Makefile targets
5. **Phase 5**: Monte Carlo Tree Search optimization framework
6. **Phase 6**: LLM-based program synthesis for metabolic strategies

#### Advanced Case Study: LLM-Generated GEM Optimization Framework

The COBRApy example above demonstrates the starting point of vibe coding. Through iterative collaboration with ADEPT, this evolved into a **comprehensive research framework** with publication-quality documentation:

See the GEM iML1515 project documentation for the whitepaper.

**Key Topics Covered**:
- Monte Carlo Tree Search (MCTS) for metabolic pathway exploration
- **LLM-based program synthesis for strain design strategies** (see details below)
- Multi-objective optimization (growth vs. product yield)
- Automated computational pipeline generation
- Integration with COBRApy ecosystem

**Repository**: Available on request from the ADEPT team.

#### LLM-Based Program Synthesis for Experimental Design

The iML1515_GP framework demonstrates a **critical capability**: using LLMs not just for code generation, but for **reasoning about experimental strategies** in metabolic engineering.

**How It Works**:

1. **Natural Language Strategy Specification**:
   ```
   "Design a strain for maximum succinate production under anaerobic conditions
   while maintaining at least 80% of wild-type growth rate"
   ```

2. **LLM Translates to Computational Actions**:
   - Analyzes metabolic network topology
   - Identifies candidate gene knockouts (OptKnock, OptGene)
   - Generates FBA/FVA simulation code
   - Proposes pathway rerouting strategies
   - Creates validation pipelines

3. **Iterative Refinement Through Vibe Coding**:
   ```
   User: "The current design has low yield. What if we enhance glyoxylate shunt?"
   AI: "I'll modify the strategy to upregulate aceA and aceB, then re-run optimization..."
   [Generates updated strain design with new constraints]
   ```

4. **Automated Hypothesis Testing**:
   - LLM generates multiple strain variants
   - Runs in-silico screening (MCTS-guided)
   - Ranks candidates by predicted performance
   - Outputs experimental protocol for wet-lab validation

**Real-World Example from iML1515_GP**:

**Initial Request**:
```
"Maximize ethanol production in E. coli under anaerobic conditions"
```

**LLM-Generated Strategy** (synthesized through vibe coding):
```python
# 1. Gene knockout candidates (reasoning-based selection)
knockouts = ["adhE", "ldhA", "frdA"]  # Block competing pathways
upregulations = ["pdc", "adhB"]        # Enhance ethanol pathway

# 2. Metabolic constraints (LLM understands biological feasibility)
model.reactions.EX_o2_e.bounds = (0, 0)  # Anaerobic
model.reactions.EX_glc__D_e.bounds = (-10, -10)  # Glucose uptake rate

# 3. Multi-objective optimization (LLM-proposed objectives)
model.objective = "BIOMASS_Ec_iML1515_core_75p37M"  # Growth
model.reactions.EX_etoh_e.lower_bound = 5.0  # Minimum ethanol secretion

# 4. Simulation and validation
solution = model.optimize()
fva_results = flux_variability_analysis(model, fraction_of_optimum=0.9)

# 5. Report generation (LLM synthesizes findings)
print(f"Predicted growth: {solution.objective_value:.2f} h^-1")
print(f"Ethanol yield: {solution.fluxes['EX_etoh_e']:.2f} mmol/gDW/h")
```

**Why This Matters for Experimental Design**:

| Traditional Approach | LLM-Based Synthesis |
|---------------------|---------------------|
| Manual literature review (days) | Automated strategy synthesis (minutes) |
| Expert knowledge bottleneck | Democratized strain design |
| Static design templates | Dynamic, context-aware strategies |
| Limited exploration space | MCTS + LLM explores 1000s of variants |
| Slow iteration cycles | Real-time refinement through dialogue |

**Critical Capabilities Enabled**:

1. **Biological Reasoning Integration**:
   - LLM understands "growth-coupled production" → translates to OptKnock constraints
   - Recognizes "redox imbalance" → suggests NADH/NADPH pathway modifications
   - Interprets "bypass toxic intermediate" → proposes alternative routes

2. **Constraint Satisfaction from Natural Language**:
   ```
   "Keep growth above 0.2 h^-1, maximize product, use only single deletions"
   →
   constraint1 = model.slim_optimize() >= 0.2
   constraint2 = len(knockouts) <= 1
   objective = maximize(product_flux)
   ```

3. **Experimental Protocol Generation**:
   - LLM converts in-silico predictions to wet-lab protocols
   - Suggests growth media composition
   - Recommends analytical methods (HPLC, GC-MS)
   - Estimates expected yields and timelines

4. **Knowledge Transfer Across Organisms**:
   ```
   "Adapt this E. coli strategy for S. cerevisiae"
   →
   LLM identifies orthologous genes, adjusts constraints for eukaryotic metabolism
   ```

**Integration with ADEPT Vibe Coding Workflow**:

```markdown
User: "Based on the whitepaper MCTS framework, design 5 alternative strains for
      butanol production. Prioritize industrially relevant constraints."

AI: "I'll use the MCTS-guided search from the framework to explore strain designs.
     Let me set up the search space..."

[LLM generates]:
1. Strain design code (COBRApy + OptKnock)
2. MCTS tree search configuration
3. Fitness function (growth + butanol + industrial constraints)
4. Automated screening pipeline
5. Comparative analysis report

Output: Top 5 strains ranked by:
- Predicted butanol yield (g/g glucose)
- Growth robustness (minimal medium tolerance)
- Genetic simplicity (fewest modifications)
- Literature precedent (validation likelihood)
```

**Key Insight**: The whitepaper demonstrates that LLMs can act as **computational metabolic engineers**, not just code assistants. They reason about:
- Biological feasibility
- Thermodynamic constraints
- Kinetic bottlenecks
- Regulatory interactions
- Experimental practicality

This elevates vibe coding from "write me a script" to "co-design my experiments with AI reasoning".

**What This Demonstrates**:
- ADEPT can generate **theoretical frameworks**, not just code snippets
- Vibe coding enables **publication-ready documentation** creation
- Simple requests can evolve into **comprehensive research platforms**
- AI partnership accelerates from prototype to production-ready system
- **LLMs can reason about experimental design**, not just execute commands

**From 5-Line Script to Research Framework**:
```
Initial Request (5 lines)  →  Basic FBA Script (50 lines)
    ↓
Docker Pipeline (500 lines) →  Makefile Automation (1000+ lines)
    ↓
MCTS Framework (2000+ lines) → Research Whitepaper (15+ pages)
```

This case study exemplifies the full potential of vibe coding for computational biology research.

### Workflow 2: Data-Driven Discovery

1. **Upload Dataset**:
```
"Loading my time-series gene expression data (GSE12345.csv)"
```

2. **Explore**:
```
"Show me the structure of this data and identify any missing values"
```

3. **Process**:
```
"Normalize the data using TMM method and filter low-expression genes"
```

4. **Analyze**:
```
"Perform differential expression analysis between timepoints"
```

5. **Visualize**:
```
"Create a heatmap of top 50 differentially expressed genes with hierarchical clustering"
```

### Workflow 3: Code Enhancement

1. **Upload Existing Code**:
```
"I'm uploading my MATLAB simulation code - convert it to Python"
```

2. **Understand**:
```
"Analyze this code and explain what each function does"
```

3. **Improve**:
```
"Optimize the numerical integration and add error handling"
```

4. **Extend**:
```
"Add parameter estimation using experimental data I'm uploading"
```

5. **Document**:
```
"Generate complete documentation and usage examples"
```

---

## Current Limitations & Workarounds

### Critical Limitations

#### 1. Context Window Overflow
**Issue**: Large files or long conversations exceed token limits
**Impact**: "Maximum context length exceeded" errors
**Workaround**:
- Start new sessions for different tasks
- Summarize rather than include full content
- Use "forget everything except the last analysis"

#### 2. RAG Indexing Failures
**Issue**: Files appear uploaded but aren't searchable
**Impact**: Can't reference content in queries
**Workaround**:
- Manually trigger indexing: "Create RAG index for file X"
- Verify with: "Query my index for [keyword]"
- Re-upload if necessary

#### 3. Session State Loss
**Issue**: Files or variables disappear
**Impact**: Need to restart analysis
**Workaround**:
- Save important results to files frequently
- Use "Save current session state to pickle"
- Keep local backups of generated code

#### 4. Execution Timeouts
**Issue**: Long-running code gets killed
**Impact**: Can't complete intensive computations
**Workaround**:
- Break into smaller steps
- Use progress indicators
- Save intermediate results

### Moderate Limitations

#### File Size Restrictions
- **PDFs**: Best under 5MB
- **CSVs**: Best under 100MB
- **Images**: Best under 10MB
- **Solution**: Pre-process large files locally

#### Package Availability
- Some specialized packages unavailable
- Solution: Request core functionality alternatives

#### Multi-User Conflicts
- Shared resources can be slow
- Solution: Work during off-peak hours

### Minor Inconveniences

#### UI Responsiveness
- Large outputs can freeze the interface
- Solution: Request paginated results

#### Code Formatting
- Generated code may need style fixes
- Solution: Ask for "PEP 8 compliant code"

---

## Tips for Effective Vibe Coding

### Communication Strategies

#### Be Specific About Requirements
**Vague**: "Analyze my data"
**Specific**: "Load my proteomics CSV, log-transform intensities, perform PCA, and plot the first two components colored by treatment group"

#### Provide Context
**No Context**: "Fix this error"
**With Context**: "I'm getting a KeyError when running the metabolic model. The error occurs at line 45 when accessing 'ATP_concentration'. Here's the relevant code..."

#### Iterate Progressively
1. Start with basic functionality
2. Verify it works
3. Add features incrementally
4. Test each addition

### Development Patterns

#### The Exploration Pattern
```
1. "Show me what's in this dataset"
2. "What patterns do you see?"
3. "Let's investigate the outliers"
4. "Build a model to explain this"
```

#### The Refinement Pattern
```
1. "Create a basic version"
2. "Now add error handling"
3. "Optimize for speed"
4. "Add visualization"
5. "Generate documentation"
```

#### The Debug Pattern
```
1. "Run this code"
2. "Why did it fail?"
3. "Fix the error"
4. "Run again"
5. "Add logging for future debugging"
```

### Domain-Specific Tips

#### For Systems Biologists
- Upload pathway databases for reference
- Ask for SBML-compatible model generation
- Request BioPython integration for sequence analysis
- Use domain terminology (e.g., "Implement Gillespie algorithm")

#### For Bioinformaticians
- Index reference genomes first
- Request memory-efficient implementations
- Ask for parallelized code when possible
- Specify file formats explicitly (FASTA, VCF, etc.)

#### For Computational Chemists
- Upload molecular databases
- Request RDKit integration
- Ask for 3D visualization code
- Specify units and constants

### Metabolic Engineering Specific Patterns

#### Loading and Exploring Genome-Scale Models
```
"Load the E. coli iML1515 model and show me basic statistics:
- Number of reactions, metabolites, and genes
- List all exchange reactions
- Show the biomass objective function components"
```

#### Simulating Growth Conditions
```
"Simulate aerobic vs anaerobic growth:
1. Set oxygen uptake to 0 for anaerobic
2. Run FBA for both conditions
3. Compare growth rates and flux distributions
4. Identify bottleneck reactions"
```

#### Strain Design
```
"Design a strain for enhanced succinate production:
1. Load the model
2. Add succinate as a secondary objective
3. Use OptKnock to find gene deletions
4. Validate the design with FBA
5. Check for growth-coupled production"
```

#### Flux Analysis Patterns
```python
# Example request for comprehensive flux analysis
"Perform the following flux analyses on my model:
1. FBA to maximize growth
2. FVA with 90% optimal growth
3. pFBA for parsimonious flux distribution
4. Flux sampling (1000 samples)
5. Create a flux map visualization for central carbon metabolism"
```

#### Media Optimization
```
"Optimize the growth medium for maximum product yield:
1. Start with M9 minimal medium
2. Test all possible carbon sources
3. Find optimal uptake rates
4. Test nitrogen source combinations
5. Generate a ranked list of media compositions"
```

### Performance Optimization

#### Working with Large Datasets
```
"Load only the first 1000 rows for prototyping, then we'll scale up"
```

#### Efficient Iterations
```
"Use vectorized operations instead of loops"
```

#### Memory Management
```
"Process this file in chunks of 10000 rows"
```

#### Genome-Scale Model Optimization
```
"For the iML1515 model with 2719 reactions:
- Use slim optimization for faster solving
- Implement warmstart for iterative optimizations
- Cache FVA results for repeated queries
- Use multiprocessing for flux sampling"
```

---

## Quick Reference Card

### Essential Commands

| Task | Example Prompt |
|------|---------------|
| **Upload & List** | "List all files in my session" |
| **Index for RAG** | "Create a searchable index of all PDFs" |
| **Generate Code** | "Write a function to [specific task]" |
| **Run Code** | "Execute this: [code block]" |
| **Debug** | "Fix this error: [error message]" |
| **Visualize** | "Plot X vs Y with [specifications]" |
| **Save Results** | "Save the dataframe as results.csv" |
| **Install Package** | "Install and import seaborn" |

### File Locations

| Type | Path |
|------|------|
| **Your Session** | `/app/data/uploaded_files/sessions/streamlit_[id]/` |
| **Shared Data** | `/app/data/uploaded_files/shared/` |
| **Generated Code** | `[session]/generated_code.py` |
| **Results** | `[session]/results/` |

### Troubleshooting

| Problem | Solution |
|---------|----------|
| **"File not found"** | Re-upload or use RegisterLocalFile |
| **"Context too long"** | Start new session or summarize |
| **"Timeout error"** | Break into smaller steps |
| **"Import error"** | Request package installation first |
| **"RAG not working"** | Manually create index |

---

## Getting Help

### When Things Don't Work

1. **First**: Check the [Current Limitations](#current-limitations--workarounds) section
2. **Second**: Try the workaround
3. **Third**: Rephrase your request more specifically
4. **Fourth**: Start a fresh session if context is corrupted

### Example Recovery Patterns

**When uploads fail**:
```
"Clear the file cache and let me re-upload my data.csv"
```

**When code won't run**:
```
"Show me the full error traceback and suggest fixes"
```

**When results disappear**:
```
"Restore the last known good state of my session"
```

### Platform Status

Check `docs/IMPLEMENTATION_STATUS_CHECKPOINT.md` for:
- Latest bug fixes
- Known issues
- Upcoming features

---

## Additional Resources

### Interactive Notebooks (`notebooks/`)

ADEPT provides comprehensive Jupyter notebooks organized by role and skill level. These are perfect for structured learning and experimentation.

#### Getting Started (Essential for all users)
**Path**: [`notebooks/00-setup/`](../notebooks/00-setup/)

Before diving into vibe coding via Streamlit, familiarize yourself with the platform through these setup notebooks:

1. **`00_environment_setup.ipynb`** - Environment verification
   - Check service health
   - Validate connectivity
   - Test authentication

2. **`01_authentication.ipynb`** - Keycloak authentication
   - Understand JWT tokens
   - Test API access
   - Manage credentials

#### End User Notebooks
**Path**: [`notebooks/01-end-user/`](../notebooks/01-end-user/)

Once you're comfortable with vibe coding in Streamlit, explore these notebooks to:
- **Deepen understanding** of chat workflows and file operations
- **Learn advanced techniques** for scientific workflows
- **Experiment** with multi-agent collaboration patterns
- **Build confidence** with interactive examples

**Topics Covered**:
- Chat with AI agents (similar to Streamlit but with more control)
- File upload/processing workflows
- Scientific domain examples (bioinformatics, chemistry)
- Multi-agent team orchestration
- Advanced use cases and patterns

**When to Use**:
- When you want to understand ADEPT API internals
- When Streamlit UI doesn't provide enough control
- When building custom integrations
- For batch processing or automation scripts

#### Developer Notebooks (For advancing your skills)
**Path**: [`notebooks/02-developer/`](../notebooks/02-developer/)

As you become more comfortable, these notebooks help you:
- Use the ADEPT SDK directly (bypass Streamlit)
- Build custom MCP tools for your domain
- Create specialized agents
- Integrate ADEPT into your own applications

**Progression Path**:
1. Start with **Streamlit vibe coding** (this guide)
2. Explore **01-end-user notebooks** for deeper understanding
3. Advance to **02-developer notebooks** to build custom solutions

#### Quick Access

```bash
# Start JupyterLab (already running in your deployment)
# Access: http://localhost:8888
# Token: Check with `docker logs jupyterlab`

# Navigate to:
# 1. notebooks/00-setup/00_environment_setup.ipynb (start here)
# 2. notebooks/01-end-user/ (explore after Streamlit practice)
# 3. notebooks/02-developer/ (when ready to build custom tools)
```

**Documentation**: See [`notebooks/README.md`](../notebooks/README.md) for complete notebook catalog.

---

### Code Examples (`examples/`)

The `examples/` directory contains production-ready integration patterns, particularly useful if you're building external applications that use ADEPT.

#### LangGraph Integration (Advanced)

**Purpose**: Integrate ADEPT into existing LangGraph applications (for Python developers).

**Files**:
- **`langgraph_adept_quickstart.py`** - Minimal 60-line example
- **`langgraph_adept_integration.py`** - Full production example (500+ lines)
- **`README.md`** - Usage guide and troubleshooting

**When This Is Relevant**:
- You have an existing LangGraph application
- You want to use ADEPT as the LLM backend
- You're building a custom Python application with multi-agent workflows

**Key Insight**: ADEPT implements its own model (`agentic-framework:scientific-agent-v1`) - it's NOT a proxy to OpenAI/Anthropic.

**Example Usage**:
```python
from litellm import completion

# Authenticate with Keycloak
token = get_adept_token("notebook-user", "password")

# Call ADEPT API
response = completion(
    model="agentic-framework:scientific-agent-v1",  # ADEPT's model
    messages=[{"role": "user", "content": "Analyze protein structure"}],
    base_url="https://api.agentic.local/v1",
    api_key=f"Bearer {token}",
    extra_headers={"X-Thread-Id": "my-analysis"},
)
```

**Documentation**: See [`docs/integration/LANGGRAPH_ADEPT_INTEGRATION_GUIDE.md`](../docs/integration/LANGGRAPH_ADEPT_INTEGRATION_GUIDE.md) for comprehensive guide.

**For Domain Scientists**: You typically don't need these examples unless you're building custom integrations. Stick with Streamlit vibe coding for your day-to-day work!

---

### Learning Path Recommendation

**For Domain Scientists (Your Primary Path)**:
```
1. This Guide (DOMAIN_SME_VIBE_CODING_GUIDE.md)
   └─> Learn vibe coding with Streamlit ← START HERE

2. Notebooks (notebooks/01-end-user/)
   └─> Deepen understanding after Streamlit practice

3. Examples (examples/) [OPTIONAL]
   └─> Only if building custom integrations
```

**Quick Reference Matrix**:

| Task | Use This | When |
|------|----------|------|
| **Interactive model development** | **Streamlit v2** | Daily work, rapid prototyping |
| **Structured learning** | **Jupyter notebooks** | Understanding concepts, experiments |
| **Custom integrations** | **Python examples** | Building external applications |
| **Batch processing** | **SDK + notebooks** | Automation, large-scale analysis |
| **Team collaboration** | **Streamlit + file upload** | Sharing results, reproducibility |

---

## Additional Resources

### Code Examples (`examples/`)

The `examples/` directory provides **standalone code examples** that work WITHOUT installing the ADEPT framework.

#### Service Token Authentication (New!)

**File**: `examples/openai_client_service_token_example.py`

For automation scripts and non-interactive access:

```bash
# 1. Install minimal dependencies
pip install -r examples/requirements.txt

# 2. Get service token from admin
export ADEPT_SERVICE_API_TOKEN="sk-service-..."

# 3. Run standalone example
python examples/openai_client_service_token_example.py
```

**Features**:
- Works WITHOUT ADEPT framework installation
- No login UI required (bearer token authentication)
- Long-lived tokens (90 days default)
- Ideal for automation, CI/CD, external services

**When to Use**:
- Integrating ADEPT into your own Python scripts
- Building automation workflows
- External service integration (n8n, custom tools)
- CI/CD pipelines

#### LangGraph Integration

**Files**:
- `examples/langgraph_adept_quickstart.py` - Minimal example
- `examples/langgraph_adept_integration.py` - Full multi-agent workflow

For building custom AI agent workflows:

```bash
# Install dependencies
pip install -r examples/requirements.txt

# Run quick start
export KEYCLOAK_USERNAME="notebook-user"
export KEYCLOAK_PASSWORD="your_password"
python examples/langgraph_adept_quickstart.py
```

**Use Cases**:
- Building custom agent workflows
- Multi-agent orchestration
- Integrating ADEPT into existing LangGraph applications

#### Standalone Requirements

**File**: `examples/requirements.txt`

Minimal dependencies for running examples:
- `openai>=1.12.0` - OpenAI-compatible client
- `httpx>=0.27.0` - HTTP client for authentication
- `langgraph>=0.0.20` - Multi-agent workflows
- `langchain-core>=0.1.20` - Message handling
- `litellm>=1.30.0` - Unified LLM client

**Installation**:
```bash
pip install -r examples/requirements.txt
```

#### Docker Support

**File**: `examples/Dockerfile`

For isolated, reproducible execution:

```bash
# Build standalone mode (minimal dependencies)
docker build -t adept-examples:standalone --target standalone examples/

# Run service token example
docker run --rm --network=agentic_framework_network \
    -e ADEPT_SERVICE_API_TOKEN="sk-service-..." \
    adept-examples:standalone \
    python /app/examples/openai_client_service_token_example.py
```

### Interactive Notebooks (`notebooks/`)

#### Progression Path:

1. **Start with Streamlit vibe coding** (this guide)
2. **Explore 01-end-user notebooks** for deeper understanding
3. **Advance to 02-developer notebooks** to build custom solutions
4. **Reference examples/** for external integrations

#### Notebook Categories:

- **00-setup**: Environment setup and authentication
- **01-end-user**: Data analysis, visualization, scientific workflows
- **02-developer**: Building custom agents, tool integration
- **03-operator**: System administration, deployment, monitoring

### Documentation

- **LangGraph Integration**: `docs/integration/LANGGRAPH_ADEPT_INTEGRATION_GUIDE.md`
- **Systems Administration**: `docs/SYSTEMS_ADMINISTRATOR_ONBOARDING.md`
- **Platform Engineering**: `docs/PLATFORM_AI_ENGINEER_ONBOARDING.md`

---

## Conclusion

ADEPT's vibe coding environment empowers domain scientists to leverage AI for computational work without deep programming expertise. While there are current limitations, the platform enables:

- **Rapid prototyping** of scientific models
- **Interactive data exploration** with natural language
- **Literature-informed** code generation
- **Collaborative** AI-assisted development

Remember: Vibe coding is about iteration and collaboration with AI. Don't aim for perfection on the first try - build progressively, test frequently, and refine continuously.

Happy vibe coding!
