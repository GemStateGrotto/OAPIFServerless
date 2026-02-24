"""Unit tests for JSON Schema generation (OGC API - Features Part 5).

Tests cover both returnable and receivable schema variants,
geometry type constraints, property schemas, and server-managed fields.
"""

from __future__ import annotations

import pytest

from oapif.models.collection import CollectionConfig, PropertySchema
from oapif.schema import generate_schema

pytestmark = pytest.mark.unit


class TestReturnableSchema:
    """Tests for returnable (GET response) schema generation."""

    def test_basic_structure(self, sample_collection_config: CollectionConfig) -> None:
        """Returnable schema has correct top-level structure."""
        schema = generate_schema(sample_collection_config)

        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert "Feature" in schema["title"]
        assert "type" in schema["properties"]
        assert "id" in schema["properties"]
        assert "geometry" in schema["properties"]
        assert "properties" in schema["properties"]

    def test_includes_id_as_readonly(self, sample_collection_config: CollectionConfig) -> None:
        """Returnable schema marks id as readOnly."""
        schema = generate_schema(sample_collection_config)
        id_schema = schema["properties"]["id"]
        assert id_schema["readOnly"] is True
        assert id_schema["type"] == "string"

    def test_id_is_required(self, sample_collection_config: CollectionConfig) -> None:
        """Returnable schema requires id."""
        schema = generate_schema(sample_collection_config)
        assert "id" in schema["required"]

    def test_geometry_has_ogc_role(self, sample_collection_config: CollectionConfig) -> None:
        """Geometry is annotated with x-ogc-role: primary-geometry."""
        schema = generate_schema(sample_collection_config)
        geom = schema["properties"]["geometry"]
        assert geom["x-ogc-role"] == "primary-geometry"

    def test_specific_geometry_type(self, sample_collection_config: CollectionConfig) -> None:
        """When geometry_type is set, schema constrains to that type."""
        schema = generate_schema(sample_collection_config)
        geom = schema["properties"]["geometry"]
        # sample config has geometry_type="Point"
        assert geom["properties"]["type"]["enum"] == ["Point"]

    def test_any_geometry_type(self) -> None:
        """When geometry_type is None, schema allows any GeoJSON geometry."""
        config = CollectionConfig(
            collection_id="any",
            title="Any Geometry",
            geometry_type=None,
        )
        schema = generate_schema(config)
        geom = schema["properties"]["geometry"]
        assert "oneOf" in geom

    def test_includes_organization_readonly(self, sample_collection_config: CollectionConfig) -> None:
        """Returnable schema includes organization as readOnly."""
        schema = generate_schema(sample_collection_config)
        props = schema["properties"]["properties"]["properties"]
        assert "organization" in props
        assert props["organization"]["readOnly"] is True

    def test_includes_visibility_enum(self, sample_collection_config: CollectionConfig) -> None:
        """Returnable schema includes visibility with enum values."""
        schema = generate_schema(sample_collection_config)
        props = schema["properties"]["properties"]["properties"]
        assert "visibility" in props
        assert props["visibility"]["enum"] == ["public", "members", "restricted"]

    def test_includes_user_properties(self, sample_collection_config: CollectionConfig) -> None:
        """Returnable schema includes user-defined properties."""
        schema = generate_schema(sample_collection_config)
        props = schema["properties"]["properties"]["properties"]
        assert "name" in props
        assert props["name"]["type"] == "string"
        assert "depth_m" in props
        assert props["depth_m"]["type"] == "number"
        assert props["depth_m"]["minimum"] == 0.0

    def test_required_properties(self, sample_collection_config: CollectionConfig) -> None:
        """Returnable schema includes required properties plus server fields."""
        schema = generate_schema(sample_collection_config)
        required = schema["properties"]["properties"]["required"]
        assert "name" in required
        assert "organization" in required
        assert "visibility" in required

    def test_property_enum(self, sample_collection_config: CollectionConfig) -> None:
        """Property with enum values includes them in schema."""
        schema = generate_schema(sample_collection_config)
        props = schema["properties"]["properties"]["properties"]
        assert props["status"]["enum"] == ["active", "closed", "unknown"]

    def test_property_format(self, sample_collection_config: CollectionConfig) -> None:
        """Property with format includes it in schema."""
        schema = generate_schema(sample_collection_config)
        props = schema["properties"]["properties"]["properties"]
        assert props["survey_date"]["format"] == "date"


