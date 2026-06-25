"""Transport abstraction — re-exports from shared module for backward compatibility."""

from ..transport import ClusterInfo, JobResult, SlurmTransport

__all__ = ["ClusterInfo", "JobResult", "SlurmTransport"]
