"""Shared pytest fixtures for OAPIFServerless tests.

Provides:
- Mocked AWS credentials (prevent accidental real AWS calls)
- DynamoDB Local client for integration tests
- Moto-based DynamoDB mock for unit tests
- Common test data factories
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Generator

import boto3
import pytest
from moto import mock_aws

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient, DynamoDBServiceResource


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
def dynamodb_mock() -> Generator[DynamoDBServiceResource, None, None]:
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
