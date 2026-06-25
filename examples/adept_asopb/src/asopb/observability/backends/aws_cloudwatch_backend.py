"""AWS CloudWatch / Bedrock observability backend.

Queries CloudWatch Logs Insights for Bedrock model invocation logs.
Requires: pip install boto3
"""

from __future__ import annotations

import time
from datetime import datetime

from ..models import GenerationRecord
from .base import ObservabilityBackend


class AWSCloudWatchBackend(ObservabilityBackend):
    """AWS CloudWatch backend for Bedrock/SageMaker token utilization.

    Config requirements:
        - region: AWS region (e.g., us-west-2)
        - extra["log_group"]: CloudWatch log group name
        - AWS credentials via environment or IAM role
    """

    @property
    def name(self) -> str:
        return "AWS CloudWatch"

    def validate_config(self) -> None:
        if not self._config.region:
            raise ValueError("AWS region is required")
        if not self._config.extra.get("log_group"):
            raise ValueError("extra['log_group'] is required for CloudWatch Logs Insights")

    def fetch_generations(self, page_limit: int = 50) -> list[GenerationRecord]:
        self.validate_config()
        try:
            import boto3
        except ImportError:
            raise ImportError("boto3 required: pip install boto3")

        client = boto3.client("logs", region_name=self._config.region)
        log_group = self._config.extra["log_group"]

        query = """
        fields @timestamp, @message
        | filter @message like /inputTokenCount/
        | parse @message '"modelId":"*"' as model
        | parse @message '"inputTokenCount":*,' as input_tokens
        | parse @message '"outputTokenCount":*,' as output_tokens
        | sort @timestamp desc
        | limit 10000
        """

        response = client.start_query(
            logGroupName=log_group,
            startTime=0,
            endTime=int(time.time()),
            queryString=query,
            limit=10000,
        )
        query_id = response["queryId"]
        records: list[GenerationRecord] = []

        for _ in range(60):
            result = client.get_query_results(queryId=query_id)
            if result["status"] == "Complete":
                for row in result.get("results", []):
                    record = self._parse_row(row)
                    if record:
                        records.append(record)
                break
            time.sleep(1)

        return records

    def _parse_row(self, row: list[dict]) -> GenerationRecord | None:
        fields = {item["field"]: item["value"] for item in row}
        try:
            input_tokens = int(float(fields.get("input_tokens", "0")))
            output_tokens = int(float(fields.get("output_tokens", "0")))
            timestamp = None
            ts_str = fields.get("@timestamp", "")
            if ts_str:
                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return GenerationRecord(
                id=fields.get("@ptr", ""),
                model=fields.get("model", "unknown"),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                timestamp=timestamp,
            )
        except (ValueError, KeyError):
            return None
