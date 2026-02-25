"""Integration tests for OAPIF Part 4 (CRUD) write endpoints against DynamoDB Local.

These tests exercise the full handler stack for write operations:
- POST /collections/{collectionId}/items (create)
- PUT /collections/{collectionId}/items/{featureId} (replace)
- PATCH /collections/{collectionId}/items/{featureId} (update via merge patch)
- DELETE /collections/{collectionId}/items/{featureId} (soft delete)
- OPTIONS on items / feature endpoints
- ETag / If-Match optimistic concurrency
- Schema validation on write bodies
- Change tracking table writes
"""

from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any

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

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    method: str = "GET",
    path: str = "/",
    query: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal API Gateway HTTP API v2 event."""
    event: dict[str, Any] = {
        "rawPath": path,
        "requestContext": {
            "domainName": "api.test.com",
            "stage": "$default",
            "http": {"method": method, "path": path},
        },
        "queryStringParameters": query,
        "headers": headers or {},
    }
    if body is not None:
        event["body"] = json.dumps(body)
        event["isBase64Encoded"] = False
    if claims is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": claims}}
    return event


def _auth_claims(
    org: str,
    groups: list[str] | None = None,
    sub: str = "user-1",
) -> dict[str, Any]:
    """Build Cognito JWT claims for an authenticated user.

    Includes ``editor`` role by default so write operations are authorized.
    """
    all_groups = [f"org:{org}", "admin"]
    if groups:
        all_groups.extend(groups)
    return {
        "sub": sub,
        "email": "test@example.com",
        "cognito:groups": " ".join(all_groups),
    }


def _valid_feature_body(
    name: str = "Test Feature",
    lon: float = -114.0,
    lat: float = 43.0,
    visibility: str = "public",
    **extra_props: Any,
) -> dict[str, Any]:
    """Build a valid GeoJSON Feature body for POST/PUT."""
    props: dict[str, Any] = {"name": name, "visibility": visibility, **extra_props}
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def _extract_etag(resp: dict[str, Any]) -> str:
    """Extract and unquote the ETag from a response."""
    raw = resp["headers"]["ETag"]
    return raw.strip('"')


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def crud_config_table_name() -> str:
    return "oapif-crud-config"


@pytest.fixture(scope="session")
def crud_features_table_name() -> str:
    return "oapif-crud-features"


@pytest.fixture(scope="session")
def crud_changes_table_name() -> str:
    return "oapif-crud-changes"


@pytest.fixture(scope="session")
def _ensure_crud_tables(
    dynamodb_local_resource: Any,
    crud_config_table_name: str,
    crud_features_table_name: str,
    crud_changes_table_name: str,
) -> None:
    for table_name in [
        crud_config_table_name,
        crud_features_table_name,
        crud_changes_table_name,
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
def crud_collection_dal(
    dynamodb_local_resource: Any,
    crud_config_table_name: str,
    _ensure_crud_tables: None,
) -> CollectionDAL:
    return CollectionDAL(
        dynamodb_resource=dynamodb_local_resource,
        config_table_name=crud_config_table_name,
    )


@pytest.fixture()
def crud_feature_dal(
    dynamodb_local_resource: Any,
    crud_features_table_name: str,
    crud_changes_table_name: str,
    _ensure_crud_tables: None,
) -> FeatureDAL:
    return FeatureDAL(
        dynamodb_resource=dynamodb_local_resource,
        features_table_name=crud_features_table_name,
        changes_table_name=crud_changes_table_name,
    )


@pytest.fixture(autouse=True)
def _reset_and_inject(
    crud_collection_dal: CollectionDAL,
    crud_feature_dal: FeatureDAL,
) -> None:
    reset_singletons()
    set_collection_dal(crud_collection_dal)
    set_feature_dal(crud_feature_dal)


@pytest.fixture()
def org_id() -> str:
    return f"test-org-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def collection_id() -> str:
    return f"test-col-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def seeded_collection(
    crud_collection_dal: CollectionDAL,
    collection_id: str,
    org_id: str,
) -> CollectionConfig:
    config = CollectionConfig(
        collection_id=collection_id,
        title="CRUD Collection",
        description="Integration test CRUD data",
        extent=CollectionExtent(
            spatial=SpatialExtent(bbox=[[-117.0, 42.0, -111.0, 49.0]]),
            temporal=TemporalExtent(interval=[["2024-01-01T00:00:00Z", None]]),
        ),
        properties_schema={
            "name": PropertySchema(type="string", description="Feature name"),
            "depth_m": PropertySchema(type="number", description="Depth in meters"),
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
    crud_collection_dal.put_collection(config)
    return config


# ===================================================================
# POST — Create feature
# ===================================================================


class TestCreateFeature:
    """Tests for POST /collections/{collectionId}/items."""

    def test_create_returns_201(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        event = _make_event(
            method="POST",
            path=f"/collections/{seeded_collection.collection_id}/items",
            body=_valid_feature_body(),
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 201

    def test_create_returns_location_header(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        event = _make_event(
            method="POST",
            path=f"/collections/{seeded_collection.collection_id}/items",
            body=_valid_feature_body(),
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert "Location" in resp["headers"]
        body = json.loads(resp["body"])
        assert resp["headers"]["Location"].endswith(f"/items/{body['id']}")

    def test_create_returns_etag(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        event = _make_event(
            method="POST",
            path=f"/collections/{seeded_collection.collection_id}/items",
            body=_valid_feature_body(),
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert "ETag" in resp["headers"]
        assert resp["headers"]["ETag"].startswith('"')

    def test_create_returns_geojson_feature(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        event = _make_event(
            method="POST",
            path=f"/collections/{seeded_collection.collection_id}/items",
            body=_valid_feature_body(name="My Feature"),
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body["type"] == "Feature"
        assert body["properties"]["name"] == "My Feature"
        assert body["properties"]["organization"] == org_id
        assert body["properties"]["visibility"] == "public"
        assert "id" in body

    def test_create_feature_is_readable(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        """Created feature can be read back with GET."""
        create_event = _make_event(
            method="POST",
            path=f"/collections/{seeded_collection.collection_id}/items",
            body=_valid_feature_body(name="Readable Feature"),
            claims=_auth_claims(org_id),
        )
        create_resp = handler(create_event, None)
        created = json.loads(create_resp["body"])

        get_event = _make_event(
            method="GET",
            path=f"/collections/{seeded_collection.collection_id}/items/{created['id']}",
            query={"organization": org_id},
        )
        get_resp = handler(get_event, None)
        assert get_resp["statusCode"] == 200
        got = json.loads(get_resp["body"])
        assert got["id"] == created["id"]
        assert got["properties"]["name"] == "Readable Feature"

    def test_create_requires_authentication(self, seeded_collection: CollectionConfig) -> None:
        """Unauthenticated POST returns 401."""
        event = _make_event(
            method="POST",
            path=f"/collections/{seeded_collection.collection_id}/items",
            body=_valid_feature_body(),
            query={"organization": "SomeOrg"},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 401

    def test_create_validates_body_schema(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        """Missing required 'name' property returns 422."""
        event = _make_event(
            method="POST",
            path=f"/collections/{seeded_collection.collection_id}/items",
            body={
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-114.0, 43.0]},
                "properties": {},  # Missing required 'name'
            },
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 422

    def test_create_invalid_json_returns_400(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        event = _make_event(
            method="POST",
            path=f"/collections/{seeded_collection.collection_id}/items",
            claims=_auth_claims(org_id),
        )
        event["body"] = "not json"
        resp = handler(event, None)
        assert resp["statusCode"] == 400

    def test_create_empty_body_returns_400(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        event = _make_event(
            method="POST",
            path=f"/collections/{seeded_collection.collection_id}/items",
            claims=_auth_claims(org_id),
        )
        # No body at all
        resp = handler(event, None)
        assert resp["statusCode"] == 400

    def test_create_nonexistent_collection_returns_404(self, org_id: str) -> None:
        event = _make_event(
            method="POST",
            path="/collections/nonexistent/items",
            body=_valid_feature_body(),
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 404

    def test_create_content_type_is_geojson(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        event = _make_event(
            method="POST",
            path=f"/collections/{seeded_collection.collection_id}/items",
            body=_valid_feature_body(),
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["headers"]["Content-Type"] == "application/geo+json"

    def test_create_has_links(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        event = _make_event(
            method="POST",
            path=f"/collections/{seeded_collection.collection_id}/items",
            body=_valid_feature_body(),
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        rels = {link["rel"] for link in body["links"]}
        assert "self" in rels
        assert "collection" in rels


# ===================================================================
# PUT — Replace feature
# ===================================================================


class TestReplaceFeature:
    """Tests for PUT /collections/{collectionId}/items/{featureId}."""

    def _create_feature(self, collection_id: str, org_id: str, name: str = "Replace Me") -> tuple[str, str]:
        """Helper: create a feature and return (feature_id, etag)."""
        event = _make_event(
            method="POST",
            path=f"/collections/{collection_id}/items",
            body=_valid_feature_body(name=name),
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        return body["id"], _extract_etag(resp)

    def test_replace_returns_200(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PUT",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body=_valid_feature_body(name="Replaced"),
            headers={"if-match": f'"{etag}"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200

    def test_replace_updates_content(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PUT",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body=_valid_feature_body(name="New Name", depth_m=100.5),
            headers={"if-match": f'"{etag}"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body["properties"]["name"] == "New Name"
        assert body["properties"]["depth_m"] == 100.5

    def test_replace_returns_new_etag(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PUT",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body=_valid_feature_body(name="New"),
            headers={"if-match": f'"{etag}"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        new_etag = _extract_etag(resp)
        assert new_etag != etag

    def test_replace_without_if_match_returns_428(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, _etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PUT",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body=_valid_feature_body(name="No ETag"),
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 428

    def test_replace_wrong_etag_returns_412(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, _etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PUT",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body=_valid_feature_body(name="Wrong ETag"),
            headers={"if-match": '"wrong-etag"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 412

    def test_replace_nonexistent_feature_returns_404(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        event = _make_event(
            method="PUT",
            path=f"/collections/{seeded_collection.collection_id}/items/nonexistent",
            body=_valid_feature_body(),
            headers={"if-match": '"some-etag"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 404

    def test_replace_validates_schema(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PUT",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body={
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-114.0, 43.0]},
                "properties": {},  # Missing required 'name'
            },
            headers={"if-match": f'"{etag}"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 422

    def test_replace_requires_authentication(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PUT",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body=_valid_feature_body(),
            headers={"if-match": f'"{etag}"'},
            query={"organization": org_id},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 401

    def test_replace_org_immutable(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        body = _valid_feature_body()
        body["properties"]["organization"] = "DifferentOrg"
        event = _make_event(
            method="PUT",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body=body,
            headers={"if-match": f'"{etag}"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 422


# ===================================================================
# PATCH — Update feature (JSON Merge Patch)
# ===================================================================


class TestUpdateFeature:
    """Tests for PATCH /collections/{collectionId}/items/{featureId}."""

    def _create_feature(self, collection_id: str, org_id: str, name: str = "Patch Me") -> tuple[str, str]:
        event = _make_event(
            method="POST",
            path=f"/collections/{collection_id}/items",
            body=_valid_feature_body(name=name, depth_m=50.0),
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        return body["id"], _extract_etag(resp)

    def test_patch_returns_200(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PATCH",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body={"properties": {"name": "Patched"}},
            headers={"if-match": f'"{etag}"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200

    def test_patch_partial_update(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        """PATCH only modifies specified fields; other fields are preserved."""
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PATCH",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body={"properties": {"name": "Updated Name"}},
            headers={"if-match": f'"{etag}"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body["properties"]["name"] == "Updated Name"
        # depth_m should be preserved from the original
        assert body["properties"]["depth_m"] == 50.0

    def test_patch_geometry(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PATCH",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body={"geometry": {"type": "Point", "coordinates": [-115.0, 44.0]}},
            headers={"if-match": f'"{etag}"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body["geometry"]["coordinates"] == [-115.0, 44.0]

    def test_patch_returns_new_etag(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PATCH",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body={"properties": {"name": "New"}},
            headers={"if-match": f'"{etag}"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        new_etag = _extract_etag(resp)
        assert new_etag != etag

    def test_patch_without_if_match_returns_428(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, _etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PATCH",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body={"properties": {"name": "No ETag"}},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 428

    def test_patch_wrong_etag_returns_412(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, _etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PATCH",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body={"properties": {"name": "Wrong"}},
            headers={"if-match": '"wrong-etag"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 412

    def test_patch_nonexistent_feature_returns_404(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        event = _make_event(
            method="PATCH",
            path=f"/collections/{seeded_collection.collection_id}/items/nonexistent",
            body={"properties": {"name": "Nope"}},
            headers={"if-match": '"some-etag"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 404

    def test_patch_requires_authentication(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PATCH",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body={"properties": {"name": "Unauth"}},
            headers={"if-match": f'"{etag}"'},
            query={"organization": org_id},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 401

    def test_patch_org_immutable(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="PATCH",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            body={"properties": {"organization": "DifferentOrg"}},
            headers={"if-match": f'"{etag}"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 422


# ===================================================================
# DELETE — Soft delete feature
# ===================================================================


class TestDeleteFeature:
    """Tests for DELETE /collections/{collectionId}/items/{featureId}."""

    def _create_feature(self, collection_id: str, org_id: str, name: str = "Delete Me") -> tuple[str, str]:
        event = _make_event(
            method="POST",
            path=f"/collections/{collection_id}/items",
            body=_valid_feature_body(name=name),
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        return body["id"], _extract_etag(resp)

    def test_delete_returns_204(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="DELETE",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            headers={"if-match": f'"{etag}"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 204

    def test_delete_feature_no_longer_readable(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        """Deleted feature returns 404 on subsequent GET."""
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        # Delete
        del_event = _make_event(
            method="DELETE",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            headers={"if-match": f'"{etag}"'},
            claims=_auth_claims(org_id),
        )
        handler(del_event, None)

        # Try to read
        get_event = _make_event(
            method="GET",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            query={"organization": org_id},
        )
        get_resp = handler(get_event, None)
        assert get_resp["statusCode"] == 404

    def test_delete_without_if_match_returns_428(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, _etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="DELETE",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 428

    def test_delete_wrong_etag_returns_412(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, _etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="DELETE",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            headers={"if-match": '"wrong-etag"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 412

    def test_delete_nonexistent_returns_404(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        event = _make_event(
            method="DELETE",
            path=f"/collections/{seeded_collection.collection_id}/items/nonexistent",
            headers={"if-match": '"some-etag"'},
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 404

    def test_delete_requires_authentication(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        fid, etag = self._create_feature(seeded_collection.collection_id, org_id)
        event = _make_event(
            method="DELETE",
            path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
            headers={"if-match": f'"{etag}"'},
            query={"organization": org_id},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 401


# ===================================================================
# OPTIONS
# ===================================================================


class TestOptions:
    """Tests for OPTIONS on items and feature endpoints."""

    def test_options_items(self, seeded_collection: CollectionConfig) -> None:
        event = _make_event(
            method="OPTIONS",
            path=f"/collections/{seeded_collection.collection_id}/items",
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 204
        assert "GET" in resp["headers"]["Allow"]
        assert "POST" in resp["headers"]["Allow"]

    def test_options_feature(self, seeded_collection: CollectionConfig) -> None:
        event = _make_event(
            method="OPTIONS",
            path=f"/collections/{seeded_collection.collection_id}/items/any-id",
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 204
        allow = resp["headers"]["Allow"]
        assert "GET" in allow
        assert "PUT" in allow
        assert "PATCH" in allow
        assert "DELETE" in allow

    def test_options_feature_has_accept_patch(self, seeded_collection: CollectionConfig) -> None:
        event = _make_event(
            method="OPTIONS",
            path=f"/collections/{seeded_collection.collection_id}/items/any-id",
        )
        resp = handler(event, None)
        assert resp["headers"].get("Accept-Patch") == "application/merge-patch+json"


# ===================================================================
# Full CRUD lifecycle
# ===================================================================


class TestFullCRUDLifecycle:
    """End-to-end CRUD lifecycle test."""

    def test_full_lifecycle(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        """Create → Read → Update → Replace → Delete → Verify gone."""
        cid = seeded_collection.collection_id
        claims = _auth_claims(org_id)

        # 1. CREATE
        create_resp = handler(
            _make_event(
                method="POST",
                path=f"/collections/{cid}/items",
                body=_valid_feature_body(name="Lifecycle Feature", depth_m=25.0),
                claims=claims,
            ),
            None,
        )
        assert create_resp["statusCode"] == 201
        created = json.loads(create_resp["body"])
        fid = created["id"]
        etag1 = _extract_etag(create_resp)

        # 2. READ
        get_resp = handler(
            _make_event(
                method="GET",
                path=f"/collections/{cid}/items/{fid}",
                query={"organization": org_id},
            ),
            None,
        )
        assert get_resp["statusCode"] == 200
        got = json.loads(get_resp["body"])
        assert got["properties"]["name"] == "Lifecycle Feature"
        assert got["properties"]["depth_m"] == 25.0

        # 3. PATCH (update depth_m only)
        patch_resp = handler(
            _make_event(
                method="PATCH",
                path=f"/collections/{cid}/items/{fid}",
                body={"properties": {"depth_m": 50.0}},
                headers={"if-match": f'"{etag1}"'},
                claims=claims,
            ),
            None,
        )
        assert patch_resp["statusCode"] == 200
        patched = json.loads(patch_resp["body"])
        assert patched["properties"]["depth_m"] == 50.0
        assert patched["properties"]["name"] == "Lifecycle Feature"  # Preserved
        etag2 = _extract_etag(patch_resp)
        assert etag2 != etag1

        # 4. PUT (replace entire feature)
        put_resp = handler(
            _make_event(
                method="PUT",
                path=f"/collections/{cid}/items/{fid}",
                body=_valid_feature_body(name="Replaced Feature", depth_m=75.0),
                headers={"if-match": f'"{etag2}"'},
                claims=claims,
            ),
            None,
        )
        assert put_resp["statusCode"] == 200
        replaced = json.loads(put_resp["body"])
        assert replaced["properties"]["name"] == "Replaced Feature"
        etag3 = _extract_etag(put_resp)
        assert etag3 != etag2

        # 5. DELETE
        del_resp = handler(
            _make_event(
                method="DELETE",
                path=f"/collections/{cid}/items/{fid}",
                headers={"if-match": f'"{etag3}"'},
                claims=claims,
            ),
            None,
        )
        assert del_resp["statusCode"] == 204

        # 6. VERIFY GONE
        gone_resp = handler(
            _make_event(
                method="GET",
                path=f"/collections/{cid}/items/{fid}",
                query={"organization": org_id},
            ),
            None,
        )
        assert gone_resp["statusCode"] == 404

    def test_stale_etag_after_update_is_rejected(self, seeded_collection: CollectionConfig, org_id: str) -> None:
        """After an update, the old ETag is stale and rejected."""
        cid = seeded_collection.collection_id
        claims = _auth_claims(org_id)

        create_resp = handler(
            _make_event(
                method="POST",
                path=f"/collections/{cid}/items",
                body=_valid_feature_body(name="Stale Test"),
                claims=claims,
            ),
            None,
        )
        fid = json.loads(create_resp["body"])["id"]
        etag1 = _extract_etag(create_resp)

        # Update
        patch_resp = handler(
            _make_event(
                method="PATCH",
                path=f"/collections/{cid}/items/{fid}",
                body={"properties": {"name": "Updated"}},
                headers={"if-match": f'"{etag1}"'},
                claims=claims,
            ),
            None,
        )
        assert patch_resp["statusCode"] == 200

        # Try to use stale etag
        stale_resp = handler(
            _make_event(
                method="PATCH",
                path=f"/collections/{cid}/items/{fid}",
                body={"properties": {"name": "Should Fail"}},
                headers={"if-match": f'"{etag1}"'},
                claims=claims,
            ),
            None,
        )
        assert stale_resp["statusCode"] == 412


# ===================================================================
# Change tracking
# ===================================================================


class TestChangeTracking:
    """Verify that mutations write to the change tracking table."""

    def test_create_writes_change_record(
        self,
        seeded_collection: CollectionConfig,
        org_id: str,
        crud_feature_dal: FeatureDAL,
        crud_changes_table_name: str,
        dynamodb_local_resource: Any,
    ) -> None:
        """POST creates a CHANGE record in the changes table."""
        event = _make_event(
            method="POST",
            path=f"/collections/{seeded_collection.collection_id}/items",
            body=_valid_feature_body(name="Change Track"),
            claims=_auth_claims(org_id),
        )
        resp = handler(event, None)
        fid = json.loads(resp["body"])["id"]

        # Query changes table directly
        from boto3.dynamodb.conditions import Key

        from oapif.models.feature import Feature

        changes_table = dynamodb_local_resource.Table(crud_changes_table_name)

        result = changes_table.query(
            KeyConditionExpression=Key("PK").eq(Feature.make_pk(org_id, seeded_collection.collection_id))
            & Key("SK").begins_with("CHANGE#"),
        )
        matching = [i for i in result["Items"] if i["feature_id"] == fid and i["operation"] == "CREATE"]
        assert len(matching) >= 1

    def test_delete_writes_change_record(
        self,
        seeded_collection: CollectionConfig,
        org_id: str,
        crud_changes_table_name: str,
        dynamodb_local_resource: Any,
    ) -> None:
        """DELETE creates a CHANGE record."""
        claims = _auth_claims(org_id)
        create_resp = handler(
            _make_event(
                method="POST",
                path=f"/collections/{seeded_collection.collection_id}/items",
                body=_valid_feature_body(name="Will Delete"),
                claims=claims,
            ),
            None,
        )
        fid = json.loads(create_resp["body"])["id"]
        etag = _extract_etag(create_resp)

        handler(
            _make_event(
                method="DELETE",
                path=f"/collections/{seeded_collection.collection_id}/items/{fid}",
                headers={"if-match": f'"{etag}"'},
                claims=claims,
            ),
            None,
        )

        from boto3.dynamodb.conditions import Key

        from oapif.models.feature import Feature

        changes_table = dynamodb_local_resource.Table(crud_changes_table_name)
        result = changes_table.query(
            KeyConditionExpression=Key("PK").eq(Feature.make_pk(org_id, seeded_collection.collection_id))
            & Key("SK").begins_with("CHANGE#"),
        )
        delete_records = [i for i in result["Items"] if i["feature_id"] == fid and i["operation"] == "DELETE"]
        assert len(delete_records) >= 1
