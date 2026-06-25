# 🧬 Agentic Framework: Your AI Scientific Research Assistant

> **Transform your research with AI-powered scientific analysis tools**

Welcome to your personal AI research assistant! The Agentic Framework makes it easy to analyze data, search scientific literature, run complex calculations, and generate visualizations - all through simple conversation.

## 🚀 What Can You Do?

**Chat with AI to:**
- 📊 **Analyze your data files** - Upload CSV, Excel, or text files and get instant insights
- 🧬 **Research proteins & genes** - Get sequence analysis, BLAST searches, and protein properties  
- 🧪 **Look up compounds** - Find molecular properties, chemical structures, and drug information
- 📈 **Create visualizations** - Generate plots, charts, and graphs from your data
- 📚 **Search scientific literature** - Find relevant papers and research on any topic
- 🔬 **Run Python analyses** - Execute custom code for specialized research needs

## ⚡ Quick Start Guide (Updated)

### Step 1: Install the Research Assistant

**From PyPI (Recommended for end users)**:
```bash
# Install the CLI client
pip install agentic-framework-sdk[cli]
```

**From Source (For developers and contributors)**:
```bash
# Clone repository
git clone https://github.com/your-org/adept-extended-2025-11-07.git
cd adept-extended-2025-11-07

# Create Python 3.11 virtual environment
python3.11 -m venv .venv311
source .venv311/bin/activate  # On Windows: .venv311\Scripts\activate

# Install SDK in editable mode
pip install -e src/

# Verify installation
python -c "import agentic_framework_sdk; print('✅ SDK installed')"
agentic --help  # Shows available commands
```

**Troubleshooting Installation**:

If you see `ModuleNotFoundError: No module named 'agentic_framework_sdk'`:
```bash
# Ensure Python 3.11 is active
python --version  # Should be 3.11.x

# Uninstall any old installation
pip uninstall agentic-framework-sdk -y

# Reinstall from correct location
pip install -e src/
```

If you see `AttributeError: ... has no attribute 'main'`:
```bash
# You have an old installation with incorrect entry points
pip uninstall agentic-framework-sdk -y
pip install -e src/
```

### Step 2: One-Command Setup (Recommended)

**For external users connecting from HOST environment to Docker services:**

```bash
# 1. Ensure your /etc/hosts file contains:
echo "127.0.0.1 api.agentic.local" | sudo tee -a /etc/hosts

# 2. Complete setup with one command (validates environment + authenticates)
python3 agentic_cli.py --init

# This will:
# ✅ Validate your environment setup
# ✅ Generate authentication tokens via NGINX proxy  
# ✅ Configure CLI with proper settings
# ✅ Test the complete authentication flow
# ✅ Confirm all models and tools are accessible
```

### Step 3: Alternative Setup Methods

#### Option A: Step-by-Step Manual Setup
```bash
# 1. Validate environment first
python3 agentic_cli.py --check

# 2. Run initialization if validation passes
python3 agentic_cli.py --init

# 3. Test your setup
python3 agentic_cli.py auth test --external
```

#### Option B: Legacy Script-Based Setup (Still Supported)
```bash
# Using the original setup scripts
./scripts/agentic-cli-setup.sh --check
./scripts/agentic-cli-setup.sh auth login --external --username notebook-user
```

#### Option C: Manual Token Setup (Advanced Users)
```bash
# Get token and store it automatically
python3 scripts/init_external_cli.py

# Or set environment variables manually:
export AGENTIC_API_KEY="your-jwt-token"
export AGENTIC_BASE_URL="https://api.agentic.local/v1"
```

### Step 4: Start Your Research Session

```bash
# Launch the research assistant (with environment validation)
python3 agentic_cli.py chat

# Use direct CLI commands after initialization:
agentic chat --session my-research

# Or use the legacy wrapper:
./scripts/agentic-cli-setup.sh chat
```

### Step 5: Upload and Analyze Files

```bash
# In the chat interface, upload files with @filename:
You: Please analyze @my_data.csv and show trends

# The assistant will:
# ✅ Upload your file automatically
# ✅ Analyze the data structure  
# ✅ Generate insights and visualizations
# ✅ Answer follow-up questions
```

---

## 🔧 Current Implementation Status

### ✅ **What's Working NOW** (Updated August 2025)

