"""Azure Monitor observability backend.

Queries Azure Monitor / Application Insights for Azure OpenAI token usage.
Requires: pip install azure-identity azure-monitor-query
"""

from __future__ import annotations

from datetime import timedelta

from ..models import GenerationRecord
from .base import ObservabilityBackend


class AzureMonitorBackend(ObservabilityBackend):
    """Azure Monitor / Application Insights backend.

    Config requirements:
        - extra["workspace_id"]: Log Analytics workspace ID
        - Azure credentials via DefaultAzureCredential
    """

    @property
    def name(self) -> str:
        return "Azure Monitor"

    def validate_config(self) -> None:
        if not self._config.extra.get("workspace_id"):
            raise ValueError(
                "extra['workspace_id'] is required for Azure Monitor queries. "
                "Set via config or AZURE_WORKSPACE_ID environment variable."
            )

    def fetch_generations(
        self, page_limit: int = 50, timespan_days: int | None = None
    ) -> list[GenerationRecord]:
        """Fetch generations from Azure Monitor.

        Args:
            page_limit: Maximum pages to fetch (unused, kept for interface compat).
            timespan_days: Number of days to query. Defaults to 90.
                Override via config extra['timespan_days'] or pass directly.
        """
        self.validate_config()
        try:
            from azure.identity import DefaultAzureCredential
            from azure.monitor.query import LogsQueryClient
        except ImportError:
            raise ImportError(
                "Required: pip install azure-identity azure-monitor-query"
            )

        credential = DefaultAzureCredential()
        client = LogsQueryClient(credential)
        workspace_id = self._config.extra.get("workspace_id", "")

        days = timespan_days or int(self._config.extra.get("timespan_days", 90))

        query = """
        AzureDiagnostics
        | where ResourceProvider == "MICROSOFT.COGNITIVESERVICES"
        | where Category == "RequestResponse"
        | extend model = tostring(parse_json(properties_s).model)
        | extend prompt_tokens = toint(parse_json(properties_s).prompt_tokens)
        | extend completion_tokens = toint(parse_json(properties_s).completion_tokens)
        | project TimeGenerated, model, prompt_tokens, completion_tokens, CorrelationId
        | order by TimeGenerated desc
        | take 10000
        """

        response = client.query_workspace(
            workspace_id=workspace_id,
            query=query,
            timespan=timedelta(days=days),
        )

        records: list[GenerationRecord] = []
        if response.tables:
            for row in response.tables[0].rows:
                record = self._parse_row(row, response.tables[0].columns)
                if record:
                    records.append(record)
        return records

    def _parse_row(self, row, columns) -> GenerationRecord | None:
        col_map = {col.name: i for i, col in enumerate(columns)}
        try:
            input_tokens = int(row[col_map["prompt_tokens"]] or 0)
            output_tokens = int(row[col_map["completion_tokens"]] or 0)
            return GenerationRecord(
                id=str(row[col_map.get("CorrelationId", -1)] or ""),
                model=str(row[col_map["model"]] or "unknown"),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                timestamp=row[col_map["TimeGenerated"]],
            )
        except (ValueError, KeyError, IndexError):
            return None
