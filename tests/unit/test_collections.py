"""Unit tests for CollectionDAL — collection configuration CRUD.

Uses moto-mocked DynamoDB (no Docker required).
"""

from __future__ import annotations

import pytest

from oapif.dal.collections import CollectionDAL
from oapif.dal.exceptions import CollectionNotFoundError
from oapif.models.collection import (
    CollectionConfig,
    CollectionExtent,
    PropertySchema,
    SpatialExtent,
    TemporalExtent,
)

pytestmark = pytest.mark.unit


class TestCollectionDALGetCollection:
    """Tests for CollectionDAL.get_collection."""

    def test_get_existing_collection(
        self,
        collection_dal: CollectionDAL,
        sample_collection_config: CollectionConfig,
    ) -> None:
        """Retrieved collection matches what was stored."""
        collection_dal.put_collection(sample_collection_config)
        result = collection_dal.get_collection("caves")

        assert result.collection_id == "caves"
        assert result.title == "Caves"
        assert result.description == "Cave survey data"
        assert result.geometry_type == "Point"
        assert "name" in result.properties_schema
        assert result.properties_schema["name"].type == "string"
        assert result.required_properties == ["name"]
        assert result.visibility_values == ["public", "members", "restricted"]

    def test_get_nonexistent_collection(self, collection_dal: CollectionDAL) -> None:
        """CollectionNotFoundError is raised for missing collections."""
        with pytest.raises(CollectionNotFoundError) as exc_info:
            collection_dal.get_collection("nonexistent")
        assert "nonexistent" in str(exc_info.value)

    def test_get_preserves_extent(
        self,
        collection_dal: CollectionDAL,
        sample_collection_config: CollectionConfig,
    ) -> None:
        """Spatial and temporal extents survive round-trip."""
        collection_dal.put_collection(sample_collection_config)
        result = collection_dal.get_collection("caves")

        assert result.extent.spatial.bbox == [[-117.0, 42.0, -111.0, 49.0]]
        assert result.extent.temporal.interval == [["2020-01-01T00:00:00Z", None]]

    def test_get_preserves_organizations(
        self,
        collection_dal: CollectionDAL,
        sample_collection_config: CollectionConfig,
    ) -> None:
        """Organization access config survives round-trip."""
        collection_dal.put_collection(sample_collection_config)
        result = collection_dal.get_collection("caves")

        assert "GemStateGrotto" in result.organizations
        org = result.organizations["GemStateGrotto"]
        assert org.cognito_group == "org:GemStateGrotto"
        assert org.access_groups["members"] == "GemStateGrotto:members"
        assert org.access_groups["restricted"] == "GemStateGrotto:restricted"

    def test_get_preserves_property_schema_details(
        self,
        collection_dal: CollectionDAL,
        sample_collection_config: CollectionConfig,
    ) -> None:
        """Property schema details (enum, format, min) survive round-trip."""
        collection_dal.put_collection(sample_collection_config)
        result = collection_dal.get_collection("caves")

        depth = result.properties_schema["depth_m"]
        assert depth.type == "number"
        assert depth.min_value == 0.0

        survey_date = result.properties_schema["survey_date"]
        assert survey_date.format == "date"

        status = result.properties_schema["status"]
        assert status.enum == ["active", "closed", "unknown"]


class TestCollectionDALListCollections:
    """Tests for CollectionDAL.list_collections."""

    def test_list_empty(self, collection_dal: CollectionDAL) -> None:
        """Empty config table returns empty list."""
        result = collection_dal.list_collections()
        assert result == []

    def test_list_multiple_collections(self, collection_dal: CollectionDAL) -> None:
        """Multiple collections are returned sorted by collection_id."""
        configs = [
            CollectionConfig(collection_id="zebra", title="Zebra"),
            CollectionConfig(collection_id="alpha", title="Alpha"),
            CollectionConfig(collection_id="middle", title="Middle"),
        ]
        for config in configs:
            collection_dal.put_collection(config)

        result = collection_dal.list_collections()
        assert len(result) == 3
        assert [c.collection_id for c in result] == ["alpha", "middle", "zebra"]

    def test_list_returns_full_config(
        self,
        collection_dal: CollectionDAL,
        sample_collection_config: CollectionConfig,
    ) -> None:
        """Listed collections contain full configuration data."""
        collection_dal.put_collection(sample_collection_config)
        result = collection_dal.list_collections()

        assert len(result) == 1
        assert result[0].title == "Caves"
        assert "name" in result[0].properties_schema


class TestCollectionDALPutCollection:
    """Tests for CollectionDAL.put_collection."""

    def test_create_minimal_collection(self, collection_dal: CollectionDAL) -> None:
        """Minimal collection with just id and title can be stored."""
        config = CollectionConfig(collection_id="minimal", title="Minimal")
        result = collection_dal.put_collection(config)

        assert result.collection_id == "minimal"
        retrieved = collection_dal.get_collection("minimal")
        assert retrieved.title == "Minimal"
        assert retrieved.visibility_values == ["public", "members", "restricted"]

    def test_update_existing_collection(
        self,
        collection_dal: CollectionDAL,
        sample_collection_config: CollectionConfig,
    ) -> None:
        """Putting a collection with an existing ID replaces it."""
        collection_dal.put_collection(sample_collection_config)

        updated = CollectionConfig(
            collection_id="caves",
            title="Updated Caves",
            description="Updated description",
        )
        collection_dal.put_collection(updated)

        result = collection_dal.get_collection("caves")
        assert result.title == "Updated Caves"
        assert result.description == "Updated description"
        # Schema should be empty since we replaced entirely
        assert result.properties_schema == {}

    def test_put_collection_with_no_geometry_type(self, collection_dal: CollectionDAL) -> None:
        """Collection with geometry_type=None allows any geometry."""
        config = CollectionConfig(
            collection_id="any-geom",
            title="Any Geometry",
            geometry_type=None,
        )
        collection_dal.put_collection(config)
        result = collection_dal.get_collection("any-geom")
        assert result.geometry_type is None


