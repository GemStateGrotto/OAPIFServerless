"""Runtime configuration for Lambda functions.

Reads configuration from environment variables set by CDK during deployment.
This module is imported at Lambda cold start.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeConfig:
    """Runtime configuration populated from Lambda environment variables."""

    features_table: str
    changes_table: str
    config_table: str
    project_bucket: str
    aws_region: str
    environment: str
    log_level: str

    @classmethod
    def from_env(cls) -> RuntimeConfig:
        """Load runtime configuration from environment variables."""
        return cls(
            features_table=os.environ["FEATURES_TABLE"],
            changes_table=os.environ["CHANGES_TABLE"],
            config_table=os.environ["CONFIG_TABLE"],
            project_bucket=os.environ.get("PROJECT_BUCKET", ""),
            aws_region=os.environ.get("AWS_REGION", "us-west-2"),
            environment=os.environ.get("ENVIRONMENT", "dev"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
