"""Unit tests for the DynamoDB data access layer.

All tests use moto-mocked DynamoDB — no Docker or network required.
"""

from __future__ import annotations

from typing import Any

import pytest

from oapif.dal.exceptions import ETagMismatchError, FeatureNotFoundError
from oapif.dal.features import FeatureDAL, _json_merge_patch
from oapif.dal.pagination import decode_cursor, encode_cursor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG = "test-org"
COLLECTION = "my-collection"


def _point_feature(lon: float = -116.0, lat: float = 43.0, **extra_props: Any) -> dict[str, Any]:
    """Build a minimal GeoJSON-like feature dict for testing."""
    return {
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": "Test Feature", **extra_props},
    }


# ======================================================================
# CREATE
# ======================================================================


@pytest.mark.unit
class TestCreateFeature:
    def test_returns_feature_with_id_and_etag(self, dal: FeatureDAL) -> None:
        feature = dal.create_feature(COLLECTION, _point_feature(), ORG)

        assert feature.id  # non-empty
        assert feature.etag  # non-empty
        assert feature.collection_id == COLLECTION
        assert feature.organization == ORG
        assert feature.visibility == "public"
        assert feature.deleted is False
        assert feature.created_at
        assert feature.updated_at
        assert feature.geometry == {"type": "Point", "coordinates": [-116.0, 43.0]}
        assert feature.properties["name"] == "Test Feature"

    def test_generates_unique_ids(self, dal: FeatureDAL) -> None:
        f1 = dal.create_feature(COLLECTION, _point_feature(), ORG)
        f2 = dal.create_feature(COLLECTION, _point_feature(), ORG)
        assert f1.id != f2.id
        assert f1.etag != f2.etag

    def test_respects_visibility_from_properties(self, dal: FeatureDAL) -> None:
        data = _point_feature(visibility="members")
        feature = dal.create_feature(COLLECTION, data, ORG)
        assert feature.visibility == "members"
        # visibility should be extracted, not duplicated in properties
        assert "visibility" not in feature.properties

    def test_ignores_client_supplied_organization(self, dal: FeatureDAL) -> None:
        data = _point_feature(organization="evil-org")
        feature = dal.create_feature(COLLECTION, data, ORG)
        assert feature.organization == ORG
        assert "organization" not in feature.properties

    def test_writes_change_log(self, dal: FeatureDAL) -> None:
        feature = dal.create_feature(COLLECTION, _point_feature(), ORG)

        # Scan the changes table for this feature
        resp = dal._changes_table.scan()
        items = [i for i in resp["Items"] if i["feature_id"] == feature.id and i["operation"] == "CREATE"]
        assert len(items) == 1
        assert items[0]["organization"] == ORG

    def test_null_geometry(self, dal: FeatureDAL) -> None:
        data: dict[str, Any] = {"geometry": None, "properties": {"note": "no location"}}
        feature = dal.create_feature(COLLECTION, data, ORG)
        assert feature.geometry is None


# ======================================================================
# GET
# ======================================================================


@pytest.mark.unit
class TestGetFeature:
    def test_returns_created_feature(self, dal: FeatureDAL) -> None:
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        fetched = dal.get_feature(COLLECTION, created.id, ORG)

        assert fetched.id == created.id
        assert fetched.etag == created.etag
        assert fetched.properties["name"] == "Test Feature"

    def test_not_found_raises(self, dal: FeatureDAL) -> None:
        with pytest.raises(FeatureNotFoundError):
            dal.get_feature(COLLECTION, "nonexistent-id", ORG)

    def test_deleted_feature_raises(self, dal: FeatureDAL) -> None:
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        dal.delete_feature(COLLECTION, created.id, created.etag, ORG)

        with pytest.raises(FeatureNotFoundError):
            dal.get_feature(COLLECTION, created.id, ORG)

    def test_wrong_org_raises(self, dal: FeatureDAL) -> None:
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)

        with pytest.raises(FeatureNotFoundError):
            dal.get_feature(COLLECTION, created.id, "other-org")


