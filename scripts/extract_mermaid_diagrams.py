#!/usr/bin/env python3
"""
Extract Mermaid diagrams from workshop presentation and create standalone files.
"""

import re
import sys
from pathlib import Path


def extract_mermaid_diagrams(markdown_file: Path, output_dir: Path):
    """Extract all Mermaid diagrams from markdown file."""

    output_dir.mkdir(parents=True, exist_ok=True)

    with open(markdown_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find all mermaid code blocks with context (slide number)
    slide_pattern = r'## Slide ([^:]+):[^\n]*\n(.*?)```mermaid\n(.*?)```'
    matches = re.findall(slide_pattern, content, re.DOTALL)

    diagrams = []
    for slide_num, context, diagram_code in matches:
        # Clean up slide number (e.g., "3A" or "15")
        slide_id = slide_num.strip().replace(' ', '_')

        # Extract diagram title from context (first line after slide header)
        lines = context.strip().split('\n')
        title = "Untitled"
        for line in lines:
            if line.strip() and not line.startswith('**') and not line.startswith('|'):
                title = line.strip().rstrip(':')
                break

        # Clean title for filename
        filename_base = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
        filename_base = re.sub(r'_+', '_', filename_base)[:50]  # Limit length

        diagrams.append({
            'slide_id': slide_id,
            'title': title,
            'filename_base': filename_base,
            'code': diagram_code.strip()
        })

    print(f"Found {len(diagrams)} Mermaid diagrams")

    # Write standalone .mmd files
    for i, diagram in enumerate(diagrams, 1):
        filename = f"slide_{diagram['slide_id']}_{diagram['filename_base']}.mmd"
        output_path = output_dir / filename

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# Slide {diagram['slide_id']}: {diagram['title']}\n")
            f.write(f"# Source: ADEPT_WORKSHOP_PRESENTATION_OUTLINE.md\n\n")
            f.write(diagram['code'])
            f.write('\n')

        print(f"{i}. Created {filename}")
        diagrams[i-1]['output_path'] = output_path

    return diagrams


def main():
    markdown_file = Path(__file__).parent.parent / "docs/workshop/ADEPT_WORKSHOP_PRESENTATION_OUTLINE.md"
    output_dir = Path(__file__).parent.parent / "docs/workshop/diagrams"

    if not markdown_file.exists():
        print(f"Error: {markdown_file} not found")
        sys.exit(1)

    diagrams = extract_mermaid_diagrams(markdown_file, output_dir)

    print(f"\n✅ Extracted {len(diagrams)} diagrams to {output_dir}")
    print(f"\nNext steps:")
    print(f"1. Generate PNG: mmdc -i <file>.mmd -o <file>.png")
    print(f"2. Generate SVG: mmdc -i <file>.mmd -o <file>.svg")

    return diagrams


if __name__ == "__main__":
    main()