**Authentication & Security:**
- ✅ **CLI Authentication Commands**: Full `auth login`, `auth status`, `auth test` functionality
- ✅ **External NGINX Proxy Access**: HOST users can connect via `api.agentic.local`
- ✅ **JWT Token Management**: Automatic token storage and validation
- ✅ **SSL/TLS Support**: Self-signed certificates handled properly
- ✅ **Environment Validation**: Comprehensive setup checking with `agentic-cli-setup.sh`

**File Upload & Processing:**
- ✅ **Session-Aware File Uploads**: Files include session context automatically
- ✅ **@filename Syntax**: Upload files directly in chat with `@my_file.csv`
- ✅ **File Analysis**: Agent can analyze CSV, TXT, PDF, and other formats
- ✅ **Multi-format Support**: Data files, documents, images, scientific formats

**Chat Interface & AI:**
- ✅ **Interactive Chat**: Full conversational AI with scientific tools
- ✅ **Session Management**: Persistent conversations with `--session` flag
- ✅ **Streaming & Non-streaming**: Choose response mode with `--stream/--no-stream`
- ✅ **Scientific Tools**: BLAST, PubChem, UniProt, literature search integrated

### 🚧 **Advanced Features** (Implementation Complete, Configuration Required)

**OAuth2 Device Flow:**
- ✅ **Full Implementation**: Complete `DeviceFlowAuth` class with PIN-based login
- ✅ **CLI Integration**: `--device-flow` flag available
- ⚙️ **Requires**: Keycloak server configuration for device authorization grants

**Production Deployment:**
- ✅ **Multi-cloud Architecture**: Azure/AWS/GCP infrastructure ready
- ✅ **Containerization**: Full Docker Compose with health monitoring
- ⚙️ **Requires**: Environment-specific configuration

### Testing Your Setup

```bash
# Environment validation only
python3 agentic_cli.py --check

# Full initialization (recommended first-time setup)
python3 agentic_cli.py --init

# Quick connection test  
agentic chat --test

# If everything works, you'll see:
# ✅ Connected to Agentic Framework
# ✅ Authentication successful  
# ✅ Scientific tools available
# 🧬 Ready for research!
```

---

## 💬 How to Use the Chat Interface

### Starting a Research Session

```bash
# Start a new research session
agentic chat

# Continue previous work (saves your conversation)
agentic chat --session my-protein-study

# Quick analysis without saving
agentic chat --no-save
```

### Example Research Conversations

#### 📊 **Data Analysis Example**
```
You: I have sales data in @sales_data.csv - can you analyze trends?

🧠 AI Research Assistant: I'll analyze your sales data right away!

[Uploads and analyzes the file]

✅ Analysis complete! Here's what I found:
- 📈 Sales increased 23% in Q3  
- 🎯 Top product: Widget A (34% of revenue)
- 📅 Best month: September ($45,2k)
- 📊 Generated trend visualization: sales_trends.png

Would you like me to create a detailed report or explore specific patterns?

You: Yes, show me seasonal patterns

AI: I'll create a seasonal analysis...
[Creates detailed seasonal breakdown with charts]
```

#### 🧬 **Protein Research Example**
```
You: What can you tell me about the protein sequence MKLLVLLLV?

🧠 AI Research Assistant: I'll analyze this protein sequence for you!

🔬 Running sequence analysis...
✅ BLAST search completed
✅ Structure prediction ready  
✅ Function analysis done

📋 Results:
- **Type**: Signal peptide (secretory protein)
- **Length**: 9 amino acids
- **Hydrophobicity**: Very high (secretion signal)
- **Similar sequences**: Found 847 matches in UniProt
- **Predicted function**: ER targeting signal

🧪 Would you like me to:
1. Show similar proteins
2. Predict 3D structure
3. Search for related research papers
```

#### 🧪 **Chemistry Research Example**
```
You: Find information about caffeine

🧬 AI Research Assistant: Let me look up caffeine information for you!

🔍 Searching PubChem database...
✅ Compound data retrieved

☕ **Caffeine (C₈H₁₀N₄O₂)**
- **IUPAC Name**: 1,3,7-Trimethylxanthine
- **Molecular Weight**: 194.19 g/mol  
- **Melting Point**: 235-238°C
- **Solubility**: 21.6 mg/mL in water
- **Bioactivity**: CNS stimulant, adenosine receptor antagonist

💊 **Pharmacology**: 
- Blocks adenosine A1 and A2A receptors
- Half-life: 3-5 hours in adults
- Peak plasma: 15-45 minutes after oral dose

Would you like me to find research papers about caffeine's effects?
```

