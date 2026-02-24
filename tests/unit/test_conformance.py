"""Conformance validation tests — validate model outputs against OGC and GeoJSON schemas.

These tests catch structural conformance bugs *before* we have live HTTP
endpoints.  They validate:

1. Feature.to_geojson() output against RFC 7946 GeoJSON Feature schema
2. CollectionConfig.to_oapif_metadata() output against OGC collection schema
3. generate_schema() output is valid JSON Schema (meta-validation)
4. Sample feature data validates against our own generated schemas

This is an early pull-forward of Phase 13 conformance work.
"""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest

from oapif.models.collection import (
    CollectionConfig,
    CollectionExtent,
    OrgAccessConfig,
    PropertySchema,
    SpatialExtent,
    TemporalExtent,
)
from oapif.models.feature import Feature
from oapif.schema import generate_schema
from tests.schemas import (
    GEOJSON_FEATURE_SCHEMA,
    OGC_COLLECTION_SCHEMA,
    OGC_COLLECTIONS_SCHEMA,
    OGC_CONFORMANCE_SCHEMA,
    OGC_ITEMS_RESPONSE_SCHEMA,
    OGC_LANDING_PAGE_SCHEMA,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate(instance: Any, schema: dict[str, Any]) -> None:
    """Validate a JSON instance against a schema, raising on failure."""
    jsonschema.validate(instance, schema)


def _make_feature(**overrides: Any) -> Feature:
    """Create a Feature with sensible defaults, overridable via kwargs."""
    defaults: dict[str, Any] = {
        "id": "f-001",
        "collection_id": "caves",
        "organization": "GemStateGrotto",
        "visibility": "public",
        "geometry": {"type": "Point", "coordinates": [-114.74, 43.60]},
        "properties": {"name": "Crystal Ice Cave", "depth_m": 12.5},
        "etag": "abc123",
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
        "deleted": False,
    }
    defaults.update(overrides)
    return Feature(**defaults)


def _caves_config() -> CollectionConfig:
    """Standard caves collection config for conformance tests."""
    return CollectionConfig(
        collection_id="caves",
        title="Caves",
        description="Cave survey data for Idaho",
        extent=CollectionExtent(
            spatial=SpatialExtent(bbox=[[-117.0, 42.0, -111.0, 49.0]]),
            temporal=TemporalExtent(interval=[["2020-01-01T00:00:00Z", None]]),
        ),
        properties_schema={
            "name": PropertySchema(type="string", description="Cave name"),
            "depth_m": PropertySchema(type="number", description="Depth in meters", min_value=0.0),
            "status": PropertySchema(type="string", enum=["active", "closed", "unknown"]),
        },
        required_properties=["name"],
        visibility_values=["public", "members", "restricted"],
        geometry_type="Point",
        organizations={
            "GemStateGrotto": OrgAccessConfig(
                cognito_group="org:GemStateGrotto",
                access_groups={"members": "GemStateGrotto:members", "restricted": "GemStateGrotto:restricted"},
            ),
        },
    )


# ===================================================================
# 1. GeoJSON Feature conformance (RFC 7946)
# ===================================================================


class TestGeoJSONFeatureConformance:
    """Validate Feature.to_geojson() against RFC 7946."""

    def test_point_feature(self) -> None:
        geojson = _make_feature().to_geojson()
        _validate(geojson, GEOJSON_FEATURE_SCHEMA)

    def test_linestring_feature(self) -> None:
        geojson = _make_feature(
            geometry={"type": "LineString", "coordinates": [[-114.0, 43.0], [-115.0, 44.0]]}
        ).to_geojson()
        _validate(geojson, GEOJSON_FEATURE_SCHEMA)

    def test_polygon_feature(self) -> None:
        geojson = _make_feature(
            geometry={
                "type": "Polygon",
                "coordinates": [[[-114.0, 43.0], [-115.0, 43.0], [-115.0, 44.0], [-114.0, 43.0]]],
            }
        ).to_geojson()
        _validate(geojson, GEOJSON_FEATURE_SCHEMA)

    def test_multipoint_feature(self) -> None:
        geojson = _make_feature(
            geometry={"type": "MultiPoint", "coordinates": [[-114.0, 43.0], [-115.0, 44.0]]}
        ).to_geojson()
        _validate(geojson, GEOJSON_FEATURE_SCHEMA)

    def test_multipolygon_feature(self) -> None:
        geojson = _make_feature(
            geometry={
                "type": "MultiPolygon",
                "coordinates": [
                    [[[-114.0, 43.0], [-115.0, 43.0], [-115.0, 44.0], [-114.0, 43.0]]],
                ],
            }
        ).to_geojson()
        _validate(geojson, GEOJSON_FEATURE_SCHEMA)

    def test_null_geometry_feature(self) -> None:
        """RFC 7946 §3.2: geometry MAY be null."""
        geojson = _make_feature(geometry=None).to_geojson()
        _validate(geojson, GEOJSON_FEATURE_SCHEMA)

    def test_feature_has_required_keys(self) -> None:
        geojson = _make_feature().to_geojson()
        assert "type" in geojson
        assert "geometry" in geojson
        assert "properties" in geojson
        assert geojson["type"] == "Feature"

    def test_feature_id_is_string(self) -> None:
        geojson = _make_feature().to_geojson()
        assert isinstance(geojson["id"], str)

    def test_properties_include_organization(self) -> None:
        """Organization must appear in GeoJSON properties."""
        geojson = _make_feature().to_geojson()
        assert "organization" in geojson["properties"]
        assert geojson["properties"]["organization"] == "GemStateGrotto"

    def test_properties_include_visibility(self) -> None:
        """Visibility must appear in GeoJSON properties."""
        geojson = _make_feature().to_geojson()
        assert "visibility" in geojson["properties"]
        assert geojson["properties"]["visibility"] == "public"


# ===================================================================
# 2. OGC Collection metadata conformance (OGC 17-069r4 §7.14)
# ===================================================================


class TestOGCCollectionMetadataConformance:
    """Validate CollectionConfig.to_oapif_metadata() against OGC schema."""

    def test_collection_with_links(self) -> None:
        config = _caves_config()
        meta = config.to_oapif_metadata(base_url="https://api.example.com")
        _validate(meta, OGC_COLLECTION_SCHEMA)

    def test_collection_has_required_fields(self) -> None:
        config = _caves_config()
        meta = config.to_oapif_metadata(base_url="https://api.example.com")
        assert "id" in meta
        assert "links" in meta
        assert isinstance(meta["links"], list)
        assert len(meta["links"]) > 0

    def test_collection_links_have_self(self) -> None:
        config = _caves_config()
        meta = config.to_oapif_metadata(base_url="https://api.example.com")
        rels = [link["rel"] for link in meta["links"]]
        assert "self" in rels

    def test_collection_links_have_items(self) -> None:
        config = _caves_config()
        meta = config.to_oapif_metadata(base_url="https://api.example.com")
        rels = [link["rel"] for link in meta["links"]]
        assert "items" in rels

    def test_collection_extent_structure(self) -> None:
        config = _caves_config()
        meta = config.to_oapif_metadata(base_url="https://api.example.com")
        assert "extent" in meta
        assert "spatial" in meta["extent"]
        assert "temporal" in meta["extent"]
        assert "bbox" in meta["extent"]["spatial"]

    def test_minimal_collection(self) -> None:
        """Even a minimal collection produces valid OGC metadata."""
        config = CollectionConfig(collection_id="minimal", title="Minimal")
        meta = config.to_oapif_metadata(base_url="https://api.example.com")
        _validate(meta, OGC_COLLECTION_SCHEMA)

    def test_collections_list_structure(self) -> None:
        """Validate that a list of collections matches OGC schema."""
        configs = [
            _caves_config(),
            CollectionConfig(collection_id="springs", title="Springs"),
        ]
        collections_response = {
            "links": [{"href": "https://api.example.com/collections", "rel": "self"}],
            "collections": [c.to_oapif_metadata(base_url="https://api.example.com") for c in configs],
        }
        _validate(collections_response, OGC_COLLECTIONS_SCHEMA)


# ===================================================================
# 3. Generated JSON Schema meta-validation (Part 5)
# ===================================================================


class TestGeneratedSchemaMetaValidation:
    """Validate that generate_schema() produces valid JSON Schema 2020-12."""

    def test_returnable_schema_is_valid_json_schema(self) -> None:
        """Returnable schema must be a valid JSON Schema document."""
        config = _caves_config()
        schema = generate_schema(config)
        # Validate the schema itself is valid JSON Schema
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_receivable_schema_is_valid_json_schema(self) -> None:
        """Receivable schema must be a valid JSON Schema document."""
        config = _caves_config()
        schema = generate_schema(config, receivable=True)
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_minimal_collection_schema_is_valid(self) -> None:
        """Schema from minimal config is valid JSON Schema."""
        config = CollectionConfig(collection_id="empty", title="Empty")
        schema = generate_schema(config)
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_any_geometry_schema_is_valid(self) -> None:
        """Schema with geometry_type=None is valid JSON Schema."""
        config = CollectionConfig(collection_id="any-geom", title="Any Geometry")
        schema = generate_schema(config)
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_all_geometry_types_produce_valid_schemas(self) -> None:
        for geom_type in ["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"]:
            config = CollectionConfig(
                collection_id=f"test-{geom_type.lower()}",
                title=f"Test {geom_type}",
                geometry_type=geom_type,
            )
            schema = generate_schema(config)
            jsonschema.Draft202012Validator.check_schema(schema)


# ===================================================================
# 4. Feature data validates against generated schema
# ===================================================================


class TestFeatureAgainstGeneratedSchema:
    """Validate that Feature.to_geojson() conforms to the generated schema."""

    def test_valid_feature_passes_returnable_schema(self) -> None:
        """A well-formed feature validates against the returnable schema."""
        config = _caves_config()
        schema = generate_schema(config)
        feature = _make_feature(properties={"name": "Crystal Ice Cave", "depth_m": 12.5, "status": "active"})
        geojson = feature.to_geojson()
        _validate(geojson, schema)

    def test_valid_feature_missing_optional_property(self) -> None:
        """A feature missing optional properties still validates."""
        config = _caves_config()
        schema = generate_schema(config)
        feature = _make_feature(properties={"name": "Minimal Cave"})
        geojson = feature.to_geojson()
        _validate(geojson, schema)

    def test_feature_missing_required_property_fails(self) -> None:
        """A feature missing a required property fails validation."""
        config = _caves_config()
        schema = generate_schema(config)
        # Missing "name" which is required
        feature = _make_feature(properties={"depth_m": 10.0})
        geojson = feature.to_geojson()
        with pytest.raises(jsonschema.ValidationError):
            _validate(geojson, schema)

    def test_feature_invalid_enum_fails(self) -> None:
        """A feature with an invalid enum value fails validation."""
        config = _caves_config()
        schema = generate_schema(config)
        feature = _make_feature(properties={"name": "Bad Cave", "status": "nonexistent_status"})
        geojson = feature.to_geojson()
        with pytest.raises(jsonschema.ValidationError):
            _validate(geojson, schema)

    def test_feature_invalid_visibility_fails(self) -> None:
        """A feature with an invalid visibility value fails validation."""
        config = _caves_config()
        schema = generate_schema(config)
        feature = _make_feature(
            visibility="top-secret",
            properties={"name": "Secret Cave"},
        )
        geojson = feature.to_geojson()
        with pytest.raises(jsonschema.ValidationError):
            _validate(geojson, schema)

    def test_receivable_feature_valid(self) -> None:
        """A receivable feature (no id, no organization) validates."""
        config = _caves_config()
        schema = generate_schema(config, receivable=True)
        receivable = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-114.74, 43.60]},
            "properties": {"name": "New Cave", "visibility": "public"},
        }
        _validate(receivable, schema)

    def test_receivable_feature_missing_required_fails(self) -> None:
        """A receivable feature missing required properties fails."""
        config = _caves_config()
        schema = generate_schema(config, receivable=True)
        receivable = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-114.74, 43.60]},
            "properties": {"depth_m": 5.0},  # missing "name"
        }
        with pytest.raises(jsonschema.ValidationError):
            _validate(receivable, schema)


