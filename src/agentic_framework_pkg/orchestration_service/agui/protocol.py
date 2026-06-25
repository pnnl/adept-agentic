"""AG-UI Protocol event models.

Re-exports from the official ``ag-ui-protocol`` package and adds a thin
``to_jsonl()`` helper.  The official types use camelCase aliases and
SCREAMING_SNAKE_CASE event type values (e.g., ``RUN_STARTED``).
"""

import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

# Re-export official AG-UI protocol types for convenience
from ag_ui.core import (  # noqa: F401
    CustomEvent,
    EventType,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
    StateSnapshotEvent,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def to_jsonl(event) -> str:
    """Serialize any AG-UI event to a JSONL line (JSON + newline).

    Works with both official ``ag_ui.core`` event classes and our custom
    extension events below.
    """
    return event.model_dump_json(by_alias=True, exclude_none=True) + "\n"


# --- Extension events not in the official spec ---

class MetaEvent(BaseModel):
    """ADEPT-specific meta event for fork metadata and other internal data."""
    model_config = ConfigDict(populate_by_name=True)

    type: str = "META_EVENT"
    timestamp: int = Field(default_factory=_now_ms)
    key: str
    value: Any

    def to_jsonl(self) -> str:
        return self.model_dump_json(by_alias=True, exclude_none=True) + "\n"
