#!/bin/bash
# Generate workshop diagrams from Mermaid code in presentation outline
#
# Usage:
#   ./scripts/generate_workshop_diagrams.sh           # Generate all formats (PNG + SVG)
#   ./scripts/generate_workshop_diagrams.sh png       # Generate PNG only
#   ./scripts/generate_workshop_diagrams.sh svg       # Generate SVG only
#   ./scripts/generate_workshop_diagrams.sh --docker  # Use Docker instead of local mmdc

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Parse arguments
FORMAT="${1:-all}"
USE_DOCKER=""

if [[ "$1" == "--docker" ]] || [[ "$2" == "--docker" ]]; then
    USE_DOCKER="--docker"
    if [[ "$1" == "--docker" ]]; then
        FORMAT="${2:-all}"
    fi
fi

echo -e "${GREEN}==> Generating ADEPT Workshop Diagrams${NC}"
echo

# Check if Python script exists
if [[ ! -f "$SCRIPT_DIR/generate_workshop_diagrams.py" ]]; then
    echo -e "${RED}Error: generate_workshop_diagrams.py not found${NC}"
    exit 1
fi

# Check if workshop markdown file exists
MARKDOWN_FILE="$PROJECT_ROOT/docs/ADEPT_WORKSHOP_PRESENTATION_OUTLINE.md"
if [[ ! -f "$MARKDOWN_FILE" ]]; then
    echo -e "${RED}Error: Workshop markdown file not found: $MARKDOWN_FILE${NC}"
    exit 1
fi

# Check dependencies
if [[ -n "$USE_DOCKER" ]]; then
    echo -e "${YELLOW}--> Using Docker for Mermaid rendering${NC}"
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Error: Docker not found. Please install Docker or use local mmdc.${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}--> Using local Mermaid CLI (mmdc)${NC}"
    if ! command -v mmdc &> /dev/null; then
        echo -e "${RED}Error: Mermaid CLI (mmdc) not found.${NC}"
        echo -e "${YELLOW}Install with: npm install -g @mermaid-js/mermaid-cli${NC}"
        echo -e "${YELLOW}Or use Docker: $0 --docker${NC}"
        exit 1
    fi
fi

# Create output directory
OUTPUT_DIR="$PROJECT_ROOT/docs/diagrams/workshop"
mkdir -p "$OUTPUT_DIR"

echo -e "${GREEN}==> Running diagram generator${NC}"
echo

# Run Python script
cd "$PROJECT_ROOT"
python3 "$SCRIPT_DIR/generate_workshop_diagrams.py" \
    --format "$FORMAT" \
    --output-dir "$OUTPUT_DIR" \
    --markdown-file "$MARKDOWN_FILE" \
    $USE_DOCKER

echo
echo -e "${GREEN}==> Diagrams generated successfully!${NC}"
echo -e "${GREEN}    Output: $OUTPUT_DIR${NC}"
echo

# List generated files
echo -e "${YELLOW}Generated files:${NC}"
ls -lh "$OUTPUT_DIR" | grep -E '\.(png|svg|pdf)$' || echo "No diagram files found"

echo
echo -e "${GREEN}==> View diagrams:${NC}"
echo -e "    Index: $OUTPUT_DIR/README.md"
echo
