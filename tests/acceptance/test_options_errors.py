"""OPTIONS / CORS and error response tests.

Covers TODO sections 10 (OPTIONS / CORS) and 11 (Error Responses).
"""

from __future__ import annotations

import httpx
import pytest

from tests.acceptance.conftest import COLLECTION_ID

pytestmark = pytest.mark.acceptance


# ---------------------------------------------------------------------------
# OPTIONS endpoints (TODO §10)
# ---------------------------------------------------------------------------


class TestOptions:
    """OPTIONS requests must return Allow headers."""

    def test_options_items(self, anon_client: httpx.Client) -> None:
        """OPTIONS /collections/{id}/items returns Allow with GET, POST, OPTIONS."""
        resp = anon_client.request(
            "OPTIONS",
            f"/collections/{COLLECTION_ID}/items",
        )
        # OPTIONS should succeed (200 or 204)
        assert resp.status_code in (200, 204)
        allow = resp.headers.get("allow", "")
        for method in ("GET", "POST", "OPTIONS"):
            assert method in allow, f"Expected '{method}' in Allow header: {allow}"

    def test_options_feature(self, anon_client: httpx.Client) -> None:
        """OPTIONS /collections/{id}/items/{featureId} returns Allow with GET, PUT, PATCH, DELETE, OPTIONS."""
        resp = anon_client.request(
            "OPTIONS",
            f"/collections/{COLLECTION_ID}/items/dummy-feature-id",
        )
        assert resp.status_code in (200, 204)
        allow = resp.headers.get("allow", "")
        for method in ("GET", "PUT", "PATCH", "DELETE", "OPTIONS"):
            assert method in allow, f"Expected '{method}' in Allow header: {allow}"


# ---------------------------------------------------------------------------
# Error responses (TODO §11)
# ---------------------------------------------------------------------------


class TestErrorResponses:
    """Error responses should follow OGC exception schema."""

    def test_404_nonexistent_collection(self, anon_client: httpx.Client) -> None:
        """GET nonexistent collection returns 404."""
        resp = anon_client.get("/collections/this-collection-does-not-exist")
        assert resp.status_code == 404

    def test_404_nonexistent_feature(self, anon_client: httpx.Client) -> None:
        """GET nonexistent feature returns 404."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items/nonexistent-feature-id",
            params={"organization": "TestOrgA"},
        )
        assert resp.status_code == 404

    def test_404_has_error_body(self, anon_client: httpx.Client) -> None:
        """404 response has a JSON body with error information."""
        resp = anon_client.get("/collections/nonexistent-xyz-abc")
        assert resp.status_code == 404
        body = resp.json()
        # OGC exception format uses 'code' and 'description' (or similar)
        assert any(key in body for key in ("code", "description", "detail", "message")), (
            f"Error body missing expected fields: {body}"
        )

    def test_404_nonexistent_route(self, anon_client: httpx.Client) -> None:
        """GET a completely unknown path returns 404."""
        resp = anon_client.get("/this/path/does/not/exist")
        assert resp.status_code == 404
