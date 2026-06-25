#!/usr/bin/env python3
"""COBRApy FBA optimization job script for Deception HPC.

This script is submitted to Deception via sbatch. It either:
  1. Builds a simple 3-reaction metabolic network (default demo)
  2. Loads a GEM from an SBML XML file (when path passed as argument)

Both modes solve using Gurobi via COBRApy's Flux Balance Analysis (FBA).

Expected environment on Deception compute nodes:
    module load python/3.11
    module load gurobi/11.0
    # or: apptainer exec adept-cobrapy.sif python3 cobrapy_fba_job.py [model.xml]

Usage:
    python3 cobrapy_fba_job.py                           # built-in 3-reaction model
    python3 cobrapy_fba_job.py /path/to/e_coli_core.xml  # load SBML GEM

Output: structured line "RESULT:optimal_value=<float>" for machine parsing.
Exit 0 on success, 1 on solver failure.
"""

import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("adept.cobrapy_fba")

try:
    import cobra
except ImportError:
    logger.error("cobra not available. Install with: pip install cobra")
    sys.exit(1)

try:
    import gurobipy
except ImportError:
    logger.error("gurobipy not available. Install with: pip install gurobipy")
    sys.exit(1)


def build_simple_model() -> cobra.Model:
    """Build a minimal metabolic model: glucose -> biomass pathway.

    Network topology:
        v1: -> A  (glucose uptake, bounded at 10)
        v2: A -> B  (glycolysis)
        v3: B ->    (biomass production, objective)

    Expected optimal value: 10.0 (bounded by v1 upper limit)
    """
    model = cobra.Model("simple_fba_demo")

    A = cobra.Metabolite("A", name="Metabolite A", compartment="c")
    B = cobra.Metabolite("B", name="Metabolite B", compartment="c")

    v1 = cobra.Reaction("v1")
    v1.name = "Glucose uptake"
    v1.lower_bound = 0
    v1.upper_bound = 10.0
    v1.add_metabolites({A: 1.0})

    v2 = cobra.Reaction("v2")
    v2.name = "Glycolysis"
    v2.lower_bound = 0
    v2.upper_bound = 1000.0
    v2.add_metabolites({A: -1.0, B: 1.0})

    v3 = cobra.Reaction("v3")
    v3.name = "Biomass"
    v3.lower_bound = 0
    v3.upper_bound = 1000.0
    v3.add_metabolites({B: -1.0})

    model.add_reactions([v1, v2, v3])
    model.objective = "v3"

    return model


def load_sbml_model(xml_path: str) -> cobra.Model:
    """Load a GEM from an SBML XML file."""
    path = Path(xml_path)
    if not path.exists():
        logger.error("Model file not found: %s", xml_path)
        sys.exit(1)

    logger.info("Loading SBML model from: %s", xml_path)
    model = cobra.io.read_sbml_model(str(path))
    logger.info(
        "Loaded: %s (%d reactions, %d metabolites, %d genes)",
        model.id, len(model.reactions), len(model.metabolites), len(model.genes),
    )
    return model


def main():
    logger.info("COBRApy version: %s", cobra.__version__)
    logger.info("Gurobi version: %s", str(gurobipy.grbversion()))

    # Determine model source
    if len(sys.argv) > 1:
        model = load_sbml_model(sys.argv[1])
    else:
        logger.info("No model file specified — using built-in 3-reaction demo model")
        model = build_simple_model()

    logger.info(
        "Model: %s (%d reactions, %d metabolites)",
        model.id, len(model.reactions), len(model.metabolites),
    )

    # Configure solver
    model.solver = "gurobi"
    logger.info("Solver: %s", model.solver.interface.__name__)

    # Run FBA
    logger.info("Running Flux Balance Analysis...")
    solution = model.optimize()

    if solution.status == "optimal":
        logger.info("Status: %s", solution.status)
        logger.info("Objective value: %.6f", solution.objective_value)

        # Print flux summary for top reactions
        fluxes = solution.fluxes
        nonzero = fluxes[fluxes.abs() > 1e-8].sort_values(ascending=False)
        logger.info("Non-zero fluxes: %d / %d reactions", len(nonzero), len(fluxes))
        for rxn_id, flux in nonzero.head(10).items():
            logger.info("  %s = %.4f", rxn_id, flux)

        # Machine-parseable output
        print(f"RESULT:optimal_value={solution.objective_value:.6f}")
        print(f"RESULT:status={solution.status}")
        print(f"RESULT:num_reactions={len(model.reactions)}")
        print(f"RESULT:num_nonzero_fluxes={len(nonzero)}")
        return 0
    else:
        logger.error("Solver failed with status: %s", solution.status)
        print(f"RESULT:status={solution.status}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
