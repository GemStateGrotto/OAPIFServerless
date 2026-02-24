"""Deployment configuration loader.

Reads deployment parameters from environment variables (OAPIF_* prefix)
and CDK context (--context key=value). Defaults are defined in the
DeploymentConfig dataclass — this is the single source of truth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeploymentConfig:
    """Deployment configuration for all OAPIFServerless stacks.

    Defaults are defined here. Override via environment variables
    (OAPIF_* prefix) or CDK context (--context key=value).
    """

    # AWS environment
    aws_region: str = "us-west-2"
    aws_account: str = ""

    # Naming
    stack_prefix: str = "oapif"
    environment: str = "dev"  # dev | staging | prod

    # DynamoDB
    dynamodb_table_prefix: str = "oapif"
    dynamodb_billing_mode: str = "PAY_PER_REQUEST"  # PAY_PER_REQUEST | PROVISIONED

    # S3
    s3_bucket_prefix: str = "oapif"

    # Cognito
    cognito_domain_prefix: str = "oapif"

    # Lambda
    lambda_memory_mb: int = 256
    lambda_timeout_seconds: int = 30
    lambda_log_level: str = "INFO"

    # API Gateway
    api_stage_name: str = "v1"

    @property
    def features_table_name(self) -> str:
        return f"{self.dynamodb_table_prefix}-{self.environment}-features"

    @property
    def changes_table_name(self) -> str:
        return f"{self.dynamodb_table_prefix}-{self.environment}-changes"

    @property
    def config_table_name(self) -> str:
        return f"{self.dynamodb_table_prefix}-{self.environment}-config"

    @property
    def project_bucket_name(self) -> str:
        return f"{self.s3_bucket_prefix}-{self.environment}-projects"


# Maps OAPIF_* env vars to DeploymentConfig field names.
_ENV_MAPPING: dict[str, str] = {
    "OAPIF_AWS_REGION": "aws_region",
    "OAPIF_AWS_ACCOUNT": "aws_account",
    "OAPIF_STACK_PREFIX": "stack_prefix",
    "OAPIF_ENVIRONMENT": "environment",
    "OAPIF_DYNAMODB_TABLE_PREFIX": "dynamodb_table_prefix",
    "OAPIF_DYNAMODB_BILLING_MODE": "dynamodb_billing_mode",
    "OAPIF_S3_BUCKET_PREFIX": "s3_bucket_prefix",
    "OAPIF_COGNITO_DOMAIN_PREFIX": "cognito_domain_prefix",
    "OAPIF_LAMBDA_MEMORY_MB": "lambda_memory_mb",
    "OAPIF_LAMBDA_TIMEOUT_SECONDS": "lambda_timeout_seconds",
    "OAPIF_LAMBDA_LOG_LEVEL": "lambda_log_level",
    "OAPIF_API_STAGE_NAME": "api_stage_name",
}

# Fields that need str→int coercion when read from env vars.
_INT_FIELDS: set[str] = {"lambda_memory_mb", "lambda_timeout_seconds"}


def load_deployment_config(app: Any = None) -> DeploymentConfig:
    """Load deployment configuration.

    Priority (highest to lowest):
    1. CDK context values (--context key=value)
    2. Environment variables (OAPIF_* prefix)
    3. Defaults in DeploymentConfig
    """
    values: dict[str, Any] = {}

    # Environment variables
    for env_var, config_key in _ENV_MAPPING.items():
        env_value = os.environ.get(env_var)
        if env_value is not None:
            values[config_key] = env_value

    # CDK context overrides (highest priority)
    if app is not None:
        for config_key in DeploymentConfig.__dataclass_fields__:
            ctx_value = app.node.try_get_context(config_key)
            if ctx_value is not None:
                values[config_key] = ctx_value

    # Coerce string values to int where needed
    for field_name in _INT_FIELDS:
        if field_name in values and isinstance(values[field_name], str):
            values[field_name] = int(values[field_name])

    return DeploymentConfig(**values)
