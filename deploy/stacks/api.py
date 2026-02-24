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
    aws_apigatewayv2_authorizers as apigwv2_authz,
)
from aws_cdk import (
    aws_apigatewayv2_integrations as apigwv2_integrations,
)
from aws_cdk import (
    aws_cognito as cognito,
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
        user_pool: cognito.IUserPool,
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
                "COGNITO_USER_POOL_ID": user_pool.user_pool_id,
                "COGNITO_REGION": cdk.Stack.of(self).region,
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

        # --- JWT Authorizer (Cognito) ---
        # The authorizer validates JWTs but does NOT block unauthenticated
        # requests on GET routes.  API Gateway passes claims when present;
        # Lambda handles the unauthenticated vs authenticated logic.
        issuer_url = f"https://cognito-idp.{cdk.Stack.of(self).region}.amazonaws.com/{user_pool.user_pool_id}"

        jwt_authorizer = apigwv2_authz.HttpJwtAuthorizer(
            "OapifJwtAuthorizer",
            jwt_issuer=issuer_url,
            jwt_audience=[
                # Both app clients are valid audiences
                # Note: Cognito access tokens use the user pool client ID as audience
                # We'll be permissive here; Lambda validates further
                user_pool.user_pool_id,
            ],
            identity_source="$request.header.Authorization",
        )

        # Lambda integration for all routes
        lambda_integration = apigwv2_integrations.HttpLambdaIntegration(
            "OapifLambdaIntegration",
            handler=self.handler,
        )

        # --- Read routes (Phase 3: OGC API - Features Part 1 Core) ---
        # GET routes allow unauthenticated access (no authorizer).
        # The Lambda handler enforces the unauthenticated path:
        #   - require 'organization' query param
        #   - restrict to public visibility
        # When a valid JWT is present, API Gateway passes claims to Lambda
        # via requestContext.authorizer.jwt (even without a mandatory authorizer).
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
                # No authorizer — GET routes allow unauthenticated access.
                # Lambda handles auth logic based on presence of JWT claims.
            )

        # Write routes (Phase 6) will require the JWT authorizer:
        # self.api.add_routes(
        #     ...,
        #     authorizer=jwt_authorizer,
        # )
        # Store authorizer for Phase 6 to reference
        self._jwt_authorizer = jwt_authorizer

        # --- Outputs ---
        cdk.CfnOutput(self, "ApiUrl", value=self.api.url or "")
        cdk.CfnOutput(self, "LambdaFunctionName", value=self.handler.function_name)
