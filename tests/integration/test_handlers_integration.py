"""Integration tests for OAPIF read endpoints against DynamoDB Local.

These tests exercise the full handler stack (router → routes → DAL → DynamoDB)
using DynamoDB Local. They verify end-to-end behavior including:

- Landing page and conformance responses
- Collection listing and retrieval
- Feature querying with pagination, bbox, property filters
- Single feature retrieval with ETag
- Schema endpoint
- Organization isolation
- Content types and link structure
"""

from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import jsonschema
import pytest

from oapif.dal.collections import CollectionDAL
from oapif.dal.features import FeatureDAL
from oapif.handlers.main import handler
from oapif.handlers.routes import (
    reset_singletons,
    set_collection_dal,
    set_feature_dal,
)
from oapif.models.collection import (
    CollectionConfig,
    CollectionExtent,
    OrgAccessConfig,
    PropertySchema,
    SpatialExtent,
    TemporalExtent,
)
from tests.schemas import (
    GEOJSON_FEATURE_SCHEMA,
    OGC_COLLECTIONS_SCHEMA,
    OGC_CONFORMANCE_SCHEMA,
    OGC_ITEMS_RESPONSE_SCHEMA,
    OGC_LANDING_PAGE_SCHEMA,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    method: str = "GET",
    path: str = "/",
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "rawPath": path,
        "requestContext": {
            "domainName": "api.test.com",
            "stage": "$default",
            "http": {"method": method, "path": path},
        },
        "queryStringParameters": query,
    }


def _validate(instance: Any, schema: dict[str, Any]) -> None:
    jsonschema.validate(instance, schema)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def integration_handler_config_table_name() -> str:
    return "oapif-integration-handler-config"


@pytest.fixture(scope="session")
def integration_handler_features_table_name() -> str:
    return "oapif-integration-handler-features"


@pytest.fixture(scope="session")
def integration_handler_changes_table_name() -> str:
    return "oapif-integration-handler-changes"


@pytest.fixture(scope="session")
def _ensure_handler_tables(
    dynamodb_local_resource: Any,
    integration_handler_config_table_name: str,
    integration_handler_features_table_name: str,
    integration_handler_changes_table_name: str,
) -> None:
    """Create all tables needed for handler integration tests."""
    for table_name in [
        integration_handler_config_table_name,
        integration_handler_features_table_name,
        integration_handler_changes_table_name,
    ]:
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
def handler_collection_dal(
    dynamodb_local_resource: Any,
    integration_handler_config_table_name: str,
    _ensure_handler_tables: None,
) -> CollectionDAL:
    return CollectionDAL(
        dynamodb_resource=dynamodb_local_resource,
        config_table_name=integration_handler_config_table_name,
    )


@pytest.fixture()
def handler_feature_dal(
    dynamodb_local_resource: Any,
    integration_handler_features_table_name: str,
    integration_handler_changes_table_name: str,
    _ensure_handler_tables: None,
) -> FeatureDAL:
    return FeatureDAL(
        dynamodb_resource=dynamodb_local_resource,
        features_table_name=integration_handler_features_table_name,
        changes_table_name=integration_handler_changes_table_name,
    )


@pytest.fixture(autouse=True)
def _reset_and_inject(
    handler_collection_dal: CollectionDAL,
    handler_feature_dal: FeatureDAL,
) -> None:
    reset_singletons()
    set_collection_dal(handler_collection_dal)
    set_feature_dal(handler_feature_dal)


@pytest.fixture()
def org_id() -> str:
    return f"test-org-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def collection_id() -> str:
    return f"test-col-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def seeded_collection(
    handler_collection_dal: CollectionDAL,
    collection_id: str,
    org_id: str,
) -> CollectionConfig:
    config = CollectionConfig(
        collection_id=collection_id,
        title="Test Collection",
        description="Integration test feature data",
        extent=CollectionExtent(
            spatial=SpatialExtent(bbox=[[-117.0, 42.0, -111.0, 49.0]]),
            temporal=TemporalExtent(interval=[["2024-01-01T00:00:00Z", None]]),
        ),
        properties_schema={
            "name": PropertySchema(type="string", description="Feature name"),
            "depth_m": PropertySchema(type="number", description="Depth"),
        },
        required_properties=["name"],
        visibility_values=["public", "members", "restricted"],
        geometry_type="Point",
        organizations={
            org_id: OrgAccessConfig(
                cognito_group=f"org:{org_id}",
                access_groups={},
            ),
        },
    )
    handler_collection_dal.put_collection(config)
    return config