# ======================================================================
# QUERY
# ======================================================================


@pytest.mark.unit
class TestQueryFeatures:
    def test_basic_query(self, dal: FeatureDAL) -> None:
        col = "query-basic"
        dal.create_feature(col, _point_feature(), ORG)
        dal.create_feature(col, _point_feature(), ORG)

        result = dal.query_features(col, ORG, limit=10)
        assert len(result.features) == 2
        assert result.next_cursor is None

    def test_empty_collection(self, dal: FeatureDAL) -> None:
        result = dal.query_features("empty-col", ORG, limit=10)
        assert result.features == []
        assert result.next_cursor is None

    def test_excludes_deleted(self, dal: FeatureDAL) -> None:
        col = "query-deleted"
        f1 = dal.create_feature(col, _point_feature(), ORG)
        dal.create_feature(col, _point_feature(), ORG)
        dal.delete_feature(col, f1.id, f1.etag, ORG)

        result = dal.query_features(col, ORG, limit=10)
        assert len(result.features) == 1

    def test_pagination(self, dal: FeatureDAL) -> None:
        col = "query-pagination"
        for _ in range(5):
            dal.create_feature(col, _point_feature(), ORG)

        # First page
        page1 = dal.query_features(col, ORG, limit=2)
        assert len(page1.features) == 2
        assert page1.next_cursor is not None

        # Second page
        page2 = dal.query_features(col, ORG, limit=2, cursor=page1.next_cursor)
        assert len(page2.features) == 2
        assert page2.next_cursor is not None

        # Third page
        page3 = dal.query_features(col, ORG, limit=2, cursor=page2.next_cursor)
        assert len(page3.features) == 1
        assert page3.next_cursor is None

        # All IDs unique
        all_ids = [f.id for f in page1.features + page2.features + page3.features]
        assert len(set(all_ids)) == 5

    def test_visibility_filter(self, dal: FeatureDAL) -> None:
        col = "query-vis"
        dal.create_feature(col, _point_feature(), ORG, visibility="public")
        dal.create_feature(col, _point_feature(), ORG, visibility="members")
        dal.create_feature(col, _point_feature(), ORG, visibility="restricted")

        public_only = dal.query_features(col, ORG, limit=10, visibility_filter=["public"])
        assert len(public_only.features) == 1
        assert public_only.features[0].visibility == "public"

        pub_members = dal.query_features(col, ORG, limit=10, visibility_filter=["public", "members"])
        assert len(pub_members.features) == 2

    def test_property_filter(self, dal: FeatureDAL) -> None:
        col = "query-prop"
        dal.create_feature(col, _point_feature(color="red"), ORG)
        dal.create_feature(col, _point_feature(color="blue"), ORG)
        dal.create_feature(col, _point_feature(color="red"), ORG)

        result = dal.query_features(col, ORG, limit=10, property_filters={"color": "red"})
        assert len(result.features) == 2
        assert all(f.properties["color"] == "red" for f in result.features)

    def test_bbox_filter(self, dal: FeatureDAL) -> None:
        col = "query-bbox"
        # Inside bbox
        dal.create_feature(col, _point_feature(lon=-116.0, lat=43.0), ORG)
        # Outside bbox
        dal.create_feature(col, _point_feature(lon=-80.0, lat=35.0), ORG)

        # Bbox around Boise, Idaho area
        result = dal.query_features(col, ORG, limit=10, bbox=(-117.0, 42.0, -115.0, 44.0))
        assert len(result.features) == 1
        assert result.features[0].geometry is not None
        assert result.features[0].geometry["coordinates"][0] == -116.0

    def test_bbox_excludes_null_geometry(self, dal: FeatureDAL) -> None:
        col = "query-bbox-null"
        dal.create_feature(
            col,
            {"geometry": None, "properties": {"name": "ghost"}},
            ORG,
        )

        result = dal.query_features(col, ORG, limit=10, bbox=(-180.0, -90.0, 180.0, 90.0))
        assert len(result.features) == 0

    def test_organization_scoping(self, dal: FeatureDAL) -> None:
        col = "query-org-scope"
        dal.create_feature(col, _point_feature(), "org-alpha")
        dal.create_feature(col, _point_feature(), "org-beta")

        alpha = dal.query_features(col, "org-alpha", limit=10)
        assert len(alpha.features) == 1
        assert alpha.features[0].organization == "org-alpha"

        beta = dal.query_features(col, "org-beta", limit=10)
        assert len(beta.features) == 1
        assert beta.features[0].organization == "org-beta"