class TestReceivableSchema:
    """Tests for receivable (POST/PUT request body) schema generation."""

    def test_no_id_field(self, sample_collection_config: CollectionConfig) -> None:
        """Receivable schema does not include id (server-generated)."""
        schema = generate_schema(sample_collection_config, receivable=True)
        assert "id" not in schema["properties"]

    def test_id_not_required(self, sample_collection_config: CollectionConfig) -> None:
        """Receivable schema does not require id."""
        schema = generate_schema(sample_collection_config, receivable=True)
        assert "id" not in schema["required"]

    def test_no_organization_field(self, sample_collection_config: CollectionConfig) -> None:
        """Receivable schema omits organization (server-populated)."""
        schema = generate_schema(sample_collection_config, receivable=True)
        props = schema["properties"]["properties"]["properties"]
        assert "organization" not in props

    def test_visibility_is_settable(self, sample_collection_config: CollectionConfig) -> None:
        """Receivable schema includes visibility (clients can set it)."""
        schema = generate_schema(sample_collection_config, receivable=True)
        props = schema["properties"]["properties"]["properties"]
        assert "visibility" in props
        assert props["visibility"]["enum"] == ["public", "members", "restricted"]

    def test_required_only_user_properties(self, sample_collection_config: CollectionConfig) -> None:
        """Receivable schema only requires user-defined properties."""
        schema = generate_schema(sample_collection_config, receivable=True)
        props_schema = schema["properties"]["properties"]
        required = props_schema.get("required", [])
        assert "name" in required
        assert "organization" not in required
        assert "visibility" not in required

    def test_feature_required_fields(self, sample_collection_config: CollectionConfig) -> None:
        """Receivable schema requires type, geometry, properties at top level."""
        schema = generate_schema(sample_collection_config, receivable=True)
        assert "type" in schema["required"]
        assert "geometry" in schema["required"]
        assert "properties" in schema["required"]

    def test_includes_user_properties(self, sample_collection_config: CollectionConfig) -> None:
        """Receivable schema includes user-defined properties."""
        schema = generate_schema(sample_collection_config, receivable=True)
        props = schema["properties"]["properties"]["properties"]
        assert "name" in props
        assert "depth_m" in props


class TestSchemaEdgeCases:
    """Edge cases for schema generation."""

    def test_empty_properties_schema(self) -> None:
        """Collection with no custom properties produces valid schema."""
        config = CollectionConfig(
            collection_id="empty",
            title="Empty",
        )
        schema = generate_schema(config)
        assert schema["type"] == "object"
        # Should still have organization and visibility in returnables
        props = schema["properties"]["properties"]["properties"]
        assert "organization" in props
        assert "visibility" in props

    def test_empty_visibility_values(self) -> None:
        """Collection with empty visibility_values omits enum."""
        config = CollectionConfig(
            collection_id="no-vis",
            title="No Visibility Enum",
            visibility_values=[],
        )
        schema = generate_schema(config)
        vis = schema["properties"]["properties"]["properties"]["visibility"]
        assert "enum" not in vis

    def test_all_geometry_types(self) -> None:
        """Each supported geometry type produces a valid schema."""
        for geom_type in ["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"]:
            config = CollectionConfig(
                collection_id=f"test-{geom_type.lower()}",
                title=f"Test {geom_type}",
                geometry_type=geom_type,
            )
            schema = generate_schema(config)
            geom = schema["properties"]["geometry"]
            assert geom["properties"]["type"]["enum"] == [geom_type]
            assert geom["x-ogc-role"] == "primary-geometry"

    def test_schema_id_contains_collection_id(self) -> None:
        """Schema $id includes the collection ID."""
        config = CollectionConfig(collection_id="my-collection", title="Test")
        schema = generate_schema(config)
        assert "my-collection" in schema["$id"]

    def test_no_required_user_properties(self) -> None:
        """Collection with no required properties still works."""
        config = CollectionConfig(
            collection_id="optional",
            title="Optional Props",
            properties_schema={
                "note": PropertySchema(type="string"),
            },
            required_properties=[],
        )
        receivable_schema = generate_schema(config, receivable=True)
        props_schema = receivable_schema["properties"]["properties"]
        # No required properties from the user side
        assert "required" not in props_schema or props_schema.get("required") == []
