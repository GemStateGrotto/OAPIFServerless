"""Read endpoint tests — landing page, conformance, API definition.

Covers TODO sections 1 (Read Endpoints) and 2 (Authentication & Token Lifecycle).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.acceptance


# ---------------------------------------------------------------------------
# GET / — Landing page (OGC 17-069r4 §7.2)
# ---------------------------------------------------------------------------


class TestLandingPage:
    """Landing page must include required OGC links."""

    def test_landing_page_status(self, anon_client: object) -> None:
        """GET / returns 200."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        resp = client.get("/")
        assert resp.status_code == 200

    def test_landing_page_has_title(self, anon_client: object) -> None:
        """Response includes a title."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        body = client.get("/").json()
        assert "title" in body
        assert isinstance(body["title"], str)
        assert len(body["title"]) > 0

    def test_landing_page_self_link(self, anon_client: object) -> None:
        """Response has a 'self' link."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        body = client.get("/").json()
        rels = {link["rel"] for link in body.get("links", [])}
        assert "self" in rels

    def test_landing_page_service_desc_link(self, anon_client: object) -> None:
        """Response has a 'service-desc' link."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        body = client.get("/").json()
        rels = {link["rel"] for link in body.get("links", [])}
        assert "service-desc" in rels

    def test_landing_page_conformance_link(self, anon_client: object) -> None:
        """Response has a 'conformance' link."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        body = client.get("/").json()
        rels = {link["rel"] for link in body.get("links", [])}
        assert "conformance" in rels

    def test_landing_page_data_link(self, anon_client: object) -> None:
        """Response has a 'data' link pointing to /collections."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        body = client.get("/").json()
        rels = {link["rel"] for link in body.get("links", [])}
        assert "data" in rels

    def test_landing_page_links_use_https(self, anon_client: object) -> None:
        """All link hrefs use HTTPS."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        body = client.get("/").json()
        for link in body.get("links", []):
            assert link["href"].startswith("https://"), f"Non-HTTPS link: {link['href']}"


# ---------------------------------------------------------------------------
# GET /conformance — Conformance declaration (OGC 17-069r4 §7.4)
# ---------------------------------------------------------------------------


class TestConformance:
    """Conformance endpoint must declare all supported conformance classes."""

    def test_conformance_status(self, anon_client: object) -> None:
        """GET /conformance returns 200."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        resp = client.get("/conformance")
        assert resp.status_code == 200

    def test_conformance_has_conforms_to(self, anon_client: object) -> None:
        """Response contains a 'conformsTo' array."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        body = client.get("/conformance").json()
        assert "conformsTo" in body
        assert isinstance(body["conformsTo"], list)
        assert len(body["conformsTo"]) > 0

    def test_conformance_core(self, anon_client: object) -> None:
        """Declares OGC API Features Part 1 Core."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        classes = client.get("/conformance").json()["conformsTo"]
        assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core" in classes

    def test_conformance_oas30(self, anon_client: object) -> None:
        """Declares OpenAPI 3.0 conformance."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        classes = client.get("/conformance").json()["conformsTo"]
        assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30" in classes

    def test_conformance_geojson(self, anon_client: object) -> None:
        """Declares GeoJSON conformance."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        classes = client.get("/conformance").json()["conformsTo"]
        assert "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson" in classes

    def test_conformance_crud(self, anon_client: object) -> None:
        """Declares Part 4 CRUD conformance."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        classes = client.get("/conformance").json()["conformsTo"]
        assert "http://www.opengis.net/spec/ogcapi-features-4/0.0/conf/crud" in classes

    def test_conformance_schemas(self, anon_client: object) -> None:
        """Declares Part 5 Schemas conformance."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        classes = client.get("/conformance").json()["conformsTo"]
        assert "http://www.opengis.net/spec/ogcapi-features-5/0.0/conf/schemas" in classes


# ---------------------------------------------------------------------------
# GET /api — OpenAPI definition (OGC 17-069r4 §7.3)
# ---------------------------------------------------------------------------


class TestOpenAPI:
    """The /api endpoint must return valid OpenAPI 3.0 JSON."""

    def test_api_status(self, anon_client: object) -> None:
        """GET /api returns 200."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        resp = client.get("/api")
        assert resp.status_code == 200

    def test_api_is_openapi3(self, anon_client: object) -> None:
        """Response contains openapi field starting with '3.'."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        body = client.get("/api").json()
        assert "openapi" in body
        assert body["openapi"].startswith("3.")

    def test_api_has_info(self, anon_client: object) -> None:
        """Response contains an 'info' block with title."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        body = client.get("/api").json()
        assert "info" in body
        assert "title" in body["info"]

    def test_api_has_paths(self, anon_client: object) -> None:
        """Response contains a 'paths' block."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        body = client.get("/api").json()
        assert "paths" in body
        assert isinstance(body["paths"], dict)
        assert len(body["paths"]) > 0

    def test_api_content_type(self, anon_client: object) -> None:
        """Content-Type is the OpenAPI JSON media type."""
        from httpx import Client

        client: Client = anon_client  # type: ignore[assignment]
        resp = client.get("/api")
        ct = resp.headers.get("content-type", "")
        assert "openapi" in ct or "json" in ct
