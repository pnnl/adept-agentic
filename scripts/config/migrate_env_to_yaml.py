#!/usr/bin/env python3
"""Generate config/llm.yaml from current environment variables.

Uses a local PURPOSE_ENV_VARS mapping (mirroring the runtime env-var
conventions) to resolve each purpose's model, detect provider from model
prefix, and emit a validated YAML config.

Usage:
    python scripts/config/migrate_env_to_yaml.py              # print to stdout
    python scripts/config/migrate_env_to_yaml.py --write      # write to config/llm.yaml
    python scripts/config/migrate_env_to_yaml.py --out /tmp/test.yaml
    python scripts/config/migrate_env_to_yaml.py --env-file .env  # read from .env file
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

PROVIDER_PREFIXES = ("bedrock/", "azure/", "openai/", "ollama/", "anthropic/", "vertex_ai/")

PURPOSE_ENV_VARS: Dict[str, str] = {
    "streamlit": "STREAMLIT_DEFAULT_MODEL",
    "embedding": "EMBEDDING_DEFAULT_MODEL",
    "rag": "RAG_DEFAULT_MODEL",
    "agent_main": "DEFAULT_LLM_MODEL",
    "agent_supervisor": "DEFAULT_LLM_MODEL",
    "agent_planner": "DEFAULT_LLM_MODEL",
    "coding_agent": "CODING_AGENT_DEFAULT_MODEL",
    "session_summary": "DEFAULT_LLM_MODEL",
    "generic": "DEFAULT_LLM_MODEL",
    "biology_agent": "BIOLOGY_AGENT_DEFAULT_MODEL",
    "chemistry_agent": "CHEMISTRY_AGENT_DEFAULT_MODEL",
    "data_scientist": "DATA_SCIENTIST_DEFAULT_MODEL",
    "hpc_agent": "HPC_AGENT_DEFAULT_MODEL",
}

PURPOSE_DESCRIPTIONS = {
    "agent_main": "Primary agent for reasoning and conversation",
    "agent_supervisor": "Multi-agent session supervisor",
    "agent_planner": "Multi-agent task planner",
    "coding_agent": "Code generation, debugging, and security reviews",
    "rag": "RAG query generation (CSV, PDF, knowledge base)",
    "streamlit": "Streamlit UI interactions",
    "session_summary": "Session summary generation",
    "embedding": "Text embeddings",
    "generic": "General fallback purpose",
    "biology_agent": "Biological data analysis, protein structure, genomics",
    "chemistry_agent": "Chemical analysis, reaction prediction, molecular design",
    "data_scientist": "Statistical analysis, ML pipelines, data visualization",
    "hpc_agent": "HPC job management, Slurm scripts, batch scheduling",
}


def parse_env_file(env_path: Path) -> Dict[str, str]:
    """Parse a .env file into a dict, ignoring comments and empty lines."""
    env_vars: Dict[str, str] = {}
    if not env_path.exists():
        return env_vars
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
        if match:
            key = match.group(1)
            val = match.group(2).strip().strip('"').strip("'")
            if not val.startswith("#"):
                env_vars[key] = val
    return env_vars


def detect_provider(model: str) -> Tuple[Optional[str], str]:
    """Detect provider from model prefix. Returns (provider, bare_model)."""
    for prefix in PROVIDER_PREFIXES:
        if model.startswith(prefix):
            provider = prefix.rstrip("/")
            bare_model = model[len(prefix):]
            return provider, bare_model
    return None, model


def resolve_env(key: str, env_overrides: Dict[str, str]) -> Optional[str]:
    """Resolve an env var from overrides first, then os.environ."""
    val = env_overrides.get(key) or os.environ.get(key)
    if val and not val.startswith("YOUR_") and val != "":
        return val
    return None


def build_yaml(env_overrides: Optional[Dict[str, str]] = None) -> str:
    """Build YAML config string from current environment."""
    env = env_overrides or {}

    default_model_raw = resolve_env("DEFAULT_LLM_MODEL", env)
    if not default_model_raw:
        print("WARNING: DEFAULT_LLM_MODEL not set. Using placeholder.", file=sys.stderr)
        default_model_raw = "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"

    default_provider, default_model = detect_provider(default_model_raw)
    if not default_provider:
        # Infer provider from available credentials
        if resolve_env("AZURE_API_KEY", env):
            default_provider = "azure"
        elif resolve_env("OPENAI_API_KEY", env):
            default_provider = "openai"
        elif resolve_env("AWS_ACCESS_KEY_ID", env):
            default_provider = "bedrock"
        else:
            default_provider = "azure"

    aws_region = resolve_env("AWS_REGION_NAME", env) or "us-west-2"
    azure_api_version = resolve_env("AZURE_API_VERSION", env) or "2024-12-01-preview"
    ollama_base = resolve_env("OLLAMA_API_BASE", env) or "http://localhost:11434"

    providers_seen = set()
    purposes_output = []

    for purpose, env_var in PURPOSE_ENV_VARS.items():
        model_raw = resolve_env(env_var, env)
        if not model_raw:
            purposes_output.append((purpose, None, None, None))
            continue

        provider, bare_model = detect_provider(model_raw)
        if provider:
            providers_seen.add(provider)

        if provider == default_provider and bare_model == default_model:
            purposes_output.append((purpose, None, None, None))
        else:
            purposes_output.append((purpose, provider, bare_model, model_raw))

    providers_seen.add(default_provider)

    lines = []
    lines.append("# ADEPT LLM Provider and Purpose Configuration")
    lines.append("# Generated by: python scripts/config/migrate_env_to_yaml.py")
    lines.append("#")
    lines.append("# Credentials use env var references (never inline secrets).")
    lines.append("# Activation: set LLM_CONFIG_PATH=config/llm.yaml")
    lines.append("")

    # Defaults
    lines.append("defaults:")
    lines.append(f"  provider: {default_provider}")
    lines.append(f"  model: {default_model}")
    lines.append("  temperature: 0.0")
    lines.append("  retry:")
    lines.append("    max_retries: 10")
    lines.append("    initial_delay_seconds: 1.0")
    lines.append("    max_delay_seconds: 60.0")
    lines.append("    backoff_multiplier: 2.0")
    lines.append("")

    # Providers
    lines.append("providers:")
    if "bedrock" in providers_seen:
        lines.append("  bedrock:")
        lines.append(f"    aws_region: {aws_region}")
        lines.append("    credentials:")
        lines.append("      aws_access_key_id_env: AWS_ACCESS_KEY_ID")
        lines.append("      aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY")
        lines.append("")

    if "azure" in providers_seen:
        lines.append("  azure:")
        lines.append(f'    api_version: "{azure_api_version}"')
        lines.append("    credentials:")
        lines.append("      api_key_env: AZURE_API_KEY")
        lines.append("      api_base_env: AZURE_API_BASE")
        lines.append("")

    if "openai" in providers_seen:
        lines.append("  openai:")
        lines.append("    credentials:")
        lines.append("      api_key_env: OPENAI_API_KEY")
        lines.append("")

    if "ollama" in providers_seen:
        lines.append("  ollama:")
        lines.append(f'    api_base: "{ollama_base}"')
        lines.append("")

    if "anthropic" in providers_seen:
        lines.append("  anthropic:")
        lines.append("    credentials:")
        lines.append("      api_key_env: ANTHROPIC_API_KEY")
        lines.append("")

    if "vertex_ai" in providers_seen:
        lines.append("  vertex_ai:")
        lines.append("    credentials:")
        lines.append("      api_key_env: VERTEX_AI_API_KEY")
        lines.append("")

    # Purposes
    lines.append("purposes:")
    for purpose, provider, bare_model, _raw in purposes_output:
        desc = PURPOSE_DESCRIPTIONS.get(purpose, "")
        lines.append(f"  {purpose}:")
        if desc:
            lines.append(f'    description: "{desc}"')
        if provider and provider != default_provider:
            lines.append(f"    provider: {provider}")
        if bare_model:
            lines.append(f"    model: {bare_model}")

        # Embedding-specific credentials
        if purpose == "embedding":
            embed_key_env = resolve_env("EMBEDDING_AZURE_API_KEY", env)
            embed_base_env = resolve_env("EMBEDDING_AZURE_API_BASE", env)
            embed_api_ver = resolve_env("EMBEDDING_AZURE_API_VERSION", env)
            if embed_key_env or embed_base_env:
                lines.append("    credentials:")
                if embed_key_env:
                    lines.append("      api_key_env: EMBEDDING_AZURE_API_KEY")
                if embed_base_env:
                    lines.append("      api_base_env: EMBEDDING_AZURE_API_BASE")
            if embed_api_ver:
                lines.append(f'    api_version: "{embed_api_ver}"')

        # Coding agent specific credentials
        if purpose == "coding_agent":
            coding_region = resolve_env("CODING_AGENT_AWS_REGION_NAME", env)
            coding_key = resolve_env("CODING_AGENT_AWS_ACCESS_KEY_ID", env)
            if coding_region:
                lines.append(f"    aws_region: {coding_region}")
            if coding_key:
                lines.append("    credentials:")
                lines.append("      aws_access_key_id_env: CODING_AGENT_AWS_ACCESS_KEY_ID")
                lines.append("      aws_secret_access_key_env: CODING_AGENT_AWS_SECRET_ACCESS_KEY")

        lines.append("")

    # Fallback
    lines.append("fallback:")
    lines.append(f"  provider: {default_provider}")
    lines.append(f"  model: {default_model}")
    lines.append("")

    # Role aliases (static, from model_catalog pattern)
    lines.append("role_aliases:")
    lines.append("  coder: coding_agent")
    lines.append("  developer: coding_agent")
    lines.append("  programmer: coding_agent")
    lines.append("  python_developer: coding_agent")
    lines.append("  software_engineer: coding_agent")
    lines.append("  biologist: biology_agent")
    lines.append("  genomics_researcher: biology_agent")
    lines.append("  protein_analyst: biology_agent")
    lines.append("  bioinformatician: biology_agent")
    lines.append("  chemist: chemistry_agent")
    lines.append("  materials_scientist: chemistry_agent")
    lines.append("  data_scientist: data_scientist")
    lines.append("  statistician: data_scientist")
    lines.append("  ml_engineer: data_scientist")
    lines.append("  hpc_engineer: hpc_agent")
    lines.append("  slurm_admin: hpc_agent")

    return "\n".join(lines) + "\n"


def validate_generated_yaml(yaml_content: str) -> bool:
    """Validate the generated YAML loads through LLMConfig."""
    import tempfile
    tmp_path = None
    try:
        from agentic_framework_pkg.core.llm_config import LLMConfig
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            tmp_path = f.name
            f.write(yaml_content)
            f.flush()
            config = LLMConfig.load(config_path=tmp_path)
            if config.source != "yaml":
                print(f"ERROR: Config loaded but source is '{config.source}', expected 'yaml'", file=sys.stderr)
                return False
            print(f"Validation passed: {len(config.purposes)} purposes, "
                  f"{len(config.providers)} providers, source=yaml", file=sys.stderr)
            return True
    except Exception as e:
        print(f"Validation FAILED: {e}", file=sys.stderr)
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def main():
    parser = argparse.ArgumentParser(
        description="Generate config/llm.yaml from current .env / environment variables"
    )
    parser.add_argument(
        "--write", action="store_true",
        help="Write output to config/llm.yaml (default: stdout)"
    )
    parser.add_argument(
        "--out", type=str, default=None,
        help="Write output to specified path"
    )
    parser.add_argument(
        "--env-file", type=str, default=None,
        help="Read env vars from a .env file (in addition to os.environ)"
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Validate generated YAML through LLMConfig.load()"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be written without writing (implies --validate)"
    )
    args = parser.parse_args()

    env_overrides: Dict[str, str] = {}
    if args.env_file:
        env_path = Path(args.env_file)
        if not env_path.exists():
            print(f"ERROR: --env-file '{args.env_file}' does not exist", file=sys.stderr)
            sys.exit(1)
        env_overrides = parse_env_file(env_path)
        print(f"Loaded {len(env_overrides)} variables from {args.env_file}", file=sys.stderr)

    yaml_content = build_yaml(env_overrides)

    if args.dry_run or args.validate:
        valid = validate_generated_yaml(yaml_content)
        if not valid:
            sys.exit(1)

    if args.dry_run:
        print(yaml_content)
        return

    if args.write:
        out_path = PROJECT_ROOT / "config" / "llm.yaml"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(yaml_content)
        print(f"Written to {out_path}", file=sys.stderr)
    elif args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(yaml_content)
        print(f"Written to {out_path}", file=sys.stderr)
    else:
        print(yaml_content)


if __name__ == "__main__":
    main()
