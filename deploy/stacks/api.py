"""API stack — Lambda functions and API Gateway.

This stack contains all STATELESS resources. It can be freely
destroyed and redeployed without affecting data in the DataStack.

Lambda code changes deploy in ~15-30 seconds via incremental updates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    aws_apigatewayv2 as apigwv2,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_s3 as s3,
)
from constructs import Construct

if TYPE_CHECKING:
    from deploy.config import DeploymentConfig


class ApiStack(cdk.Stack):
    """Lambda functions and API Gateway HTTP API for OAPIF endpoints."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeploymentConfig,
        features_table: dynamodb.ITable,
        changes_table: dynamodb.ITable,
        config_table: dynamodb.ITable,
        project_bucket: s3.IBucket,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Lambda Function ---
        self.handler = lambda_.Function(
            self,
            "OapifHandler",
            runtime=lambda_.Runtime.PYTHON_3_13,  # Closest available; upgrade to 3.14 when CDK adds it
            handler="oapif.handlers.main.handler",
            code=lambda_.Code.from_asset("src"),
            memory_size=config.lambda_memory_mb,
            timeout=Duration.seconds(config.lambda_timeout_seconds),
            environment={
                "FEATURES_TABLE": features_table.table_name,
                "CHANGES_TABLE": changes_table.table_name,
                "CONFIG_TABLE": config_table.table_name,
                "PROJECT_BUCKET": project_bucket.bucket_name,
                "ENVIRONMENT": config.environment,
                "LOG_LEVEL": config.lambda_log_level,
            },
        )

        # Grant least-privilege access to data resources
        features_table.grant_read_write_data(self.handler)
        changes_table.grant_read_write_data(self.handler)
        config_table.grant_read_data(self.handler)
        project_bucket.grant_read(self.handler)

        # --- API Gateway HTTP API ---
        self.api = apigwv2.HttpApi(
            self,
            "OapifApi",
            api_name=f"{config.stack_prefix}-{config.environment}",
            description="OGC API - Features endpoint",
        )

        # Routes will be added in Phase 3 (read endpoints) and Phase 6 (write endpoints).
        # For now the API and Lambda exist but have no routes wired up.

        # --- Outputs ---
        cdk.CfnOutput(self, "ApiUrl", value=self.api.url or "")
        cdk.CfnOutput(self, "LambdaFunctionName", value=self.handler.function_name)
