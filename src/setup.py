#!/usr/bin/env python3
"""
Setup script for Agentic Framework SDK
"""

from setuptools import setup, find_packages
import os

# Read requirements
def read_requirements(filename):
    """Read requirements from file."""
    path = os.path.join(os.path.dirname(__file__), filename)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return []

# Read long description
def read_long_description():
    """Read long description from README."""
    readme_path = os.path.join(os.path.dirname(__file__), 'agentic_framework_sdk', 'README.md')
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()
    return "Agentic Framework SDK - OpenAI-compatible scientific AI toolkit"

setup(
    name="agentic-framework-sdk",
    version="1.0.0", 
    description="OpenAI-compatible SDK for scientific AI workflows with UCS extensions",
    long_description=read_long_description(),
    long_description_content_type="text/markdown",
    author="Paul Rigor",
    author_email="paul.rigor@pnnl.gov",
    url="https://github.com/pnnl/agentic-framework",
    packages=find_packages(),  # Now finds agentic_framework_sdk/ from src/ directory
    python_requires=">=3.11,<3.12",
    install_requires=[
        "httpx>=0.24.0",
        "pydantic>=2.0.0",
        "typing-extensions>=4.0.0",
        "click>=8.0.0",
        "rich>=13.0.0",
        "requests>=2.31.0",
        "PyJWT>=2.12.1,<3.0.0",  # SECURITY: CVE-2026-32597 crit header fix (ADEPT-SEC-2026-002)
    ],
    extras_require={
        "cli": [
            "click>=8.0.0",
            "rich>=13.0.0",
            "prompt-toolkit>=3.0.0",
        ],
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.20.0",
            "pytest-mock>=3.0.0",
            "black>=23.0.0",
            "isort>=5.0.0",
            "mypy>=1.0.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "agentic=agentic_framework_sdk.cli.main:cli",
            "agentic-chat=agentic_framework_sdk.cli.main:cli",
            "agentic-cli=agentic_framework_sdk.bin.agentic_cli:main",
            "agentic-init=agentic_framework_sdk.bin.init_external_cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    keywords="ai, openai, scientific, bioinformatics, chemistry, research, agent, workflow",
    project_urls={
        "Documentation": "https://github.com/pnnl/agentic-framework/docs",
        "Source": "https://github.com/pnnl/agentic-framework",
        "Tracker": "https://github.com/pnnl/agentic-framework/issues",
    },
)