# ===================================================================
# 5. OGC response structure templates (for Phase 3 readiness)
# ===================================================================


class TestOGCResponseStructures:
    """Validate template response structures against OGC schemas.

    These test what our future endpoint responses will look like,
    ensuring the shape is correct before we build the handlers.
    """

    def test_landing_page_structure(self) -> None:
        """Landing page with required links validates."""
        landing = {
            "title": "OAPIFServerless",
            "description": "OGC API - Features backed by DynamoDB",
            "links": [
                {"href": "https://api.example.com/", "rel": "self", "type": "application/json"},
                {
                    "href": "https://api.example.com/api",
                    "rel": "service-desc",
                    "type": "application/vnd.oai.openapi+json;version=3.0",
                },
                {"href": "https://api.example.com/conformance", "rel": "conformance", "type": "application/json"},
                {"href": "https://api.example.com/collections", "rel": "data", "type": "application/json"},
            ],
        }
        _validate(landing, OGC_LANDING_PAGE_SCHEMA)

    def test_conformance_structure(self) -> None:
        """Conformance declaration validates."""
        conformance = {
            "conformsTo": [
                "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
                "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
                "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
            ],
        }
        _validate(conformance, OGC_CONFORMANCE_SCHEMA)

    def test_items_response_structure(self) -> None:
        """Feature collection response with paging metadata validates."""
        features = [_make_feature(id=f"f-{i}", properties={"name": f"Cave {i}"}).to_geojson() for i in range(3)]
        items_response = {
            "type": "FeatureCollection",
            "features": features,
            "links": [
                {"href": "https://api.example.com/collections/caves/items", "rel": "self"},
                {"href": "https://api.example.com/collections/caves/items?cursor=abc", "rel": "next"},
            ],
            "timeStamp": "2025-01-01T00:00:00Z",
            "numberMatched": 100,
            "numberReturned": 3,
        }
        _validate(items_response, OGC_ITEMS_RESPONSE_SCHEMA)

    def test_single_feature_response(self) -> None:
        """Single feature GET response (just GeoJSON) validates."""
        geojson = _make_feature().to_geojson()
        _validate(geojson, GEOJSON_FEATURE_SCHEMA)

    def test_items_response_empty(self) -> None:
        """Empty feature collection validates."""
        items_response = {
            "type": "FeatureCollection",
            "features": [],
            "links": [
                {"href": "https://api.example.com/collections/caves/items", "rel": "self"},
            ],
            "timeStamp": "2025-01-01T00:00:00Z",
            "numberMatched": 0,
            "numberReturned": 0,
        }
        _validate(items_response, OGC_ITEMS_RESPONSE_SCHEMA)