# ======================================================================
# REPLACE
# ======================================================================


@pytest.mark.unit
class TestReplaceFeature:
    def test_replaces_feature(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG)

        new_data: dict[str, Any] = {
            "geometry": {"type": "Point", "coordinates": [-117.0, 44.0]},
            "properties": {"name": "Replaced Feature"},
        }
        replaced = dal.replace_feature(COLLECTION, original.id, new_data, original.etag, ORG)

        assert replaced.id == original.id
        assert replaced.etag != original.etag
        assert replaced.properties["name"] == "Replaced Feature"
        assert replaced.geometry == {"type": "Point", "coordinates": [-117.0, 44.0]}
        assert replaced.created_at == original.created_at
        assert replaced.updated_at >= original.updated_at

    def test_etag_mismatch_raises(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG)

        with pytest.raises(ETagMismatchError):
            dal.replace_feature(COLLECTION, original.id, _point_feature(), "wrong-etag", ORG)

    def test_not_found_raises(self, dal: FeatureDAL) -> None:
        with pytest.raises(FeatureNotFoundError):
            dal.replace_feature(COLLECTION, "nonexistent", _point_feature(), "any-etag", ORG)

    def test_writes_change_log(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG)
        dal.replace_feature(
            COLLECTION,
            original.id,
            _point_feature(),
            original.etag,
            ORG,
        )

        resp = dal._changes_table.scan()
        replaces = [i for i in resp["Items"] if i["feature_id"] == original.id and i["operation"] == "REPLACE"]
        assert len(replaces) == 1

    def test_preserves_visibility_change(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG, visibility="public")

        new_data: dict[str, Any] = {
            "geometry": {"type": "Point", "coordinates": [-116.0, 43.0]},
            "properties": {"name": "Same", "visibility": "restricted"},
        }
        replaced = dal.replace_feature(COLLECTION, original.id, new_data, original.etag, ORG)
        assert replaced.visibility == "restricted"


# ======================================================================
# UPDATE (PATCH)
# ======================================================================