@pytest.fixture()
def seeded_features(
    handler_feature_dal: FeatureDAL,
    seeded_collection: CollectionConfig,
    org_id: str,
) -> list[str]:
    """Create 5 features and return their IDs."""
    ids = []
    for i in range(5):
        feature = handler_feature_dal.create_feature(
            collection_id=seeded_collection.collection_id,
            feature_data={
                "geometry": {"type": "Point", "coordinates": [-114.0 + i * 0.5, 43.0 + i * 0.1]},
                "properties": {"name": f"Feature {i}", "depth_m": 10.0 + i * 5},
            },
            organization=org_id,
            visibility="public",
        )
        ids.append(feature.id)
    return ids


# ===================================================================
# Landing page and conformance
# ===================================================================


class TestLandingPageIntegration:
    def test_landing_page(self) -> None:
        resp = handler(_make_event(path="/"), None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        _validate(body, OGC_LANDING_PAGE_SCHEMA)

    def test_conformance(self) -> None:
        resp = handler(_make_event(path="/conformance"), None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        _validate(body, OGC_CONFORMANCE_SCHEMA)


# ===================================================================
# Collections
# ===================================================================


class TestCollectionsIntegration:
    def test_list_collections_includes_seeded(self, seeded_collection: CollectionConfig) -> None:
        resp = handler(_make_event(path="/collections"), None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        _validate(body, OGC_COLLECTIONS_SCHEMA)
        col_ids = [c["id"] for c in body["collections"]]
        assert seeded_collection.collection_id in col_ids

    def test_get_single_collection(self, seeded_collection: CollectionConfig) -> None:
        resp = handler(
            _make_event(path=f"/collections/{seeded_collection.collection_id}"),
            None,
        )
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["id"] == seeded_collection.collection_id
        assert body["title"] == "Test Collection"

    def test_get_nonexistent_collection(self) -> None:
        resp = handler(_make_event(path="/collections/does-not-exist"), None)
        assert resp["statusCode"] == 404


# ===================================================================
# Features itemsT
# ===================================================================


class TestItemsIntegration:
    def test_items_empty_collection(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        resp = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/items",
                query={"organization": org_id},
            ),
            None,
        )
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        _validate(body, OGC_ITEMS_RESPONSE_SCHEMA)
        assert body["numberReturned"] == 0

    def test_items_with_features(
        self,
        seeded_collection: CollectionConfig,
        seeded_features: list[str],
        org_id: str,
    ) -> None:
        resp = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/items",
                query={"organization": org_id},
            ),
            None,
        )
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        _validate(body, OGC_ITEMS_RESPONSE_SCHEMA)
        assert body["numberReturned"] == 5

    def test_items_pagination(
        self,
        seeded_collection: CollectionConfig,
        seeded_features: list[str],
        org_id: str,
    ) -> None:
        # First page
        resp1 = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/items",
                query={"organization": org_id, "limit": "3"},
            ),
            None,
        )
        body1 = json.loads(resp1["body"])
        assert body1["numberReturned"] == 3

        # Extract cursor
        next_links = [link for link in body1["links"] if link["rel"] == "next"]
        assert len(next_links) == 1
        cursor = parse_qs(urlparse(next_links[0]["href"]).query)["cursor"][0]

        # Second page
        resp2 = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/items",
                query={"organization": org_id, "limit": "3", "cursor": cursor},
            ),
            None,
        )
        body2 = json.loads(resp2["body"])
        assert body2["numberReturned"] == 2  # 5 total - 3 = 2

    def test_items_org_isolation(
        self,
        seeded_collection: CollectionConfig,
        seeded_features: list[str],
    ) -> None:
        resp = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/items",
                query={"organization": "completely-different-org"},
            ),
            None,
        )
        body = json.loads(resp["body"])
        assert body["numberReturned"] == 0

    def test_items_bbox_filter(
        self,
        seeded_collection: CollectionConfig,
        seeded_features: list[str],
        org_id: str,
    ) -> None:
        # Features are at -114, -113.5, -113, -112.5, -112
        # Filter to just the first two
        resp = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/items",
                query={
                    "organization": org_id,
                    "bbox": "-114.1,42.5,-113.4,43.5",
                },
            ),
            None,
        )
        body = json.loads(resp["body"])
        assert body["numberReturned"] == 2

    def test_items_property_filter(
        self,
        seeded_collection: CollectionConfig,
        seeded_features: list[str],
        org_id: str,
    ) -> None:
        resp = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/items",
                query={"organization": org_id, "name": "Feature 2"},
            ),
            None,
        )
        body = json.loads(resp["body"])
        assert body["numberReturned"] == 1
        assert body["features"][0]["properties"]["name"] == "Feature 2"

    def test_items_missing_org_returns_400(
        self,
        handler_collection_dal: CollectionDAL,
    ) -> None:
        """Multi-org collection requires organization query parameter."""
        config = CollectionConfig(
            collection_id="multi-org-int",
            title="Multi-org",
            organizations={
                "OrgA": OrgAccessConfig(cognito_group="org:OrgA"),
                "OrgB": OrgAccessConfig(cognito_group="org:OrgB"),
            },
        )
        handler_collection_dal.put_collection(config)
        resp = handler(
            _make_event(
                path="/collections/multi-org-int/items",
            ),
            None,
        )
        assert resp["statusCode"] == 400


