#!/usr/bin/env python3
"""
Generate images from Mermaid diagrams in workshop presentation outline.

This script extracts all Mermaid diagrams from the workshop markdown file
and generates PNG and SVG images using the Mermaid CLI.

Prerequisites:
    - Node.js 18+ installed
    - @mermaid-js/mermaid-cli installed: npm install -g @mermaid-js/mermaid-cli
    - Or use Docker: docker pull minlag/mermaid-cli

Usage:
    python scripts/generate_workshop_diagrams.py
    python scripts/generate_workshop_diagrams.py --format png
    python scripts/generate_workshop_diagrams.py --format svg
    python scripts/generate_workshop_diagrams.py --docker

Output:
    docs/diagrams/workshop/
    ├── 01_three_tier_architecture.png
    ├── 01_three_tier_architecture.svg
    ├── 02_standard_request_flow.png
    ├── 02_standard_request_flow.svg
    └── ...
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


class MermaidDiagramExtractor:
    """Extract Mermaid diagrams from markdown files."""

    def __init__(self, markdown_file: Path):
        self.markdown_file = markdown_file
        self.diagrams: List[Tuple[str, str, str]] = []

    def extract_diagrams(self) -> List[Tuple[str, str, str]]:
        """
        Extract all Mermaid diagrams from markdown file.

        Returns:
            List of tuples: (diagram_name, diagram_code, slide_reference)
        """
        with open(self.markdown_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Pattern to match mermaid code blocks
        pattern = r'```mermaid\n(.*?)```'
        matches = re.findall(pattern, content, re.DOTALL)

        # Extract context (slide number and title) for each diagram
        for idx, diagram_code in enumerate(matches, start=1):
            # Find the slide context (look backward for ## Slide N: Title)
            pos = content.find(diagram_code)
            before_text = content[:pos]

            # Find the last slide heading before this diagram
            slide_match = re.findall(r'## Slide (\d+): (.+)', before_text)

            if slide_match:
                slide_num, slide_title = slide_match[-1]
                diagram_name = self._generate_diagram_name(idx, slide_title)
            else:
                diagram_name = f"{idx:02d}_diagram"

            slide_reference = f"Slide {slide_num}: {slide_title}" if slide_match else f"Diagram {idx}"

            self.diagrams.append((diagram_name, diagram_code.strip(), slide_reference))

        return self.diagrams

    def _generate_diagram_name(self, idx: int, slide_title: str) -> str:
        """
        Generate a clean filename from slide title.

        Args:
            idx: Diagram index
            slide_title: Slide title text

        Returns:
            Clean filename (e.g., "01_three_tier_architecture")
        """
        # Clean title: lowercase, replace spaces with underscores, remove special chars
        clean_title = re.sub(r'[^\w\s-]', '', slide_title.lower())
        clean_title = re.sub(r'[-\s]+', '_', clean_title)
        clean_title = clean_title[:50]  # Limit length

        return f"{idx:02d}_{clean_title}"


class MermaidRenderer:
    """Render Mermaid diagrams to images."""

    def __init__(self, output_dir: Path, use_docker: bool = False):
        self.output_dir = output_dir
        self.use_docker = use_docker
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def check_dependencies(self) -> bool:
        """
        Check if required tools are available.

        Returns:
            True if dependencies are met, False otherwise
        """
        if self.use_docker:
            try:
                result = subprocess.run(
                    ['docker', '--version'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                print(f"✅ Docker available: {result.stdout.strip()}")
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("❌ Docker not found. Install Docker or use --no-docker flag.")
                return False
        else:
            try:
                result = subprocess.run(
                    ['mmdc', '--version'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                print(f"✅ Mermaid CLI available: {result.stdout.strip()}")
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("❌ Mermaid CLI (mmdc) not found.")
                print("   Install with: npm install -g @mermaid-js/mermaid-cli")
                print("   Or use --docker flag to use Docker image.")
                return False

    def render_diagram(
        self,
        diagram_name: str,
        diagram_code: str,
        output_format: str = 'png'
    ) -> bool:
        """
        Render a single Mermaid diagram to image.

        Args:
            diagram_name: Output filename (without extension)
            diagram_code: Mermaid diagram code
            output_format: Output format ('png', 'svg', 'pdf')

        Returns:
            True if successful, False otherwise
        """
        # Create temporary mermaid file
        temp_mmd = self.output_dir / f"{diagram_name}.mmd"
        output_file = self.output_dir / f"{diagram_name}.{output_format}"

        try:
            # Write diagram code to temp file
            with open(temp_mmd, 'w', encoding='utf-8') as f:
                f.write(diagram_code)

            # Render with mmdc or Docker
            if self.use_docker:
                cmd = [
                    'docker', 'run', '--rm',
                    '-v', f'{self.output_dir.absolute()}:/data',
                    'minlag/mermaid-cli',
                    '-i', f'/data/{diagram_name}.mmd',
                    '-o', f'/data/{diagram_name}.{output_format}',
                    '-t', 'default',
                    '-b', 'transparent'
                ]
            else:
                cmd = [
                    'mmdc',
                    '-i', str(temp_mmd),
                    '-o', str(output_file),
                    '-t', 'default',
                    '-b', 'transparent'
                ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )

            # Clean up temp file
            temp_mmd.unlink()

            print(f"✅ Generated: {output_file}")
            return True

        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to render {diagram_name}: {e.stderr}")
            # Clean up temp file on error
            if temp_mmd.exists():
                temp_mmd.unlink()
            return False
        except Exception as e:
            print(f"❌ Error rendering {diagram_name}: {e}")
            if temp_mmd.exists():
                temp_mmd.unlink()
            return False


def main():
    parser = argparse.ArgumentParser(
        description='Generate images from Mermaid diagrams in workshop presentation'
    )
    parser.add_argument(
        '--format',
        choices=['png', 'svg', 'pdf', 'all'],
        default='all',
        help='Output format (default: all)'
    )
    parser.add_argument(
        '--docker',
        action='store_true',
        help='Use Docker image instead of local mmdc'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path('docs/diagrams/workshop'),
        help='Output directory for diagrams'
    )
    parser.add_argument(
        '--markdown-file',
        type=Path,
        default=Path('docs/ADEPT_WORKSHOP_PRESENTATION_OUTLINE.md'),
        help='Workshop markdown file'
    )

    args = parser.parse_args()

    # Check if markdown file exists
    if not args.markdown_file.exists():
        print(f"❌ Markdown file not found: {args.markdown_file}")
        sys.exit(1)

    print(f"📄 Extracting diagrams from: {args.markdown_file}")

    # Extract diagrams
    extractor = MermaidDiagramExtractor(args.markdown_file)
    diagrams = extractor.extract_diagrams()

    if not diagrams:
        print("❌ No Mermaid diagrams found in markdown file.")
        sys.exit(1)

    print(f"✅ Found {len(diagrams)} Mermaid diagrams")
    print()

    # List diagrams
    print("Diagrams to generate:")
    for diagram_name, _, slide_ref in diagrams:
        print(f"  - {diagram_name} ({slide_ref})")
    print()

    # Initialize renderer
    renderer = MermaidRenderer(args.output_dir, use_docker=args.docker)

    # Check dependencies
    if not renderer.check_dependencies():
        sys.exit(1)

    print()
    print(f"🎨 Rendering diagrams to: {args.output_dir}")
    print()

    # Determine formats to generate
    if args.format == 'all':
        formats = ['png', 'svg']
    else:
        formats = [args.format]

    # Render diagrams
    success_count = 0
    total_count = len(diagrams) * len(formats)

    for diagram_name, diagram_code, slide_ref in diagrams:
        print(f"📊 Rendering: {diagram_name} ({slide_ref})")

        for fmt in formats:
            if renderer.render_diagram(diagram_name, diagram_code, fmt):
                success_count += 1

        print()

    # Summary
    print("=" * 60)
    print(f"✅ Successfully generated {success_count}/{total_count} images")
    print(f"📁 Output directory: {args.output_dir.absolute()}")
    print()

    # Generate index file
    index_file = args.output_dir / "README.md"
    with open(index_file, 'w', encoding='utf-8') as f:
        f.write("# ADEPT Workshop Diagrams\n\n")
        f.write("Auto-generated from Mermaid diagrams in workshop presentation outline.\n\n")
        f.write(f"**Generated**: {subprocess.check_output(['date']).decode().strip()}\n\n")
        f.write("## Diagrams\n\n")

        for diagram_name, _, slide_ref in diagrams:
            f.write(f"### {diagram_name.replace('_', ' ').title()}\n\n")
            f.write(f"**Source**: {slide_ref}\n\n")

            for fmt in formats:
                output_file = f"{diagram_name}.{fmt}"
                if (args.output_dir / output_file).exists():
                    f.write(f"- [{fmt.upper()}](./{output_file})\n")

            # Show PNG preview if it exists
            png_file = f"{diagram_name}.png"
            if (args.output_dir / png_file).exists():
                f.write(f"\n![{diagram_name}](./{png_file})\n\n")

            f.write("---\n\n")

    print(f"📋 Generated index: {index_file}")
    print()
    print("🎉 Done!")


if __name__ == '__main__':
    main()