@pytest.mark.unit
class TestUpdateFeature:
    def test_merges_properties(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(
            COLLECTION,
            _point_feature(color="red", size=10),
            ORG,
        )

        patch: dict[str, Any] = {"properties": {"color": "blue", "shape": "circle"}}
        updated = dal.update_feature(COLLECTION, original.id, patch, original.etag, ORG)

        assert updated.properties["color"] == "blue"
        assert updated.properties["shape"] == "circle"
        assert updated.properties["size"] == 10  # preserved
        assert updated.properties["name"] == "Test Feature"  # preserved

    def test_removes_null_properties(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(
            COLLECTION,
            _point_feature(temp_field="delete-me"),
            ORG,
        )

        patch: dict[str, Any] = {"properties": {"temp_field": None}}
        updated = dal.update_feature(COLLECTION, original.id, patch, original.etag, ORG)

        assert "temp_field" not in updated.properties

    def test_updates_geometry(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG)

        patch: dict[str, Any] = {"geometry": {"type": "Point", "coordinates": [-118.0, 45.0]}}
        updated = dal.update_feature(COLLECTION, original.id, patch, original.etag, ORG)
        assert updated.geometry == {"type": "Point", "coordinates": [-118.0, 45.0]}
        assert updated.properties == original.properties  # unchanged

    def test_etag_changes(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG)
        updated = dal.update_feature(COLLECTION, original.id, {"properties": {"x": 1}}, original.etag, ORG)
        assert updated.etag != original.etag

    def test_etag_mismatch_raises(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG)

        with pytest.raises(ETagMismatchError):
            dal.update_feature(COLLECTION, original.id, {"properties": {"x": 1}}, "bad-etag", ORG)

    def test_not_found_raises(self, dal: FeatureDAL) -> None:
        with pytest.raises(FeatureNotFoundError):
            dal.update_feature(COLLECTION, "missing", {"properties": {}}, "any-etag", ORG)

    def test_writes_change_log(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG)
        dal.update_feature(COLLECTION, original.id, {"properties": {"x": 1}}, original.etag, ORG)

        resp = dal._changes_table.scan()
        updates = [i for i in resp["Items"] if i["feature_id"] == original.id and i["operation"] == "UPDATE"]
        assert len(updates) == 1

    def test_updates_visibility_via_patch(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG, visibility="public")

        patch: dict[str, Any] = {"properties": {"visibility": "members"}}
        updated = dal.update_feature(COLLECTION, original.id, patch, original.etag, ORG)
        assert updated.visibility == "members"

    def test_ignores_organization_in_patch(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG)

        patch: dict[str, Any] = {"properties": {"organization": "evil-org"}}
        updated = dal.update_feature(COLLECTION, original.id, patch, original.etag, ORG)
        assert updated.organization == ORG
        assert "organization" not in updated.properties


# ======================================================================
# DELETE
# ======================================================================


@pytest.mark.unit
class TestDeleteFeature:
    def test_soft_deletes(self, dal: FeatureDAL) -> None:
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        dal.delete_feature(COLLECTION, created.id, created.etag, ORG)

        with pytest.raises(FeatureNotFoundError):
            dal.get_feature(COLLECTION, created.id, ORG)

    def test_deleted_excluded_from_query(self, dal: FeatureDAL) -> None:
        col = "delete-query"
        f1 = dal.create_feature(col, _point_feature(), ORG)
        f2 = dal.create_feature(col, _point_feature(), ORG)
        dal.delete_feature(col, f1.id, f1.etag, ORG)

        result = dal.query_features(col, ORG, limit=10)
        ids = [f.id for f in result.features]
        assert f1.id not in ids
        assert f2.id in ids

    def test_etag_mismatch_raises(self, dal: FeatureDAL) -> None:
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)

        with pytest.raises(ETagMismatchError):
            dal.delete_feature(COLLECTION, created.id, "wrong-etag", ORG)

    def test_not_found_raises(self, dal: FeatureDAL) -> None:
        with pytest.raises(FeatureNotFoundError):
            dal.delete_feature(COLLECTION, "nonexistent", "any-etag", ORG)

    def test_double_delete_raises(self, dal: FeatureDAL) -> None:
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        dal.delete_feature(COLLECTION, created.id, created.etag, ORG)

        with pytest.raises(FeatureNotFoundError):
            dal.delete_feature(COLLECTION, created.id, created.etag, ORG)

    def test_writes_change_log(self, dal: FeatureDAL) -> None:
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        dal.delete_feature(COLLECTION, created.id, created.etag, ORG)

        resp = dal._changes_table.scan()
        deletes = [i for i in resp["Items"] if i["feature_id"] == created.id and i["operation"] == "DELETE"]
        assert len(deletes) == 1


# ======================================================================
# GeoJSON serialization
# ======================================================================


@pytest.mark.unit
class TestGeoJsonSerialization:
    def test_to_geojson(self, dal: FeatureDAL) -> None:
        created = dal.create_feature(COLLECTION, _point_feature(color="red"), ORG)
        geojson = created.to_geojson()

        assert geojson["type"] == "Feature"
        assert geojson["id"] == created.id
        assert geojson["geometry"]["type"] == "Point"
        assert geojson["properties"]["color"] == "red"
        # Server-managed fields injected
        assert geojson["properties"]["organization"] == ORG
        assert geojson["properties"]["visibility"] == "public"

    def test_roundtrip_through_dynamodb(self, dal: FeatureDAL) -> None:
        """Feature survives write→read→GeoJSON conversion."""
        data = {
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-116, 43], [-115, 43], [-115, 44], [-116, 44], [-116, 43]]],
            },
            "properties": {"name": "Test Polygon", "area_km2": 42.5},
        }
        created = dal.create_feature(COLLECTION, data, ORG)
        fetched = dal.get_feature(COLLECTION, created.id, ORG)
        geojson = fetched.to_geojson()

        assert geojson["geometry"]["type"] == "Polygon"
        # Decimals should be converted to native Python types
        assert geojson["properties"]["area_km2"] == 42.5
        assert isinstance(geojson["properties"]["area_km2"], float)


