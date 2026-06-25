"""GCP Cloud Logging observability backend.

Queries Cloud Logging for Vertex AI token usage metrics.
Requires: pip install google-cloud-logging
"""

from __future__ import annotations

from ..models import GenerationRecord
from .base import ObservabilityBackend


class GCPCloudTraceBackend(ObservabilityBackend):
    """GCP Cloud Logging / Vertex AI backend.

    Config requirements:
        - project: GCP project ID
        - GCP credentials via GOOGLE_APPLICATION_CREDENTIALS or ADC
    """

    @property
    def name(self) -> str:
        return "GCP Cloud Logging"

    def validate_config(self) -> None:
        if not self._config.project:
            raise ValueError("GCP project ID is required")

    def fetch_generations(self, page_limit: int = 50) -> list[GenerationRecord]:
        self.validate_config()
        try:
            from google.cloud import logging as gcp_logging
        except ImportError:
            raise ImportError("Required: pip install google-cloud-logging")

        client = gcp_logging.Client(project=self._config.project)

        log_filter = (
            'resource.type="aiplatform.googleapis.com/Endpoint" '
            'AND jsonPayload.usageMetadata IS NOT NULL'
        )
        log_name = self._config.extra.get("log_name")
        if log_name:
            log_filter += f' AND logName="{log_name}"'

        records: list[GenerationRecord] = []
        for entry in client.list_entries(filter_=log_filter, order_by="timestamp desc"):
            record = self._parse_entry(entry)
            if record:
                records.append(record)
            if len(records) >= page_limit * 100:
                break

        return records

    def _parse_entry(self, entry) -> GenerationRecord | None:
        try:
            payload = entry.payload or {}
            usage = payload.get("usageMetadata", {})
            input_tokens = int(usage.get("promptTokenCount", 0))
            output_tokens = int(usage.get("candidatesTokenCount", 0))
            return GenerationRecord(
                id=entry.insert_id or "",
                model=payload.get("model", "unknown"),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                timestamp=entry.timestamp,
            )
        except (ValueError, KeyError, AttributeError):
            return None
