# Getting Started: Domain Scientists

ADEPT provides a natural language interface for scientific workflows. Biologists, chemists, physicists, and data scientists can interact with 28+ specialized tools through conversational chat — no programming required.

---

## Prerequisites

- A running ADEPT instance (local Docker Compose or cloud deployment)
- Valid user credentials (provided by your system administrator)
- A web browser

---

## Connecting to ADEPT

ADEPT exposes two primary interfaces for domain scientists:

| Interface | Best For |
|-----------|----------|
| OpenWebUI | General chat, file uploads, multi-turn conversations |
| JupyterLab | Notebook-style workflows, inline visualizations |

Your administrator will provide the URL and login credentials. Authentication uses single sign-on via Keycloak.

---

## Example Workflows

### Protein Sequence Search (BLAST)

```text
User: Run a BLAST search for this sequence against the nr database:
      MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVK

Agent: I'll run a BLAST search against the NCBI nr database...
       [Results: top 10 hits with E-values, identity percentages, and organism names]
```

### Literature RAG Query

Upload a collection of PDFs, then query them conversationally:

```text
User: Upload these 5 papers on CRISPR-Cas9 delivery mechanisms.
Agent: Files uploaded and indexed. Ready for queries.

User: What delivery vectors show the highest in vivo efficiency across these papers?
Agent: Based on the uploaded literature, lipid nanoparticles (LNPs) show the
       highest in vivo efficiency at 70-90% editing rates...
```

### Sandboxed Code Execution

```text
User: Calculate the binding free energy using the MM-PBSA method for this
      protein-ligand complex. Here's the trajectory data.

Agent: I'll write and execute a Python script using MDAnalysis...
       [Executes code in isolated sandbox, returns results and plots]
```

---

## Available Tools

| Category | Tools | Description |
|----------|-------|-------------|
| Bioinformatics | BLAST, UniProt, AlphaFold | Sequence search, protein data, structure prediction |
| Chemistry | PubChem | Compound properties, similarity search |
| Literature | ChromaDB RAG | Upload and query PDFs, CSVs, documents |
| Code Execution | Sandbox | Run Python/R in isolated containers |
| Web | Web Search | Search and summarize web content |
| Data | CSV Processing, File Management | Upload, transform, and analyze tabular data |
| HPC | Nextflow Pipelines | Submit and monitor HPC workflows |

!!! info "Tool Discovery"
    Ask the agent "What tools do you have available?" to see the full list of tools accessible in your current session.

---

## Multi-Agent Teams

For complex problems, ADEPT can assemble teams of specialized agents:

```text
User: Create a team with a biologist and a data scientist to analyze this
      proteomics dataset and identify differentially expressed proteins.

Agent: Creating multi-agent session with roles: biologist, data_scientist...
       [Biologist agent interprets biological significance]
       [Data scientist agent handles statistical analysis]
       [Results synthesized into a unified response]
```

Each agent receives domain-specific instructions and can use the full tool suite.

---

## File Upload and Processing

ADEPT supports uploading and processing multiple file types:

- **CSV/TSV**: Automatic schema detection, RAG indexing, SQL querying
- **PDF**: Text extraction, chunking, vector embedding for RAG
- **Code files**: Syntax-aware processing
- **Images**: Inline display in responses

!!! tip "Batch Processing"
    Upload multiple files at once for batch indexing. Use "Create a RAG index from my uploaded files" to build a searchable knowledge base.

---

## Session Continuity

ADEPT maintains conversation context across long sessions:

- **Auto-compaction**: Long conversations are automatically summarized to stay within context limits
- **Thread persistence**: Return to previous conversations by thread ID
- **Session isolation**: Your files and data are isolated from other users

---

## Tips

- Be specific about databases and parameters when requesting searches (e.g., "BLAST against SwissProt" vs "BLAST against nr")
- Upload reference documents before asking questions about them
- For reproducibility, ask the agent to show its code before executing
- Use multi-agent teams for interdisciplinary problems that benefit from multiple perspectives
- Large file uploads are processed asynchronously; the agent will notify you when indexing completes
