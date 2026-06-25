"""Langfuse observability backend implementation."""

from __future__ import annotations

import base64
import json
import urllib.request
from datetime import datetime
from typing import Any

from ..models import GenerationRecord
from .base import BackendConfig, ObservabilityBackend


class LangfuseBackend(ObservabilityBackend):
    """Langfuse v2/v3 API backend for token utilization data.

    Requires:
        - endpoint: Langfuse API base URL (e.g., http://localhost:3001)
        - public_key: Langfuse public key (pk-lf-...)
        - secret_key: Langfuse secret key (sk-lf-...)
    """

    @property
    def name(self) -> str:
        return "Langfuse"

    def validate_config(self) -> None:
        if not self._config.endpoint:
            raise ValueError("Langfuse endpoint required (e.g., http://localhost:3001)")
        if not self._config.public_key:
            raise ValueError("Langfuse public_key required (pk-lf-...)")
        if not self._config.secret_key:
            raise ValueError("Langfuse secret_key required (sk-lf-...)")

    def _auth_header(self) -> str:
        creds = f"{self._config.public_key}:{self._config.secret_key}"
        return f"Basic {base64.b64encode(creds.encode()).decode()}"

    def _fetch_page(self, page: int, limit: int = 100) -> dict[str, Any]:
        url = (
            f"{self._config.endpoint}/api/public/observations"
            f"?type=GENERATION&page={page}&limit={limit}"
        )
        req = urllib.request.Request(
            url, headers={"Authorization": self._auth_header()}
        )
        resp = urllib.request.urlopen(req, timeout=self._config.timeout)
        return json.loads(resp.read())

    def fetch_generations(self, page_limit: int = 50) -> list[GenerationRecord]:
        self.validate_config()
        records: list[GenerationRecord] = []
        page = 1

        while page <= page_limit:
            data = self._fetch_page(page)
            observations = data.get("data", [])
            if not observations:
                break
            for obs in observations:
                record = self._parse_observation(obs)
                if record:
                    records.append(record)
            page += 1

        return records

    def _parse_observation(self, obs: dict[str, Any]) -> GenerationRecord | None:
        usage = obs.get("usage") or {}
        input_tokens = usage.get("input", 0) or 0
        output_tokens = usage.get("output", 0) or 0
        total_tokens = usage.get("total", 0) or (input_tokens + output_tokens)

        timestamp = None
        start_time = obs.get("startTime", "")
        if start_time:
            try:
                ts = start_time.replace("Z", "+00:00")
                timestamp = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass

        return GenerationRecord(
            id=obs.get("id", ""),
            model=obs.get("model", "unknown"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            timestamp=timestamp,
            name=obs.get("name", ""),
            trace_id=obs.get("traceId", ""),
            metadata=obs.get("metadata") or {},
        )

    def test_connection(self) -> bool:
        try:
            self.validate_config()
            self._fetch_page(1, limit=1)
            return True
        except Exception:
            return False
