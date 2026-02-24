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
)
from aws_cdk import (
    aws_apigatewayv2 as apigwv2,
)
from aws_cdk import (
    aws_apigatewayv2_integrations as apigwv2_integrations,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
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

        # Lambda integration for all routes
        lambda_integration = apigwv2_integrations.HttpLambdaIntegration(
            "OapifLambdaIntegration",
            handler=self.handler,
        )

        # --- Read routes (Phase 3: OGC API - Features Part 1 Core) ---
        read_routes: list[tuple[str, str]] = [
            ("GET", "/"),
            ("GET", "/conformance"),
            ("GET", "/api"),
            ("GET", "/collections"),
            ("GET", "/collections/{collectionId}"),
            ("GET", "/collections/{collectionId}/items"),
            ("GET", "/collections/{collectionId}/items/{featureId}"),
            ("GET", "/collections/{collectionId}/schema"),
        ]

        for method, path in read_routes:
            self.api.add_routes(
                path=path,
                methods=[apigwv2.HttpMethod(method)],
                integration=lambda_integration,
            )

        # Write routes will be added in Phase 6.

        # --- Outputs ---
        cdk.CfnOutput(self, "ApiUrl", value=self.api.url or "")
        cdk.CfnOutput(self, "LambdaFunctionName", value=self.handler.function_name)
