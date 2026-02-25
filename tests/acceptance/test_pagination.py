"""Pagination tests.

Covers TODO section 8 (Pagination).
"""

from __future__ import annotations

import httpx
import pytest

from tests.acceptance.conftest import COLLECTION_ID, create_feature

pytestmark = pytest.mark.acceptance

# Number of features to seed for pagination tests
PAGINATION_SEED_COUNT = 5


class TestPagination:
    """Pagination through items endpoint."""

    @pytest.fixture(autouse=True)
    def _seed_features(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Seed enough features for pagination tests."""
        self._tag = f"{test_run_id}-pagination"
        for i in range(PAGINATION_SEED_COUNT):
            create_feature(
                editor_client,
                test_run_id,
                name=f"Page-{i}",
                lon=-114.75 + i * 0.01,
                extra_props={"page_tag": self._tag},
            )

    def test_limit_respected(self, editor_client: httpx.Client) -> None:
        """GET /items?limit=2 returns at most 2 features."""
        resp = editor_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"limit": "2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["features"]) <= 2

    def test_limit_produces_next_link(self, editor_client: httpx.Client) -> None:
        """When more features exist than limit, a 'next' link is present."""
        resp = editor_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"limit": "2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        rels = {link["rel"] for link in data.get("links", [])}
        assert "next" in rels, "Expected a 'next' link when limit < total features"

    def test_follow_next_link(self, editor_client: httpx.Client) -> None:
        """Following the 'next' link returns the next page of results."""
        resp = editor_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"limit": "2"},
        )
        assert resp.status_code == 200
        data = resp.json()

        next_url = None
        for link in data.get("links", []):
            if link["rel"] == "next":
                next_url = link["href"]
                break
        assert next_url is not None

        # Follow the next link (may be absolute URL)
        next_resp = editor_client.get(next_url)
        assert next_resp.status_code == 200
        next_data = next_resp.json()
        assert "features" in next_data
        assert len(next_data["features"]) > 0

    def test_paginate_no_duplicates(self, editor_client: httpx.Client) -> None:
        """Paginating until no 'next' link yields no duplicate feature IDs."""
        all_ids: list[str] = []
        url: str | None = f"/collections/{COLLECTION_ID}/items?limit=2"

        pages = 0
        max_pages = 50  # Safety limit

        while url and pages < max_pages:
            resp = editor_client.get(url)
            assert resp.status_code == 200
            data = resp.json()

            for feature in data["features"]:
                all_ids.append(feature["id"])

            url = None
            for link in data.get("links", []):
                if link["rel"] == "next":
                    url = link["href"]
                    break
            pages += 1

        # Verify no duplicates
        assert len(all_ids) == len(set(all_ids)), (
            f"Found duplicate feature IDs across {pages} pages: {[fid for fid in all_ids if all_ids.count(fid) > 1]}"
        )

        # Verify we actually paginated
        assert pages >= 2, f"Expected at least 2 pages with limit=2 and {PAGINATION_SEED_COUNT} features"
