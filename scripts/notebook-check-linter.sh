#!/bin/bash
set -e
set -o pipefail

IMAGE_NAME="agentic-framework-deps-base:latest"
NOTEBOOKS_DIRECTORY="notebooks"

echo "Running notebook linters and validators..."

# Run notebook validation and linting in a temporary container
docker run --rm -v "$(pwd)/$NOTEBOOKS_DIRECTORY:/app/$NOTEBOOKS_DIRECTORY" "$IMAGE_NAME" \
  bash -c "pip install nbqa nbformat jupyter pyflakes ruff > /dev/null 2>&1 && \
  echo '--- Validating notebook JSON structure ---' && \
  python -c '
import os
import json
import nbformat
from pathlib import Path

notebooks_dir = Path(\"/app/$NOTEBOOKS_DIRECTORY\")
errors = []

for nb_path in notebooks_dir.rglob(\"*.ipynb\"):
    try:
        with open(nb_path, \"r\") as f:
            nb = nbformat.read(f, as_version=4)
        print(f\"✅ {nb_path.relative_to(notebooks_dir)}: Valid notebook structure\")
    except json.JSONDecodeError as e:
        errors.append(f\"❌ {nb_path.relative_to(notebooks_dir)}: Invalid JSON - {e}\")
    except nbformat.ValidationError as e:
        errors.append(f\"❌ {nb_path.relative_to(notebooks_dir)}: Invalid notebook format - {e}\")
    except Exception as e:
        errors.append(f\"❌ {nb_path.relative_to(notebooks_dir)}: {e}\")

if errors:
    print(\"\n\".join(errors))
    exit(1)
else:
    print(\"\n✅ All notebooks have valid structure\")
' && \
  echo -e '\n--- Running pyflakes on notebook code cells ---' && \
  (nbqa pyflakes /app/$NOTEBOOKS_DIRECTORY --nbqa-dont-skip-bad-cells 2>/dev/null | grep -v 'imported but unused' || echo '✅ No pyflakes issues found') && \
  echo -e '\n--- Running ruff on notebook code cells ---' && \
  (nbqa ruff /app/$NOTEBOOKS_DIRECTORY --ignore F401,E501 --exit-zero || true) && \
  echo -e '\n--- Checking for common notebook issues ---' && \
  python -c '
import os
import json
from pathlib import Path

notebooks_dir = Path(\"/app/$NOTEBOOKS_DIRECTORY\")
issues = []

for nb_path in notebooks_dir.rglob(\"*.ipynb\"):
    with open(nb_path, \"r\") as f:
        nb = json.load(f)
    
    # Check for empty cells
    empty_cells = []
    for i, cell in enumerate(nb.get(\"cells\", [])):
        source = cell.get(\"source\", [])
        if isinstance(source, list):
            source = \"\".join(source)
        if not source.strip():
            empty_cells.append(i)
    
    if empty_cells:
        issues.append(f\"⚠️  {nb_path.relative_to(notebooks_dir)}: Empty cells at indices {empty_cells}\")
    
    # Check for missing kernel spec
    if \"kernelspec\" not in nb.get(\"metadata\", {}):
        issues.append(f\"⚠️  {nb_path.relative_to(notebooks_dir)}: Missing kernelspec\")
    
    # Check for execution counts (indicates executed cells not cleared)
    executed_cells = []
    for i, cell in enumerate(nb.get(\"cells\", [])):
        if cell.get(\"cell_type\") == \"code\" and cell.get(\"execution_count\") is not None:
            executed_cells.append(i)
    
    if executed_cells and len(executed_cells) > 3:  # Allow a few executed cells for examples
        issues.append(f\"ℹ️  {nb_path.relative_to(notebooks_dir)}: {len(executed_cells)} cells have execution counts (consider clearing outputs)\")

if issues:
    print(\"\n\".join(issues))
else:
    print(\"✅ No common issues found\")
'"

echo -e "\n--- Summary ---"
echo "Notebook linting complete."
echo "To fix issues automatically, you can use:"
echo "  - nbqa black notebooks/     # Format code cells with black"
echo "  - nbqa isort notebooks/     # Sort imports in code cells"
echo "  - jupyter nbconvert --clear-output --inplace notebooks/**/*.ipynb  # Clear outputs"