### 📁 File Upload Magic

Upload files by typing `@` followed by the filename:

```
You: Analyze the data in @experiment_results.xlsx

# The AI will automatically:
# 1. Upload your file
# 2. Read and understand the format  
# 3. Analyze the data
# 4. Create visualizations if helpful
# 5. Provide insights and recommendations
```

**Supported file types:**
- 📊 **Data**: `.csv`, `.xlsx`, `.tsv`, `.json`
- 📝 **Text**: `.txt`, `.md`, `.doc`, `.pdf` 
- 🧬 **Scientific**: `.fasta`, `.pdb`, `.sdf`
- 🖼️ **Images**: `.png`, `.jpg`, `.svg`

### 💡 Pro Tips for Better Research

#### Ask Research-Focused Questions
```
✅ Good: "Compare the protein expression between these two samples"
❌ Basic: "What's in this file?"

✅ Good: "Find papers about CRISPR applications in cancer therapy from 2023"  
❌ Basic: "Tell me about CRISPR"

✅ Good: "Create a correlation matrix for these biomarkers"
❌ Basic: "Make a chart"
```

#### Use Session Management
```bash
# Organize your research projects
agentic chat --session "alzheimers-study-2024"
agentic chat --session "protein-folding-analysis"  
agentic chat --session "drug-discovery-project"

# List your research sessions
agentic sessions list
```

#### Get Help Anytime
```
You: /help
# Shows available commands and features

You: /examples
# Shows example research questions

You: /tools  
# Lists available scientific tools
```

---

## 🔧 Configuration Options

### Basic Settings
```bash
# View current settings
agentic config show

# Change your research server
agentic config set gateway_url https://api.agentic.local

# Set preferred AI model
agentic config set model scientific-workflow-agent

# Enable/disable automatic file saving
agentic config set auto_save true
```

### Connection Troubleshooting

#### If You See Connection Errors:

**"Connection refused" or "Cannot connect"**
```bash
# Try the secure external connection
agentic config set gateway_url https://api.agentic.local
agentic chat

# If that fails, try internal connection  
agentic config set gateway_url http://localhost:8081
agentic chat
```

**"Authentication failed"**
```bash
# Clear saved credentials and re-authenticate
agentic auth clear
agentic chat
# This will open a browser for fresh login
```

**"SSL certificate error"**
```bash
# For development/internal servers with self-signed certificates
agentic chat --insecure
```

### Advanced Configuration

Edit `~/.agentic/config.json` for advanced settings:

```json
{
  "gateway_url": "https://api.agentic.local",
  "model": "scientific-workflow-agent",
  "auto_save": true,
  "stream": true,
  "max_history": 100,
  "research_mode": "enabled",
  "file_upload_auto": true
}
```

---

## 🎯 Your Minimum Loveable Product Experience

We've designed this to be **incredibly simple** while **incredibly powerful**:

### ✨ **What "Just Works"**
- 🔐 **Authentication**: Automatic login - no tokens to manage
- 🌐 **Connection**: Smart endpoint detection - works from anywhere  
- 📁 **File Upload**: Drag, drop, or `@filename` - instant analysis
- 💾 **Session Saving**: Never lose your research progress
- 🎨 **Visualizations**: Auto-generated charts and graphs
- 📊 **Data Analysis**: Instant insights from any dataset
- 🧬 **Scientific Tools**: BLAST, PubChem, UniProt - all integrated

### 🚀 **Getting Value in Minutes**
1. **Minute 1**: `pip install agentic-framework-sdk[cli]`
2. **Minute 2**: `agentic chat` (automatic setup)
3. **Minute 3**: Upload your first file with `@data.csv`
4. **Minute 4**: Get analysis, insights, and visualizations
5. **Minute 5**: Ask follow-up questions and dive deeper