# ===================================================================
# Single feature
# ===================================================================


class TestSingleFeatureIntegration:
    def test_get_feature(
        self,
        seeded_collection: CollectionConfig,
        seeded_features: list[str],
        org_id: str,
    ) -> None:
        fid = seeded_features[0]
        resp = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
                query={"organization": org_id},
            ),
            None,
        )
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        _validate(body, GEOJSON_FEATURE_SCHEMA)
        assert body["id"] == fid
        assert "ETag" in resp["headers"]

    def test_get_feature_not_found(
        self,
        seeded_collection: CollectionConfig,
        org_id: str,
    ) -> None:
        resp = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/items/nonexistent-id",
                query={"organization": org_id},
            ),
            None,
        )
        assert resp["statusCode"] == 404

    def test_get_feature_wrong_org(
        self,
        seeded_collection: CollectionConfig,
        seeded_features: list[str],
    ) -> None:
        fid = seeded_features[0]
        resp = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
                query={"organization": "wrong-org"},
            ),
            None,
        )
        assert resp["statusCode"] == 404

    def test_feature_has_links(
        self,
        seeded_collection: CollectionConfig,
        seeded_features: list[str],
        org_id: str,
    ) -> None:
        fid = seeded_features[0]
        resp = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
                query={"organization": org_id},
            ),
            None,
        )
        body = json.loads(resp["body"])
        rels = {link["rel"] for link in body["links"]}
        assert "self" in rels
        assert "collection" in rels


# ===================================================================
# Schema
# ===================================================================


class TestSchemaIntegration:
    def test_schema_returnable(self, seeded_collection: CollectionConfig) -> None:
        resp = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/schema",
            ),
            None,
        )
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        jsonschema.Draft202012Validator.check_schema(body)
        assert resp["headers"]["Content-Type"] == "application/schema+json"

    def test_schema_receivable(self, seeded_collection: CollectionConfig) -> None:
        resp = handler(
            _make_event(
                path=f"/collections/{seeded_collection.collection_id}/schema",
                query={"type": "receivable"},
            ),
            None,
        )
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        jsonschema.Draft202012Validator.check_schema(body)
        assert "id" not in body["properties"]

    def test_schema_nonexistent_collection(self) -> None:
        resp = handler(
            _make_event(path="/collections/nonexistent/schema"),
            None,
        )
        assert resp["statusCode"] == 404


# ===================================================================
# OpenAPI
# ===================================================================


class TestOpenAPIIntegration:
    def test_api_with_collections(self, seeded_collection: CollectionConfig) -> None:
        resp = handler(_make_event(path="/api"), None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["openapi"] == "3.0.3"
        assert f"/collections/{seeded_collection.collection_id}" in body["paths"]
