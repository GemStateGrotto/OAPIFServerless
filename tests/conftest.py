"""Shared pytest fixtures for OAPIFServerless tests.

Provides:
- Mocked AWS credentials (prevent accidental real AWS calls)
- DynamoDB Local client for integration tests
- Moto-based DynamoDB mock for unit tests
- Common test data factories
- FeatureDAL fixtures for both moto and DynamoDB Local
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Generator
from typing import TYPE_CHECKING

import boto3
import pytest
from moto import mock_aws

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient, DynamoDBServiceResource

    from oapif.dal.features import FeatureDAL


# ---------------------------------------------------------------------------
# Environment safety: prevent accidental real AWS calls
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _aws_credentials_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure fake AWS credentials are set for every test."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


# ---------------------------------------------------------------------------
# Lambda environment variables
# ---------------------------------------------------------------------------


@pytest.fixture()
def lambda_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Set environment variables that Lambda functions expect at runtime."""
    env = {
        "FEATURES_TABLE": "oapif-test-features",
        "CHANGES_TABLE": "oapif-test-changes",
        "CONFIG_TABLE": "oapif-test-config",
        "PROJECT_BUCKET": "oapif-test-projects",
        "ENVIRONMENT": "test",
        "LOG_LEVEL": "DEBUG",
        "AWS_REGION": "us-east-1",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


# ---------------------------------------------------------------------------
# Moto-based DynamoDB mock (unit tests — no Docker required)
# ---------------------------------------------------------------------------


@pytest.fixture()
def dynamodb_mock() -> Generator[DynamoDBServiceResource]:
    """Provide a moto-mocked DynamoDB resource for unit tests."""
    with mock_aws():
        resource: DynamoDBServiceResource = boto3.resource("dynamodb", region_name="us-east-1")
        yield resource


@pytest.fixture()
def features_table(dynamodb_mock: DynamoDBServiceResource, lambda_env: dict[str, str]) -> object:
    """Create the features table in the moto mock."""
    table = dynamodb_mock.create_table(
        TableName=lambda_env["FEATURES_TABLE"],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return table


@pytest.fixture()
def changes_table(dynamodb_mock: DynamoDBServiceResource, lambda_env: dict[str, str]) -> object:
    """Create the change tracking table in the moto mock."""
    table = dynamodb_mock.create_table(
        TableName=lambda_env["CHANGES_TABLE"],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return table


# ---------------------------------------------------------------------------
# DynamoDB Local client (integration tests — requires Docker)
# ---------------------------------------------------------------------------

DYNAMODB_LOCAL_ENDPOINT = os.environ.get("DYNAMODB_LOCAL_ENDPOINT", "http://dynamodb-local:8000")


@pytest.fixture(scope="session")
def dynamodb_local_client() -> DynamoDBClient:
    """Provide a boto3 client pointing at DynamoDB Local.

    Requires DynamoDB Local running (e.g., via docker-compose).
    Only used for integration tests.
    """
    return boto3.client(
        "dynamodb",
        endpoint_url=DYNAMODB_LOCAL_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


@pytest.fixture(scope="session")
def dynamodb_local_resource() -> DynamoDBServiceResource:
    """Provide a boto3 resource pointing at DynamoDB Local."""
    return boto3.resource(
        "dynamodb",
        endpoint_url=DYNAMODB_LOCAL_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


# ---------------------------------------------------------------------------
# FeatureDAL fixtures (unit tests — moto)
# ---------------------------------------------------------------------------


@pytest.fixture()
def dal(
    dynamodb_mock: DynamoDBServiceResource,
    features_table: object,
    changes_table: object,
    lambda_env: dict[str, str],
) -> FeatureDAL:
    """Provide a FeatureDAL backed by moto-mocked DynamoDB for unit tests."""
    from oapif.dal.features import FeatureDAL

    return FeatureDAL(
        dynamodb_resource=dynamodb_mock,
        features_table_name=lambda_env["FEATURES_TABLE"],
        changes_table_name=lambda_env["CHANGES_TABLE"],
    )


# ---------------------------------------------------------------------------
# FeatureDAL fixtures (integration tests — DynamoDB Local)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def integration_table_names() -> dict[str, str]:
    """Table names used for integration tests against DynamoDB Local."""
    return {
        "features": "oapif-integration-features",
        "changes": "oapif-integration-changes",
    }


@pytest.fixture(scope="session")
def _ensure_integration_tables(
    dynamodb_local_resource: DynamoDBServiceResource,
    integration_table_names: dict[str, str],
) -> None:
    """Create tables in DynamoDB Local (idempotent)."""
    for table_name in integration_table_names.values():
        with contextlib.suppress(dynamodb_local_resource.meta.client.exceptions.ResourceInUseException):
            dynamodb_local_resource.create_table(
                TableName=table_name,
                KeySchema=[
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )


@pytest.fixture()
def integration_dal(
    dynamodb_local_resource: DynamoDBServiceResource,
    integration_table_names: dict[str, str],
    _ensure_integration_tables: None,
) -> FeatureDAL:
    """Provide a FeatureDAL backed by DynamoDB Local for integration tests."""
    from oapif.dal.features import FeatureDAL

    return FeatureDAL(
        dynamodb_resource=dynamodb_local_resource,
        features_table_name=integration_table_names["features"],
        changes_table_name=integration_table_names["changes"],
    )


@pytest.fixture()
def unique_org() -> str:
    """Generate a unique organization name per test to avoid cross-test pollution."""
    return f"test-org-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def unique_collection() -> str:
    """Generate a unique collection ID per test."""
    return f"test-col-{uuid.uuid4().hex[:8]}"
