"""Acceptance test fixtures — live endpoint authentication and HTTP clients.

Derives the API base URL and Cognito User Pool ID from CloudFormation
stack outputs, authenticates test users via ``admin-initiate-auth``
(ADMIN_USER_PASSWORD_AUTH), and provides pre-authenticated ``httpx.Client``
fixtures for every persona.

Every feature created during a test run is tagged with a unique run ID
in its ``properties``.  A session-scoped finalizer deletes all features
matching that tag to prevent cross-run interference.

Environment variables:
    OAPIF_ENVIRONMENT  — deployment stage (default: ``dev``)
    OAPIF_STACK_PREFIX — CloudFormation stack name prefix (default: ``oapif``)
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from typing import Any

import boto3
import boto3.session
import httpx
import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_PASSWORD = "Accept@nceTest2026!"
COLLECTION_ID = "acceptance-test"

# ---------------------------------------------------------------------------
# Helpers — AWS session & stack output resolution
# ---------------------------------------------------------------------------


def _aws_region() -> str:
    """Resolve the AWS region from environment variables."""
    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION")
    if not region:
        msg = "Set AWS_DEFAULT_REGION or AWS_REGION"
        raise RuntimeError(msg)
    return region


def _boto3_session() -> boto3.session.Session:
    """Create a boto3 session with the correct region."""
    return boto3.session.Session(region_name=_aws_region())


def _get_stack_output(stack_name: str, output_key: str) -> str:
    """Read a single CloudFormation stack output value."""
    cfn = _boto3_session().client("cloudformation")
    resp = cfn.describe_stacks(StackName=stack_name)
    for output in resp["Stacks"][0].get("Outputs", []):
        if output["OutputKey"] == output_key:
            result: str = output["OutputValue"]
            return result
    msg = f"Output '{output_key}' not found in stack '{stack_name}'"
    raise KeyError(msg)


# ---------------------------------------------------------------------------
# Session-scoped: environment resolution
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def environment() -> str:
    """Deployment environment (dev, staging, prod)."""
    return os.environ.get("OAPIF_ENVIRONMENT", "dev")


@pytest.fixture(scope="session")
def stack_prefix() -> str:
    """CloudFormation stack name prefix."""
    return os.environ.get("OAPIF_STACK_PREFIX", "oapif")


@pytest.fixture(scope="session")
def base_url(stack_prefix: str, environment: str) -> str:
    """Derive the public base URL from the API stack outputs.

    Uses the default API Gateway URL.  If we later add a real custom
    domain output (not just the CNAME target) we can prefer that.
    """
    api_stack = f"{stack_prefix}-{environment}-api"
    url = _get_stack_output(api_stack, "ApiUrl")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def user_pool_id(stack_prefix: str, environment: str) -> str:
    """Cognito User Pool ID from the auth stack."""
    auth_stack = f"{stack_prefix}-{environment}-auth"
    return _get_stack_output(auth_stack, "UserPoolId")


@pytest.fixture(scope="session")
def cognito_client_id(stack_prefix: str, environment: str) -> str:
    """Public Cognito app client ID used for auth flows."""
    auth_stack = f"{stack_prefix}-{environment}-auth"
    return _get_stack_output(auth_stack, "AppClientId")


# ---------------------------------------------------------------------------
# Session-scoped: unique test run ID
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_run_id() -> str:
    """Unique tag for all features created during this test run."""
    return f"run-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Authentication helper
# ---------------------------------------------------------------------------


def _authenticate(
    user_pool_id: str,
    client_id: str,
    username: str,
) -> str:
    """Authenticate a test user and return the ID token (JWT).

    Uses ``ADMIN_USER_PASSWORD_AUTH`` — no SRP challenge flow required.
    """
    cognito = _boto3_session().client("cognito-idp")
    resp = cognito.admin_initiate_auth(
        UserPoolId=user_pool_id,
        ClientId=client_id,
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": username,
            "PASSWORD": TEST_PASSWORD,
        },
    )
    result: str = resp["AuthenticationResult"]["IdToken"]
    return result


# ---------------------------------------------------------------------------
# Authenticated httpx clients (session-scoped for speed)
# ---------------------------------------------------------------------------


def _make_client(base_url: str, token: str | None = None) -> httpx.Client:
    """Build an ``httpx.Client`` with optional Bearer auth."""
    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=base_url, headers=headers, timeout=30.0)


@pytest.fixture(scope="session")
def editor_token(user_pool_id: str, cognito_client_id: str) -> str:
    """JWT for test-editor."""
    return _authenticate(user_pool_id, cognito_client_id, "test-editor@oapif.test")


@pytest.fixture(scope="session")
def admin_token(user_pool_id: str, cognito_client_id: str) -> str:
    """JWT for test-admin."""
    return _authenticate(user_pool_id, cognito_client_id, "test-admin@oapif.test")


@pytest.fixture(scope="session")
def viewer_token(user_pool_id: str, cognito_client_id: str) -> str:
    """JWT for test-viewer."""
    return _authenticate(user_pool_id, cognito_client_id, "test-viewer@oapif.test")


@pytest.fixture(scope="session")
def other_org_token(user_pool_id: str, cognito_client_id: str) -> str:
    """JWT for test-other-org."""
    return _authenticate(user_pool_id, cognito_client_id, "test-other-org@oapif.test")


@pytest.fixture(scope="session")
def editor_client(base_url: str, editor_token: str) -> Generator[httpx.Client]:
    """Authenticated httpx client for test-editor (editor role, TestOrgA, members)."""
    client = _make_client(base_url, editor_token)
    yield client
    client.close()


@pytest.fixture(scope="session")
def admin_client(base_url: str, admin_token: str) -> Generator[httpx.Client]:
    """Authenticated httpx client for test-admin (admin role, TestOrgA, members+restricted)."""
    client = _make_client(base_url, admin_token)
    yield client
    client.close()


@pytest.fixture(scope="session")
def viewer_client(base_url: str, viewer_token: str) -> Generator[httpx.Client]:
    """Authenticated httpx client for test-viewer (viewer role, TestOrgA, no visibility groups)."""
    client = _make_client(base_url, viewer_token)
    yield client
    client.close()


@pytest.fixture(scope="session")
def other_org_client(base_url: str, other_org_token: str) -> Generator[httpx.Client]:
    """Authenticated httpx client for test-other-org (editor, TestOrgB)."""
    client = _make_client(base_url, other_org_token)
    yield client
    client.close()


@pytest.fixture(scope="session")
def anon_client(base_url: str) -> Generator[httpx.Client]:
    """Unauthenticated httpx client."""
    client = _make_client(base_url)
    yield client
    client.close()


# ---------------------------------------------------------------------------
# Feature factory & cleanup
# ---------------------------------------------------------------------------


def make_test_feature(
    test_run_id: str,
    *,
    name: str = "Test Feature",
    visibility: str | None = None,
    lon: float = -114.75,
    lat: float = 44.05,
    depth_m: float | None = 120.0,
    status: str = "active",
    extra_props: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a GeoJSON Feature body tagged with the test-run ID."""
    props: dict[str, Any] = {
        "name": name,
        "status": status,
        "test_run_id": test_run_id,
    }
    if depth_m is not None:
        props["depth_m"] = depth_m
    if visibility is not None:
        props["visibility"] = visibility
    if extra_props:
        props.update(extra_props)

    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
        "properties": props,
    }


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_features(
    admin_client: httpx.Client,
    test_run_id: str,
) -> Generator[None]:
    """Delete all features tagged with this test run after the session."""
    yield

    # Paginate through all features looking for our test_run_id tag
    url = f"/collections/{COLLECTION_ID}/items?limit=100"
    deleted = 0
    while url:
        resp = admin_client.get(url)
        if resp.status_code != 200:
            break
        data = resp.json()
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            if props.get("test_run_id") == test_run_id:
                fid = feature["id"]
                # Need to get the ETag first
                get_resp = admin_client.get(f"/collections/{COLLECTION_ID}/items/{fid}")
                if get_resp.status_code == 200:
                    etag = get_resp.headers.get("etag", "")
                    admin_client.delete(
                        f"/collections/{COLLECTION_ID}/items/{fid}",
                        headers={"If-Match": etag},
                    )
                    deleted += 1

        # Follow next link
        next_url = None
        for link in data.get("links", []):
            if link.get("rel") == "next":
                next_url = link["href"]
                break
        url = next_url  # type: ignore[assignment]

    if deleted:
        print(f"\n[acceptance cleanup] Deleted {deleted} test features (run={test_run_id})")  # noqa: T201


# ---------------------------------------------------------------------------
# Helper: create a feature and return (id, etag) tuple
# ---------------------------------------------------------------------------


def create_feature(
    client: httpx.Client,
    test_run_id: str,
    **kwargs: Any,
) -> tuple[str, str]:
    """Create a feature via POST and return ``(feature_id, etag)``.

    The feature is tagged with the test-run ID for cleanup.
    """
    body = make_test_feature(test_run_id, **kwargs)
    resp = client.post(
        f"/collections/{COLLECTION_ID}/items",
        json=body,
    )
    assert resp.status_code == 201, f"Feature creation failed: {resp.status_code} {resp.text}"
    data = resp.json()
    feature_id: str = data["id"]
    etag: str = resp.headers["etag"]
    return feature_id, etag
