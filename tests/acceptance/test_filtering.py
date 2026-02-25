"""Filtering tests.

Covers TODO section 9 (Filtering) — bbox, datetime, property filters.
"""

from __future__ import annotations

import httpx
import pytest

from tests.acceptance.conftest import COLLECTION_ID, create_feature

pytestmark = pytest.mark.acceptance


class TestBBoxFilter:
    """Bounding box spatial filter."""

    @pytest.fixture(autouse=True)
    def _seed_bbox_features(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Create features at known locations for bbox tests."""
        self._tag = f"{test_run_id}-bbox"
        # Feature A: inside target bbox
        create_feature(
            editor_client,
            test_run_id,
            name="BBox-Inside",
            lon=-114.0,
            lat=44.0,
            extra_props={"bbox_tag": self._tag},
        )
        # Feature B: outside target bbox
        create_feature(
            editor_client,
            test_run_id,
            name="BBox-Outside",
            lon=-120.0,
            lat=48.0,
            extra_props={"bbox_tag": self._tag},
        )

    def test_bbox_returns_only_features_within(
        self,
        editor_client: httpx.Client,
    ) -> None:
        """Features outside the bbox are excluded."""
        # bbox that contains (-114, 44) but not (-120, 48)
        resp = editor_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"bbox": "-115,43,-113,45", "limit": "100"},
        )
        assert resp.status_code == 200
        features = resp.json()["features"]
        tagged = [f for f in features if f["properties"].get("bbox_tag") == self._tag]

        names = {f["properties"]["name"] for f in tagged}
        assert "BBox-Inside" in names
        assert "BBox-Outside" not in names


class TestPropertyFilter:
    """Property-based filtering via query parameters."""

    @pytest.fixture(autouse=True)
    def _seed_prop_features(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Create features with distinct status values."""
        self._tag = f"{test_run_id}-propfilter"
        for status in ("active", "closed"):
            create_feature(
                editor_client,
                test_run_id,
                name=f"PropFilter-{status}",
                status=status,
                extra_props={"prop_tag": self._tag},
            )

    def test_property_filter_narrows_results(
        self,
        editor_client: httpx.Client,
    ) -> None:
        """Filtering by status=active returns only active features."""
        resp = editor_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"status": "active", "limit": "100"},
        )
        assert resp.status_code == 200
        features = resp.json()["features"]
        tagged = [f for f in features if f["properties"].get("prop_tag") == self._tag]

        for f in tagged:
            assert f["properties"]["status"] == "active", (
                f"Expected only 'active' features, got: {f['properties']['status']}"
            )