# ======================================================================
# Cursor pagination helpers
# ======================================================================


@pytest.mark.unit
class TestCursorPagination:
    def test_encode_decode_roundtrip(self) -> None:
        key = {"PK": "org1#COLLECTION#col1", "SK": "FEATURE#abc-123"}
        cursor = encode_cursor(key)
        decoded = decode_cursor(cursor)
        assert decoded == key

    def test_decode_invalid_returns_none(self) -> None:
        assert decode_cursor("not-valid-base64!!!") is None

    def test_decode_non_dict_returns_none(self) -> None:
        import base64
        import json

        b = base64.urlsafe_b64encode(json.dumps([1, 2, 3]).encode()).decode()
        assert decode_cursor(b) is None


# ======================================================================
# JSON Merge Patch
# ======================================================================


@pytest.mark.unit
class TestJsonMergePatch:
    def test_basic_merge(self) -> None:
        target = {"a": 1, "b": 2}
        patch = {"b": 3, "c": 4}
        assert _json_merge_patch(target, patch) == {"a": 1, "b": 3, "c": 4}

    def test_remove_key(self) -> None:
        target = {"a": 1, "b": 2, "c": 3}
        patch = {"b": None}
        assert _json_merge_patch(target, patch) == {"a": 1, "c": 3}

    def test_nested_merge(self) -> None:
        target = {"a": {"x": 1, "y": 2}, "b": 3}
        patch = {"a": {"y": 20, "z": 30}}
        result = _json_merge_patch(target, patch)
        assert result == {"a": {"x": 1, "y": 20, "z": 30}, "b": 3}

    def test_replace_dict_with_scalar(self) -> None:
        target = {"a": {"x": 1}}
        patch = {"a": "string"}
        assert _json_merge_patch(target, patch) == {"a": "string"}

    def test_remove_nonexistent_key(self) -> None:
        target = {"a": 1}
        patch = {"missing": None}
        assert _json_merge_patch(target, patch) == {"a": 1}


# ======================================================================
# ETag / conditional write behavior
# ======================================================================


@pytest.mark.unit
class TestETagBehavior:
    def test_etag_changes_on_replace(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG)
        replaced = dal.replace_feature(COLLECTION, original.id, _point_feature(), original.etag, ORG)
        assert replaced.etag != original.etag

    def test_etag_changes_on_update(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG)
        updated = dal.update_feature(COLLECTION, original.id, {"properties": {"x": 1}}, original.etag, ORG)
        assert updated.etag != original.etag

    def test_stale_etag_after_replace_rejected(self, dal: FeatureDAL) -> None:
        """Once a feature is replaced, the old ETag must fail."""
        original = dal.create_feature(COLLECTION, _point_feature(), ORG)
        dal.replace_feature(COLLECTION, original.id, _point_feature(), original.etag, ORG)

        with pytest.raises(ETagMismatchError):
            dal.replace_feature(COLLECTION, original.id, _point_feature(), original.etag, ORG)

    def test_stale_etag_after_update_rejected(self, dal: FeatureDAL) -> None:
        original = dal.create_feature(COLLECTION, _point_feature(), ORG)
        dal.update_feature(COLLECTION, original.id, {"properties": {"x": 1}}, original.etag, ORG)

        with pytest.raises(ETagMismatchError):
            dal.update_feature(COLLECTION, original.id, {"properties": {"y": 2}}, original.etag, ORG)