class TestCollectionDALDeleteCollection:
    """Tests for CollectionDAL.delete_collection."""

    def test_delete_existing_collection(
        self,
        collection_dal: CollectionDAL,
        sample_collection_config: CollectionConfig,
    ) -> None:
        """Deleting removes the collection from the config table."""
        collection_dal.put_collection(sample_collection_config)
        collection_dal.delete_collection("caves")

        with pytest.raises(CollectionNotFoundError):
            collection_dal.get_collection("caves")

    def test_delete_nonexistent_collection(self, collection_dal: CollectionDAL) -> None:
        """Deleting a non-existent collection raises CollectionNotFoundError."""
        with pytest.raises(CollectionNotFoundError):
            collection_dal.delete_collection("nonexistent")


class TestCollectionConfigModel:
    """Tests for CollectionConfig model serialization."""

    def test_dynamodb_round_trip(self, sample_collection_config: CollectionConfig) -> None:
        """CollectionConfig survives DynamoDB serialization round-trip."""
        item = sample_collection_config.to_dynamodb_item()
        restored = CollectionConfig.from_dynamodb_item(item)

        assert restored.collection_id == sample_collection_config.collection_id
        assert restored.title == sample_collection_config.title
        assert restored.description == sample_collection_config.description
        assert restored.geometry_type == sample_collection_config.geometry_type
        assert restored.visibility_values == sample_collection_config.visibility_values
        assert restored.required_properties == sample_collection_config.required_properties

    def test_make_pk(self) -> None:
        """Partition key follows expected format."""
        assert CollectionConfig.make_pk("caves") == "COLLECTION#caves"

    def test_make_sk(self) -> None:
        """Sort key is always CONFIG."""
        assert CollectionConfig.make_sk() == "CONFIG"

    def test_to_oapif_metadata(self, sample_collection_config: CollectionConfig) -> None:
        """OGC API metadata includes required fields and links."""
        meta = sample_collection_config.to_oapif_metadata(base_url="https://api.example.com")

        assert meta["id"] == "caves"
        assert meta["title"] == "Caves"
        assert meta["itemType"] == "feature"
        assert "extent" in meta

        links = meta["links"]
        assert any(link["rel"] == "self" for link in links)
        assert any(link["rel"] == "items" for link in links)
        assert any(link["rel"] == "describedby" for link in links)

    def test_to_oapif_metadata_no_base_url(self, sample_collection_config: CollectionConfig) -> None:
        """Metadata without base_url has no auto-generated links but keeps custom ones."""
        meta = sample_collection_config.to_oapif_metadata()
        # No base_url, so only custom links (which are empty in sample)
        assert meta["links"] == []


class TestPropertySchema:
    """Tests for PropertySchema model."""

    def test_to_dict_minimal(self) -> None:
        """Minimal PropertySchema serializes to just type."""
        schema = PropertySchema(type="string")
        assert schema.to_dict() == {"type": "string"}

    def test_to_dict_full(self) -> None:
        """Full PropertySchema includes all fields."""
        schema = PropertySchema(
            type="number",
            description="A number",
            min_value=0.0,
            max_value=100.0,
            format="double",
        )
        d = schema.to_dict()
        assert d["type"] == "number"
        assert d["description"] == "A number"
        assert d["minimum"] == 0.0
        assert d["maximum"] == 100.0
        assert d["format"] == "double"

    def test_from_dict_round_trip(self) -> None:
        """PropertySchema survives dict round-trip."""
        original = PropertySchema(
            type="string",
            description="Test",
            enum=["a", "b"],
            min_length=1,
            max_length=255,
        )
        restored = PropertySchema.from_dict(original.to_dict())
        assert restored.type == original.type
        assert restored.enum == original.enum
        assert restored.min_length == original.min_length
        assert restored.max_length == original.max_length


class TestExtentModels:
    """Tests for extent sub-models."""

    def test_spatial_extent_defaults(self) -> None:
        """Default spatial extent covers the whole world."""
        extent = SpatialExtent()
        assert extent.bbox == [[-180.0, -90.0, 180.0, 90.0]]
        assert "CRS84" in extent.crs

    def test_temporal_extent_defaults(self) -> None:
        """Default temporal extent is open-ended."""
        extent = TemporalExtent()
        assert extent.interval == [[None, None]]

    def test_collection_extent_round_trip(self) -> None:
        """CollectionExtent survives dict round-trip."""
        extent = CollectionExtent(
            spatial=SpatialExtent(bbox=[[-120.0, 40.0, -110.0, 50.0]]),
            temporal=TemporalExtent(interval=[["2020-01-01", "2025-12-31"]]),
        )
        d = extent.to_dict()
        restored = CollectionExtent.from_dict(d)
        assert restored.spatial.bbox == extent.spatial.bbox
        assert restored.temporal.interval == extent.temporal.interval
