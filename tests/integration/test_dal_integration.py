"""Integration tests for the feature DAL against DynamoDB Local.

These tests require DynamoDB Local to be running (e.g. via docker-compose).
Each test uses a unique organization/collection to avoid cross-test pollution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from oapif.dal.exceptions import ETagMismatchError, FeatureNotFoundError

if TYPE_CHECKING:
    from oapif.dal.features import FeatureDAL

pytestmark = pytest.mark.integration


def _point_feature(lon: float = -116.0, lat: float = 43.0, **extra: Any) -> dict[str, Any]:
    return {
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": "Integration Test", **extra},
    }


class TestCRUDLifecycle:
    """Full create → get → replace → update → delete lifecycle."""

    def test_full_cycle(
        self,
        integration_dal: FeatureDAL,
        unique_org: str,
        unique_collection: str,
    ) -> None:
        dal = integration_dal
        org = unique_org
        col = unique_collection

        # CREATE
        created = dal.create_feature(col, _point_feature(color="red"), org)
        assert created.id
        assert created.etag
        assert created.properties["color"] == "red"

        # GET
        fetched = dal.get_feature(col, created.id, org)
        assert fetched.id == created.id
        assert fetched.etag == created.etag

        # REPLACE
        replaced = dal.replace_feature(
            col,
            created.id,
            {
                "geometry": {"type": "Point", "coordinates": [-117.0, 44.0]},
                "properties": {"name": "Replaced"},
            },
            fetched.etag,
            org,
        )
        assert replaced.etag != fetched.etag
        assert replaced.properties["name"] == "Replaced"
        assert replaced.geometry == {"type": "Point", "coordinates": [-117.0, 44.0]}

        # UPDATE (PATCH)
        updated = dal.update_feature(
            col,
            created.id,
            {"properties": {"status": "active"}},
            replaced.etag,
            org,
        )
        assert updated.properties["status"] == "active"
        assert updated.properties["name"] == "Replaced"  # preserved
        assert updated.etag != replaced.etag

        # DELETE
        dal.delete_feature(col, created.id, updated.etag, org)

        with pytest.raises(FeatureNotFoundError):
            dal.get_feature(col, created.id, org)


class TestQueryPagination:
    def test_paginates_correctly(
        self,
        integration_dal: FeatureDAL,
        unique_org: str,
        unique_collection: str,
    ) -> None:
        dal = integration_dal
        org = unique_org
        col = unique_collection

        # Create several features
        for i in range(7):
            dal.create_feature(col, _point_feature(index=i), org)

        all_ids: set[str] = set()
        cursor = None

        for _ in range(10):  # safety bound
            result = dal.query_features(col, org, limit=3, cursor=cursor)
            for f in result.features:
                all_ids.add(f.id)
            cursor = result.next_cursor
            if cursor is None:
                break

        assert len(all_ids) == 7


class TestOrganizationIsolation:
    def test_cross_org_invisible(
        self,
        integration_dal: FeatureDAL,
        unique_collection: str,
    ) -> None:
        dal = integration_dal
        col = unique_collection

        f_alpha = dal.create_feature(col, _point_feature(), "org-alpha")
        f_beta = dal.create_feature(col, _point_feature(), "org-beta")

        # org-alpha can't see org-beta's feature
        with pytest.raises(FeatureNotFoundError):
            dal.get_feature(col, f_beta.id, "org-alpha")

        # org-beta can't see org-alpha's feature
        with pytest.raises(FeatureNotFoundError):
            dal.get_feature(col, f_alpha.id, "org-beta")

        # Queries scoped
        alpha_result = dal.query_features(col, "org-alpha", limit=10)
        assert len(alpha_result.features) == 1
        assert alpha_result.features[0].id == f_alpha.id


class TestConditionalWrites:
    def test_optimistic_concurrency(
        self,
        integration_dal: FeatureDAL,
        unique_org: str,
        unique_collection: str,
    ) -> None:
        dal = integration_dal
        org = unique_org
        col = unique_collection

        created = dal.create_feature(col, _point_feature(), org)
        stale_etag = created.etag

        # First update succeeds
        updated = dal.update_feature(col, created.id, {"properties": {"v": 1}}, stale_etag, org)

        # Second update with stale etag fails
        with pytest.raises(ETagMismatchError):
            dal.update_feature(col, created.id, {"properties": {"v": 2}}, stale_etag, org)

        # Verify the first update persisted
        current = dal.get_feature(col, created.id, org)
        assert current.etag == updated.etag
        assert current.properties["v"] == 1


class TestBboxFilter:
    def test_spatial_filtering(
        self,
        integration_dal: FeatureDAL,
        unique_org: str,
        unique_collection: str,
    ) -> None:
        dal = integration_dal
        org = unique_org
        col = unique_collection

        dal.create_feature(col, _point_feature(lon=-116.0, lat=43.0), org)  # inside
        dal.create_feature(col, _point_feature(lon=-80.0, lat=35.0), org)  # outside
        dal.create_feature(col, _point_feature(lon=-116.5, lat=43.5), org)  # inside

        result = dal.query_features(col, org, limit=10, bbox=(-117.0, 42.0, -115.0, 44.0))
        assert len(result.features) == 2
