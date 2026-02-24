"""Unit tests for Lambda request handler and read endpoints.

Tests cover:
- Routing (main handler dispatching)
- Landing page (GET /)
- Conformance (GET /conformance)
- Collections list (GET /collections)
- Single collection (GET /collections/{collectionId})
- Feature items (GET /collections/{collectionId}/items)
- Single feature (GET /collections/{collectionId}/items/{featureId})
- Schema endpoint (GET /collections/{collectionId}/schema)
- OpenAPI definition (GET /api)
- Content negotiation and Link headers
- Error handling (404, 400)
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import pytest

from oapif.handlers.main import handler
from oapif.handlers.routes import (
    reset_singletons,
    set_collection_dal,
    set_feature_dal,
)
from tests.schemas import (
    OGC_COLLECTIONS_SCHEMA,
    OGC_CONFORMANCE_SCHEMA,
    OGC_ITEMS_RESPONSE_SCHEMA,
    OGC_LANDING_PAGE_SCHEMA,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_URL = "https://api.example.com"


def _make_event(
    method: str = "GET",
    path: str = "/",
    query: dict[str, str] | None = None,
    domain: str = "api.example.com",
    stage: str = "$default",
) -> dict[str, Any]:
    """Build a minimal API Gateway HTTP API v2 event."""
    return {
        "rawPath": path,
        "requestContext": {
            "domainName": domain,
            "stage": stage,
            "http": {
                "method": method,
                "path": path,
            },
        },
        "queryStringParameters": query,
    }


def _validate(instance: Any, schema: dict[str, Any]) -> None:
    jsonschema.validate(instance, schema)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_handler_singletons() -> None:
    """Reset handler singletons before each test."""
    reset_singletons()


@pytest.fixture()
def _setup_dals(
    collection_dal: Any,
    dal: Any,
    lambda_env: dict[str, str],
) -> None:
    """Inject moto-backed DALs into handlers."""
    set_collection_dal(collection_dal)
    set_feature_dal(dal)


@pytest.fixture()
def _setup_with_collection(
    _setup_dals: None,
    collection_dal: Any,
    sample_collection_config: Any,
) -> None:
    """Set up DALs and seed a collection."""
    collection_dal.put_collection(sample_collection_config)


@pytest.fixture()
def _setup_with_features(
    _setup_with_collection: None,
    dal: Any,
    sample_collection_config: Any,
) -> None:
    """Set up DALs, seed a collection, and add sample features."""
    for i in range(3):
        dal.create_feature(
            collection_id=sample_collection_config.collection_id,
            feature_data={
                "geometry": {"type": "Point", "coordinates": [-114.0 + i * 0.1, 43.0]},
                "properties": {"name": f"Cave {i}", "visibility": "public"},
            },
            organization="GemStateGrotto",
            visibility="public",
        )


# ===================================================================
# Routing tests
# ===================================================================


class TestRouting:
    """Verify the handler routes requests correctly."""

    def test_unknown_route_returns_404(self) -> None:
        event = _make_event(path="/nonexistent")
        resp = handler(event, None)
        assert resp["statusCode"] == 404

    def test_post_on_read_route_returns_404(self) -> None:
        event = _make_event(method="POST", path="/conformance")
        resp = handler(event, None)
        assert resp["statusCode"] == 404

    def test_trailing_slash_stripped(self, _setup_dals: None) -> None:
        event = _make_event(path="/conformance/")
        resp = handler(event, None)
        assert resp["statusCode"] == 200


# ===================================================================
# GET / — Landing page
# ===================================================================


class TestLandingPage:
    """Tests for the landing page endpoint."""

    def test_landing_page_returns_200(self, _setup_dals: None) -> None:
        event = _make_event(path="/")
        resp = handler(event, None)
        assert resp["statusCode"] == 200

    def test_landing_page_content_type(self, _setup_dals: None) -> None:
        event = _make_event(path="/")
        resp = handler(event, None)
        assert resp["headers"]["Content-Type"] == "application/json"

    def test_landing_page_validates(self, _setup_dals: None) -> None:
        event = _make_event(path="/")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        _validate(body, OGC_LANDING_PAGE_SCHEMA)

    def test_landing_page_has_required_links(self, _setup_dals: None) -> None:
        event = _make_event(path="/")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        rels = {link["rel"] for link in body["links"]}
        assert "self" in rels
        assert "service-desc" in rels
        assert "conformance" in rels
        assert "data" in rels

    def test_landing_page_links_use_base_url(self, _setup_dals: None) -> None:
        event = _make_event(path="/")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        for link in body["links"]:
            assert link["href"].startswith("https://api.example.com/")

    def test_landing_page_with_stage(self, _setup_dals: None) -> None:
        event = _make_event(path="/", stage="prod")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        for link in body["links"]:
            assert link["href"].startswith("https://api.example.com/prod/")


# ===================================================================
# GET /conformance
# ===================================================================


class TestConformance:
    """Tests for the conformance endpoint."""

    def test_conformance_returns_200(self, _setup_dals: None) -> None:
        event = _make_event(path="/conformance")
        resp = handler(event, None)
        assert resp["statusCode"] == 200

    def test_conformance_validates(self, _setup_dals: None) -> None:
        event = _make_event(path="/conformance")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        _validate(body, OGC_CONFORMANCE_SCHEMA)

    def test_conformance_includes_core_classes(self, _setup_dals: None) -> None:
        event = _make_event(path="/conformance")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core" in body["conformsTo"]
        assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson" in body["conformsTo"]
        assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30" in body["conformsTo"]

    def test_conformance_content_type(self, _setup_dals: None) -> None:
        event = _make_event(path="/conformance")
        resp = handler(event, None)
        assert resp["headers"]["Content-Type"] == "application/json"


# ===================================================================
# GET /collections
# ===================================================================


class TestCollections:
    """Tests for the collections list endpoint."""

    def test_collections_empty(self, _setup_dals: None) -> None:
        event = _make_event(path="/collections")
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["collections"] == []

    def test_collections_validates(self, _setup_dals: None) -> None:
        event = _make_event(path="/collections")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        _validate(body, OGC_COLLECTIONS_SCHEMA)

    def test_collections_with_data(self, _setup_with_collection: None) -> None:
        event = _make_event(path="/collections")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert len(body["collections"]) == 1
        assert body["collections"][0]["id"] == "caves"

    def test_collections_has_self_link(self, _setup_dals: None) -> None:
        event = _make_event(path="/collections")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        rels = {link["rel"] for link in body["links"]}
        assert "self" in rels

    def test_collections_content_type(self, _setup_dals: None) -> None:
        event = _make_event(path="/collections")
        resp = handler(event, None)
        assert resp["headers"]["Content-Type"] == "application/json"


# ===================================================================
# GET /collections/{collectionId}
# ===================================================================


class TestSingleCollection:
    """Tests for the single collection endpoint."""

    def test_collection_found(self, _setup_with_collection: None) -> None:
        event = _make_event(path="/collections/caves")
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["id"] == "caves"
        assert body["title"] == "Caves"

    def test_collection_not_found(self, _setup_dals: None) -> None:
        event = _make_event(path="/collections/nonexistent")
        resp = handler(event, None)
        assert resp["statusCode"] == 404

    def test_collection_has_links(self, _setup_with_collection: None) -> None:
        event = _make_event(path="/collections/caves")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        rels = {link["rel"] for link in body["links"]}
        assert "self" in rels
        assert "items" in rels
        assert "describedby" in rels

    def test_collection_content_type(self, _setup_with_collection: None) -> None:
        event = _make_event(path="/collections/caves")
        resp = handler(event, None)
        assert resp["headers"]["Content-Type"] == "application/json"


# ===================================================================
# GET /collections/{collectionId}/items
# ===================================================================


class TestItems:
    """Tests for the feature collection items endpoint."""

    def test_items_requires_organization(self, _setup_with_collection: None) -> None:
        event = _make_event(path="/collections/caves/items")
        resp = handler(event, None)
        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert "organization" in body.get("detail", "")

    def test_items_collection_not_found(self, _setup_dals: None) -> None:
        event = _make_event(
            path="/collections/nonexistent/items",
            query={"organization": "TestOrg"},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 404

    def test_items_empty(self, _setup_with_collection: None) -> None:
        event = _make_event(
            path="/collections/caves/items",
            query={"organization": "GemStateGrotto"},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["type"] == "FeatureCollection"
        assert body["features"] == []
        assert body["numberReturned"] == 0

    def test_items_content_type_is_geojson(self, _setup_with_collection: None) -> None:
        event = _make_event(
            path="/collections/caves/items",
            query={"organization": "GemStateGrotto"},
        )
        resp = handler(event, None)
        assert resp["headers"]["Content-Type"] == "application/geo+json"

    def test_items_validates(self, _setup_with_collection: None) -> None:
        event = _make_event(
            path="/collections/caves/items",
            query={"organization": "GemStateGrotto"},
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        _validate(body, OGC_ITEMS_RESPONSE_SCHEMA)

    def test_items_with_features(self, _setup_with_features: None) -> None:
        event = _make_event(
            path="/collections/caves/items",
            query={"organization": "GemStateGrotto"},
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert len(body["features"]) == 3
        assert body["numberReturned"] == 3

    def test_items_has_links(self, _setup_with_features: None) -> None:
        event = _make_event(
            path="/collections/caves/items",
            query={"organization": "GemStateGrotto"},
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        rels = {link["rel"] for link in body["links"]}
        assert "self" in rels
        assert "collection" in rels

    def test_items_has_timestamp(self, _setup_with_features: None) -> None:
        event = _make_event(
            path="/collections/caves/items",
            query={"organization": "GemStateGrotto"},
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert "timeStamp" in body

    def test_items_limit(self, _setup_with_features: None) -> None:
        event = _make_event(
            path="/collections/caves/items",
            query={"organization": "GemStateGrotto", "limit": "1"},
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert len(body["features"]) == 1
        assert body["numberReturned"] == 1
        # Should have a next link
        rels = {link["rel"] for link in body["links"]}
        assert "next" in rels

    def test_items_pagination_cursor(self, _setup_with_features: None) -> None:
        # Get first page
        event1 = _make_event(
            path="/collections/caves/items",
            query={"organization": "GemStateGrotto", "limit": "2"},
        )
        resp1 = handler(event1, None)
        body1 = json.loads(resp1["body"])
        assert len(body1["features"]) == 2

        # Extract cursor from next link
        next_links = [link for link in body1["links"] if link["rel"] == "next"]
        assert len(next_links) == 1
        next_href = next_links[0]["href"]
        # Extract cursor parameter
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(next_href)
        cursor = parse_qs(parsed.query)["cursor"][0]

        # Get second page
        event2 = _make_event(
            path="/collections/caves/items",
            query={"organization": "GemStateGrotto", "limit": "2", "cursor": cursor},
        )
        resp2 = handler(event2, None)
        body2 = json.loads(resp2["body"])
        assert len(body2["features"]) == 1  # Only 1 remaining

    def test_items_org_isolation(self, _setup_with_features: None) -> None:
        """Different org sees no features."""
        event = _make_event(
            path="/collections/caves/items",
            query={"organization": "OtherOrg"},
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body["features"] == []

    def test_items_property_filter(self, _setup_with_features: None) -> None:
        event = _make_event(
            path="/collections/caves/items",
            query={"organization": "GemStateGrotto", "name": "Cave 0"},
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert len(body["features"]) == 1
        assert body["features"][0]["properties"]["name"] == "Cave 0"

    def test_items_bbox_filter(self, _setup_with_features: None) -> None:
        event = _make_event(
            path="/collections/caves/items",
            query={
                "organization": "GemStateGrotto",
                "bbox": "-114.05,42.9,-113.95,43.1",
            },
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        # Only the first feature at -114.0,43.0 should match
        assert len(body["features"]) == 1


# ===================================================================
# GET /collections/{collectionId}/items/{featureId}
# ===================================================================


class TestSingleFeature:
    """Tests for the single feature endpoint."""

    def test_feature_requires_organization(self, _setup_with_collection: None) -> None:
        event = _make_event(path="/collections/caves/items/some-id")
        resp = handler(event, None)
        assert resp["statusCode"] == 400

    def test_feature_not_found(self, _setup_with_collection: None) -> None:
        event = _make_event(
            path="/collections/caves/items/nonexistent",
            query={"organization": "GemStateGrotto"},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 404

    def test_feature_found(self, _setup_with_features: None, dal: Any) -> None:
        # Get the ID of a feature we created
        result = dal.query_features("caves", "GemStateGrotto", limit=1)
        feature = result.features[0]

        event = _make_event(
            path=f"/collections/caves/items/{feature.id}",
            query={"organization": "GemStateGrotto"},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["type"] == "Feature"
        assert body["id"] == feature.id

    def test_feature_content_type_is_geojson(self, _setup_with_features: None, dal: Any) -> None:
        result = dal.query_features("caves", "GemStateGrotto", limit=1)
        feature = result.features[0]

        event = _make_event(
            path=f"/collections/caves/items/{feature.id}",
            query={"organization": "GemStateGrotto"},
        )
        resp = handler(event, None)
        assert resp["headers"]["Content-Type"] == "application/geo+json"

    def test_feature_has_etag_header(self, _setup_with_features: None, dal: Any) -> None:
        result = dal.query_features("caves", "GemStateGrotto", limit=1)
        feature = result.features[0]

        event = _make_event(
            path=f"/collections/caves/items/{feature.id}",
            query={"organization": "GemStateGrotto"},
        )
        resp = handler(event, None)
        assert "ETag" in resp["headers"]
        assert resp["headers"]["ETag"].startswith('"')
        assert resp["headers"]["ETag"].endswith('"')

    def test_feature_has_links(self, _setup_with_features: None, dal: Any) -> None:
        result = dal.query_features("caves", "GemStateGrotto", limit=1)
        feature = result.features[0]

        event = _make_event(
            path=f"/collections/caves/items/{feature.id}",
            query={"organization": "GemStateGrotto"},
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        rels = {link["rel"] for link in body["links"]}
        assert "self" in rels
        assert "collection" in rels

    def test_feature_org_isolation(self, _setup_with_features: None, dal: Any) -> None:
        """Wrong org returns 404."""
        result = dal.query_features("caves", "GemStateGrotto", limit=1)
        feature = result.features[0]

        event = _make_event(
            path=f"/collections/caves/items/{feature.id}",
            query={"organization": "WrongOrg"},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 404


# ===================================================================
# GET /collections/{collectionId}/schema
# ===================================================================


class TestSchema:
    """Tests for the schema endpoint."""

    def test_schema_returns_200(self, _setup_with_collection: None) -> None:
        event = _make_event(path="/collections/caves/schema")
        resp = handler(event, None)
        assert resp["statusCode"] == 200

    def test_schema_content_type(self, _setup_with_collection: None) -> None:
        event = _make_event(path="/collections/caves/schema")
        resp = handler(event, None)
        assert resp["headers"]["Content-Type"] == "application/schema+json"

    def test_schema_is_valid_json_schema(self, _setup_with_collection: None) -> None:
        event = _make_event(path="/collections/caves/schema")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        jsonschema.Draft202012Validator.check_schema(body)

    def test_schema_collection_not_found(self, _setup_dals: None) -> None:
        event = _make_event(path="/collections/nonexistent/schema")
        resp = handler(event, None)
        assert resp["statusCode"] == 404

    def test_schema_receivable_variant(self, _setup_with_collection: None) -> None:
        event = _make_event(
            path="/collections/caves/schema",
            query={"type": "receivable"},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        # Receivable should not have "id" in properties
        assert "id" not in body["properties"]

    def test_schema_uses_api_base_url(self, _setup_with_collection: None) -> None:
        event = _make_event(path="/collections/caves/schema")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body["$id"] == "https://api.example.com/collections/caves/schema"


# ===================================================================
# GET /api — OpenAPI definition
# ===================================================================


class TestOpenAPI:
    """Tests for the OpenAPI definition endpoint."""

    def test_api_returns_200(self, _setup_dals: None) -> None:
        event = _make_event(path="/api")
        resp = handler(event, None)
        assert resp["statusCode"] == 200

    def test_api_content_type(self, _setup_dals: None) -> None:
        event = _make_event(path="/api")
        resp = handler(event, None)
        assert resp["headers"]["Content-Type"] == "application/vnd.oai.openapi+json;version=3.0"

    def test_api_has_basic_structure(self, _setup_dals: None) -> None:
        event = _make_event(path="/api")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body["openapi"] == "3.0.3"
        assert "info" in body
        assert "paths" in body
        assert "/" in body["paths"]
        assert "/conformance" in body["paths"]
        assert "/collections" in body["paths"]

    def test_api_includes_collection_paths(self, _setup_with_collection: None) -> None:
        event = _make_event(path="/api")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert "/collections/caves" in body["paths"]
        assert "/collections/caves/items" in body["paths"]
        assert "/collections/caves/items/{featureId}" in body["paths"]
        assert "/collections/caves/schema" in body["paths"]

    def test_api_server_url(self, _setup_dals: None) -> None:
        event = _make_event(path="/api")
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body["servers"][0]["url"] == "https://api.example.com"


# ===================================================================
# Error responses
# ===================================================================


class TestErrorResponses:
    """Tests for error response format."""

    def test_404_is_problem_json(self, _setup_dals: None) -> None:
        event = _make_event(path="/nonexistent")
        resp = handler(event, None)
        assert resp["headers"]["Content-Type"] == "application/problem+json"
        body = json.loads(resp["body"])
        assert body["status"] == 404
        assert "title" in body

    def test_400_is_problem_json(self, _setup_with_collection: None) -> None:
        event = _make_event(path="/collections/caves/items")
        resp = handler(event, None)
        assert resp["headers"]["Content-Type"] == "application/problem+json"
        body = json.loads(resp["body"])
        assert body["status"] == 400
