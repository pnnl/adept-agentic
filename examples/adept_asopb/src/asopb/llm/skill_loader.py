"""
SkillLoader: Load markdown skill files for LLM-assisted domain evaluation.

Skills are markdown documents that define domain scope, controls, scoring criteria,
patterns, and output formats. They serve as system prompts for the LLM evaluator.

Skill files are organized by domain:
  - d1_model_integrity.md
  - d2_orchestration.md
  - d3_tool_security.md
  - d4_identity.md
  - d5_federation.md
  - d6_observability.md
  - d7_itot.md
  - d8_supply_chain.md
"""

from pathlib import Path
from typing import Optional

from asopb.logging import get_logger

logger = get_logger(__name__)


class SkillLoader:
    """Load markdown skill files from the skills/ directory."""

    # Skill file mappings: domain_id -> filename
    SKILL_MAP = {
        "D1": "d1_model_integrity.md",
        "D2": "d2_orchestration.md",
        "D3": "d3_tool_security.md",
        "D4": "d4_identity.md",
        "D5": "d5_federation.md",
        "D6": "d6_observability.md",
        "D7": "d7_itot.md",
        "D8": "d8_supply_chain.md",
    }

    def __init__(self, skills_dir: Optional[Path] = None):
        """
        Initialize SkillLoader.

        Args:
            skills_dir: Directory containing skill markdown files.
                       If None, use package-relative path or default to ./skills

        """
        if skills_dir:
            self.skills_dir = Path(skills_dir)
        else:
            # Try package resources first
            try:
                import importlib.resources as resources
                # Python 3.9+ package resource API
                try:
                    # Try the new API first (3.9+)
                    files = resources.files("asopb") / "skills"
                    self.skills_dir = Path(str(files))
                except (AttributeError, TypeError):
                    # Fallback to older API
                    self.skills_dir = Path(__file__).parent.parent / "skills"
            except ImportError:
                # Fallback: relative to this module
                self.skills_dir = Path(__file__).parent.parent / "skills"

        logger.info(f"Skills directory: {self.skills_dir}")

    def load(self, domain_id: str) -> str:
        """
        Load skill markdown for a domain.

        Args:
            domain_id: Domain identifier (e.g., "D4", "D1")

        Returns:
            Markdown content as string

        Raises:
            ValueError: if domain_id is unknown
            FileNotFoundError: if skill file does not exist
        """
        domain_id_upper = domain_id.upper()

        if domain_id_upper not in self.SKILL_MAP:
            raise ValueError(
                f"Unknown domain: {domain_id}. Valid domains: {list(self.SKILL_MAP.keys())}"
            )

        filename = self.SKILL_MAP[domain_id_upper]
        skill_path = self.skills_dir / filename

        if not skill_path.exists():
            raise FileNotFoundError(
                f"Skill file not found: {skill_path}\n"
                f"Expected location: {self.skills_dir}"
            )

        logger.debug(f"Loading skill: {domain_id} from {skill_path}")

        with open(skill_path, "r") as f:
            return f.read()

    def load_all(self) -> dict[str, str]:
        """
        Load all skill markdown files.

        Returns:
            Dictionary mapping domain_id -> skill content (e.g., {"D1": "...", "D2": "...", ...})

        Raises:
            FileNotFoundError: if any skill file is missing
        """
        skills = {}

        for domain_id in sorted(self.SKILL_MAP.keys()):
            try:
                skills[domain_id] = self.load(domain_id)
            except FileNotFoundError as e:
                logger.error(f"Failed to load skill {domain_id}: {e}")
                raise

        return skills

    def available_domains(self) -> list[str]:
        """Return list of available domain IDs."""
        return sorted(self.SKILL_MAP.keys())
