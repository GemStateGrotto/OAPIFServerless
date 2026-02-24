"""Integration tests for the CollectionDAL against DynamoDB Local.

These tests require DynamoDB Local to be running (e.g. via docker-compose).
Each test uses unique collection IDs to avoid cross-test pollution.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from oapif.dal.exceptions import CollectionNotFoundError
from oapif.models.collection import (
    CollectionConfig,
    CollectionExtent,
    OrgAccessConfig,
    PropertySchema,
    SpatialExtent,
    TemporalExtent,
)

if TYPE_CHECKING:
    from oapif.dal.collections import CollectionDAL

pytestmark = pytest.mark.integration


def _unique_id() -> str:
    return f"integ-{uuid.uuid4().hex[:8]}"


def _sample_config(collection_id: str | None = None) -> CollectionConfig:
    """Build a sample config with a unique or provided ID."""
    cid = collection_id or _unique_id()
    return CollectionConfig(
        collection_id=cid,
        title=f"Integration Test {cid}",
        description="Created by integration test",
        extent=CollectionExtent(
            spatial=SpatialExtent(bbox=[[-117.0, 42.0, -111.0, 49.0]]),
            temporal=TemporalExtent(interval=[["2020-01-01T00:00:00Z", None]]),
        ),
        properties_schema={
            "name": PropertySchema(type="string", description="Feature name"),
            "depth_m": PropertySchema(type="number", min_value=0.0),
        },
        required_properties=["name"],
        visibility_values=["public", "members", "restricted"],
        geometry_type="Point",
        organizations={
            "TestOrg": OrgAccessConfig(
                cognito_group="org:TestOrg",
                access_groups={"members": "TestOrg:members"},
            ),
        },
    )


class TestCollectionCRUDLifecycle:
    """Full create → get → update → delete lifecycle."""

    def test_full_cycle(self, integration_collection_dal: CollectionDAL) -> None:
        dal = integration_collection_dal
        cid = _unique_id()
        config = _sample_config(cid)

        # CREATE
        dal.put_collection(config)
        result = dal.get_collection(cid)
        assert result.collection_id == cid
        assert result.title == config.title
        assert result.geometry_type == "Point"
        assert "name" in result.properties_schema
        assert result.properties_schema["name"].type == "string"
        assert result.properties_schema["depth_m"].min_value == 0.0
        assert "TestOrg" in result.organizations

        # UPDATE (replace)
        updated_config = CollectionConfig(
            collection_id=cid,
            title="Updated Title",
            description="Updated description",
            geometry_type="Polygon",
        )
        dal.put_collection(updated_config)
        result = dal.get_collection(cid)
        assert result.title == "Updated Title"
        assert result.geometry_type == "Polygon"
        assert result.properties_schema == {}

        # DELETE
        dal.delete_collection(cid)
        with pytest.raises(CollectionNotFoundError):
            dal.get_collection(cid)

    def test_list_collections(self, integration_collection_dal: CollectionDAL) -> None:
        dal = integration_collection_dal

        # Create two collections with predictable IDs
        id_a = f"zzz-list-a-{uuid.uuid4().hex[:6]}"
        id_b = f"zzz-list-b-{uuid.uuid4().hex[:6]}"
        dal.put_collection(CollectionConfig(collection_id=id_a, title="A"))
        dal.put_collection(CollectionConfig(collection_id=id_b, title="B"))

        result = dal.list_collections()
        found_ids = [c.collection_id for c in result]
        assert id_a in found_ids
        assert id_b in found_ids

        # Clean up
        dal.delete_collection(id_a)
        dal.delete_collection(id_b)

    def test_get_nonexistent(self, integration_collection_dal: CollectionDAL) -> None:
        with pytest.raises(CollectionNotFoundError):
            integration_collection_dal.get_collection("does-not-exist-" + uuid.uuid4().hex[:8])

    def test_delete_nonexistent(self, integration_collection_dal: CollectionDAL) -> None:
        with pytest.raises(CollectionNotFoundError):
            integration_collection_dal.delete_collection("does-not-exist-" + uuid.uuid4().hex[:8])

    def test_extent_round_trip(self, integration_collection_dal: CollectionDAL) -> None:
        """Spatial and temporal extents survive DynamoDB Local round-trip."""
        dal = integration_collection_dal
        cid = _unique_id()
        config = _sample_config(cid)
        dal.put_collection(config)

        result = dal.get_collection(cid)
        assert result.extent.spatial.bbox == [[-117.0, 42.0, -111.0, 49.0]]
        assert result.extent.temporal.interval == [["2020-01-01T00:00:00Z", None]]

        dal.delete_collection(cid)

    def test_organizations_round_trip(self, integration_collection_dal: CollectionDAL) -> None:
        """Organization access config survives DynamoDB Local round-trip."""
        dal = integration_collection_dal
        cid = _unique_id()
        config = _sample_config(cid)
        dal.put_collection(config)

        result = dal.get_collection(cid)
        assert "TestOrg" in result.organizations
        org = result.organizations["TestOrg"]
        assert org.cognito_group == "org:TestOrg"
        assert org.access_groups["members"] == "TestOrg:members"

        dal.delete_collection(cid)
