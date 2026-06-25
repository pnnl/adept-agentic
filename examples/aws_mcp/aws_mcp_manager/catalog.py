"""Catalog loader — reads static catalog.json and derives tool prefixes."""

import json
import re
from pathlib import Path
from typing import Optional

from loguru import logger

from .models import CatalogEntry


def derive_tool_prefix(server_name: str) -> str:
    """Derive a tool namespace prefix from an AWS MCP server name.

    Rules:
      1. Strip '-mcp-server' suffix
      2. Strip 'aws-' or 'amazon-' prefix
      3. Replace '-' with '_'

    Examples:
      s3-tables-mcp-server       → s3_tables
      amazon-neptune-mcp-server  → neptune
      aws-documentation-mcp-server → documentation
      dynamodb-mcp-server        → dynamodb
    """
    name = server_name
    name = re.sub(r"-mcp-server$", "", name)
    name = re.sub(r"^aws-", "", name)
    name = re.sub(r"^amazon-", "", name)
    name = name.replace("-", "_")
    return name


class Catalog:
    """Static catalog of available AWS MCP servers."""

    def __init__(self) -> None:
        self._entries: dict[str, CatalogEntry] = {}

    def load_from_file(self, path: Optional[Path] = None) -> None:
        """Load catalog from a JSON file.

        Args:
            path: Path to catalog.json. Defaults to the bundled file
                  next to this module.
        """
        if path is None:
            path = Path(__file__).parent / "catalog.json"

        if not path.exists():
            logger.warning("Catalog file not found: {}", path)
            return

        with open(path) as f:
            data = json.load(f)

        for item in data.get("servers", []):
            entry = CatalogEntry(**item)
            self._entries[entry.name] = entry

        logger.info("Loaded {} servers from catalog", len(self._entries))

    def get(self, name: str) -> Optional[CatalogEntry]:
        return self._entries.get(name)

    def list_all(self) -> list[CatalogEntry]:
        return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: str) -> bool:
        return name in self._entries
