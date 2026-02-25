"""Collection endpoint tests.

Covers TODO section 1 collection-related items:
- GET /collections
- GET /collections/{id}
- GET /collections/{id} for nonexistent
"""

from __future__ import annotations

import httpx
import pytest

from tests.acceptance.conftest import COLLECTION_ID

pytestmark = pytest.mark.acceptance


class TestCollections:
    """GET /collections and GET /collections/{id}."""

    def test_collections_status(self, anon_client: httpx.Client) -> None:
        """GET /collections returns 200."""
        resp = anon_client.get("/collections")
        assert resp.status_code == 200

    def test_collections_has_array(self, anon_client: httpx.Client) -> None:
        """Response contains a 'collections' array."""
        body = anon_client.get("/collections").json()
        assert "collections" in body
        assert isinstance(body["collections"], list)

    def test_collections_entries_have_id(self, anon_client: httpx.Client) -> None:
        """Each collection entry has an id field."""
        body = anon_client.get("/collections").json()
        for col in body["collections"]:
            assert "id" in col, f"Collection entry missing 'id': {col}"

    def test_collections_entries_have_links(self, anon_client: httpx.Client) -> None:
        """Each collection entry has a links array."""
        body = anon_client.get("/collections").json()
        for col in body["collections"]:
            assert "links" in col, f"Collection missing 'links': {col.get('id')}"

    def test_collections_self_link(self, anon_client: httpx.Client) -> None:
        """Response has a 'self' link."""
        body = anon_client.get("/collections").json()
        rels = {link["rel"] for link in body.get("links", [])}
        assert "self" in rels

    def test_acceptance_collection_present(self, anon_client: httpx.Client) -> None:
        """The acceptance-test test collection is listed."""
        body = anon_client.get("/collections").json()
        ids = [c["id"] for c in body["collections"]]
        assert COLLECTION_ID in ids, f"Expected '{COLLECTION_ID}' in {ids}"


class TestSingleCollection:
    """GET /collections/{id}."""

    def test_single_collection_status(self, anon_client: httpx.Client) -> None:
        """GET /collections/{id} for existing collection returns 200."""
        resp = anon_client.get(f"/collections/{COLLECTION_ID}")
        assert resp.status_code == 200

    def test_single_collection_id_matches(self, anon_client: httpx.Client) -> None:
        """Response id matches requested collection."""
        body = anon_client.get(f"/collections/{COLLECTION_ID}").json()
        assert body["id"] == COLLECTION_ID

    def test_single_collection_has_title(self, anon_client: httpx.Client) -> None:
        """Response contains a title."""
        body = anon_client.get(f"/collections/{COLLECTION_ID}").json()
        assert "title" in body
        assert len(body["title"]) > 0

    def test_single_collection_has_links(self, anon_client: httpx.Client) -> None:
        """Response contains links."""
        body = anon_client.get(f"/collections/{COLLECTION_ID}").json()
        assert "links" in body
        assert isinstance(body["links"], list)

    def test_nonexistent_collection_404(self, anon_client: httpx.Client) -> None:
        """GET /collections/{id} for nonexistent collection returns 404."""
        resp = anon_client.get("/collections/nonexistent-collection-xyz")
        assert resp.status_code == 404


class TestCollectionsAuthenticated:
    """Authenticated GET /collections should work identically."""

    def test_editor_gets_collections(self, editor_client: httpx.Client) -> None:
        """Authenticated editor can list collections."""
        resp = editor_client.get("/collections")
        assert resp.status_code == 200
        body = resp.json()
        assert "collections" in body

    def test_viewer_gets_collections(self, viewer_client: httpx.Client) -> None:
        """Authenticated viewer can list collections."""
        resp = viewer_client.get("/collections")
        assert resp.status_code == 200