### 💪 **Power User Features (When You're Ready)**
- **Custom Python Code**: Run any analysis you can imagine
- **Literature Search**: Access to scientific databases and papers  
- **Multi-Session Management**: Organize complex research projects
- **Collaborative Sessions**: Share research with colleagues
- **Export & Reports**: Generate professional research summaries

---

## 🆘 Need Help?

### Quick Commands
```bash
agentic --help          # Show all available commands
agentic chat --help     # Chat-specific options  
agentic config --help   # Configuration help
agentic sessions --help # Session management
```

### Common Issues & Solutions

| Problem | Solution |
|---------|----------|
| 🚫 Can't connect | Try: `agentic config set gateway_url https://api.agentic.local` |
| 🔐 Authentication fails | Run: `agentic auth clear` then `agentic chat` |
| 📁 File upload errors | Check file size < 100MB and supported format |
| 🐌 Slow responses | Use: `agentic chat --no-stream` for better stability |
| 💾 Lost conversation | Run: `agentic sessions list` to find saved sessions |
| ⚠️ File operations fail | See **File Upload Issues** section below |

### 🚦 **Current Status & Validation**

#### **Comprehensive Testing Available**
```bash
# Run full end-to-end test suite
python3 test_end_to_end.py

# Individual component tests
./scripts/agentic-cli-setup.sh --check              # Environment validation
./scripts/agentic-cli-setup.sh auth test --external # Authentication test
python3 store_token.py                              # Token acquisition test
```

#### **Validated User Workflows**

**✅ Complete HOST-to-Docker Workflow:**
1. User runs environment validation → ✅ Working
2. User authenticates via external NGINX proxy → ✅ Working  
3. User starts chat client with stored token → ✅ Working
4. User uploads files with `@filename` syntax → ✅ Working
5. Agent analyzes files and provides insights → ✅ Working
6. Session persistence across conversations → ✅ Working

#### **Known Limitations & Solutions**

**Interactive Authentication Prompts:**
- ⚠️ **Issue**: Rich terminal prompts can fail in some environments
- ✅ **Solution**: Use `python3 store_token.py` for reliable token acquisition
- ✅ **Workaround**: Manual token setup via environment variables

**SSL Certificate Handling:**
- ⚠️ **Issue**: Self-signed certificates require special handling
- ✅ **Solution**: CLI automatically disables SSL verification for development
- ✅ **Status**: Production certificates can be added for external deployment

**Domain Resolution:**
- ⚠️ **Issue**: HOST environment must resolve `api.agentic.local`
- ✅ **Solution**: `/etc/hosts` entry automatically validated by setup script
- ✅ **Status**: Docker-external access pattern working correctly

#### **Migration from Manual Setup**

If you were using manual token setup previously:
```bash
# Old method (still works):
export AGENTIC_API_KEY="your-token"
export AGENTIC_BASE_URL="https://api.agentic.local/v1"

# New method (recommended):
python3 store_token.py                    # Get and store token
./scripts/agentic-cli-setup.sh chat      # Use wrapper script
```

### Getting Support
- 📖 **Documentation**: [Full technical docs](https://github.com/pnnl/agentic-framework/wiki)
- 🐛 **Report Issues**: [GitHub Issues](https://github.com/pnnl/agentic-framework/issues)  
- 💬 **Community**: [Discussion Forum](https://github.com/pnnl/agentic-framework/discussions)
- 📧 **Email Support**: [Contact Research Team](mailto:agentic-support@example.com)

---

## 🔬 What Makes This Special?

Unlike other AI tools, the Agentic Framework is built **specifically for researchers**:

- 🎯 **Research-First**: Every feature designed for scientific workflows
- 🔧 **Tool Integration**: Direct access to BLAST, PubChem, UniProt, and more
- 📊 **Data-Centric**: Upload any dataset and get instant analysis
- 🧬 **Domain Expertise**: Understands scientific terminology and methods
- 💾 **Reproducible**: Save sessions, export code, maintain research trails
- 🔒 **Secure**: Enterprise-grade authentication and data protection

## 🎉 Ready to Transform Your Research?

```bash
# Start your AI-powered research journey right now:
pip install agentic-framework-sdk[cli]
agentic chat

# That's it! Welcome to the future of scientific research! 🚀
```

---

*The Agentic Framework: Making AI-powered research accessible to every scientist, researcher, and curious mind.* 🧬✨