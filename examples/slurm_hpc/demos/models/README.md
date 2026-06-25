# GEM Models for ADEPT COBRApy/Gurobi Demos

## Bundled Models

- `simple_pathway.xml` — Minimal 5-reaction SBML model (glucose → biomass). Expected FBA result: 10.0. Used for CI/E2E validation.

## External Models (download for full-scale testing)

### iJN1463 — Pseudomonas putida KT2440

A genome-scale metabolic model with 2583 reactions, 1963 metabolites, and 1463 genes. Exercises Gurobi at production scale.

**Download:**
```bash
# From BiGG Models database
curl -L "http://bigg.ucsd.edu/static/models/iJN1463.xml.gz" | gunzip > models/iJN1463.xml

# Or via Python
python3 -c "
import cobra
model = cobra.io.load_json_model(cobra.io.load_model('iJN1463'))
cobra.io.write_sbml_model(model, 'models/iJN1463.xml')
print(f'Loaded: {model.id} ({len(model.reactions)} rxns, {len(model.metabolites)} mets)')
"
```

**Usage with demo:**
```bash
python demos/cobrapy_fba_deception.py --user rigo160 --model demos/models/iJN1463.xml --build-sif
```

**Expected result:** Optimal biomass flux ~0.87 (with default media constraints).

### E. coli Core (iAF1260)

A well-characterized reduced model (95 reactions). Good for quick validation.

```bash
curl -L "http://bigg.ucsd.edu/static/models/e_coli_core.xml.gz" | gunzip > models/e_coli_core.xml
```

**Expected result:** Optimal biomass flux ~0.874 (glucose minimal media).

## Usage Pattern

Upload model to Deception workspace, then reference in job submission:

```bash
# Upload to workspace
scp models/iJN1463.xml rigo160@deception.pnl.gov:/people/rigo160/adept-workspace/inputs/

# Run via demo CLI
python demos/cobrapy_fba_deception.py --user rigo160 \
    --model demos/models/iJN1463.xml --skip-preflight

# Or via ADEPT MCP (natural language):
# "Run FBA on the iJN1463 Pseudomonas model using Gurobi on Deception"
```
