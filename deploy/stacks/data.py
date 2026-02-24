"""Data stack — DynamoDB tables and S3 bucket.

This stack contains all STATEFUL resources. It uses RemovalPolicy.RETAIN
so that tables and buckets survive stack deletion, protecting production
data from accidental destruction.

Termination protection is enabled for non-dev environments.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aws_cdk as cdk
from aws_cdk import (
    RemovalPolicy,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_s3 as s3,
)
from constructs import Construct

if TYPE_CHECKING:
    from deploy.config import DeploymentConfig


class DataStack(cdk.Stack):
    """DynamoDB tables and S3 bucket for feature data and QGIS projects."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeploymentConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # In dev, allow CloudFormation to delete resources on stack removal
        # for easy teardown. In staging/prod, RETAIN protects against accidents.
        is_dev = config.environment == "dev"
        removal_policy = RemovalPolicy.DESTROY if is_dev else RemovalPolicy.RETAIN

        # Enable termination protection on non-dev stacks so `cdk destroy`
        # requires an explicit override to remove stateful resources.
        if not is_dev:
            self.termination_protection = True

        billing_mode = (
            dynamodb.BillingMode.PAY_PER_REQUEST
            if config.dynamodb_billing_mode == "PAY_PER_REQUEST"
            else dynamodb.BillingMode.PROVISIONED
        )

        # --- Features Table ---
        self.features_table = dynamodb.Table(
            self,
            "FeaturesTable",
            table_name=config.features_table_name,
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=billing_mode,
            removal_policy=removal_policy,
            point_in_time_recovery=not is_dev,
        )

        # --- Change Tracking Table ---
        self.changes_table = dynamodb.Table(
            self,
            "ChangesTable",
            table_name=config.changes_table_name,
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=billing_mode,
            removal_policy=removal_policy,
            point_in_time_recovery=not is_dev,
        )

        # --- Collection Config Table ---
        self.config_table = dynamodb.Table(
            self,
            "ConfigTable",
            table_name=config.config_table_name,
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=billing_mode,
            removal_policy=removal_policy,
        )

        # --- S3 Bucket for QGIS Project Files ---
        self.project_bucket = s3.Bucket(
            self,
            "ProjectBucket",
            bucket_name=config.project_bucket_name,
            removal_policy=removal_policy,
            auto_delete_objects=is_dev,  # Only in dev: empty bucket before deletion
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=not is_dev,
        )

        # --- Outputs ---
        cdk.CfnOutput(self, "FeaturesTableName", value=self.features_table.table_name)
        cdk.CfnOutput(self, "ChangesTableName", value=self.changes_table.table_name)
        cdk.CfnOutput(self, "ConfigTableName", value=self.config_table.table_name)
        cdk.CfnOutput(self, "ProjectBucketName", value=self.project_bucket.bucket_name)
