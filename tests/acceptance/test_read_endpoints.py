"""Read endpoint tests — landing page, conformance, API definition, items.

Covers TODO sections 1 (Read Endpoints) and 2 (Authentication & Token Lifecycle).
"""

from __future__ import annotations

import httpx
import pytest

from tests.acceptance.conftest import COLLECTION_ID, create_feature, make_test_feature

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


# ---------------------------------------------------------------------------
# GET /collections/{id}/items?organization=... — Unauthenticated items
# ---------------------------------------------------------------------------


class TestUnauthenticatedItems:
    """Unauthenticated GET items with organization query parameter."""

    @pytest.fixture(autouse=True)
    def _seed_public_feature(
        self,
        admin_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Create a public feature for unauthenticated listing."""
        self._tag = f"{test_run_id}-anon-items"
        body = make_test_feature(
            test_run_id,
            name="AnonItems-Public",
            visibility="public",
            extra_props={"anon_items_tag": self._tag},
        )
        resp = admin_client.post(
            f"/collections/{COLLECTION_ID}/items",
            json=body,
        )
        assert resp.status_code == 201

    def test_anon_items_returns_geojson_feature_collection(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """GET /collections/{id}/items?organization=... returns a valid GeoJSON FeatureCollection."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"organization": "TestOrgA"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "FeatureCollection"
        assert "features" in body
        assert isinstance(body["features"], list)
        assert "links" in body
        assert "numberReturned" in body

    def test_anon_items_features_have_correct_structure(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """Each feature in the response has type, geometry, properties, and id."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"organization": "TestOrgA", "limit": "10"},
        )
        assert resp.status_code == 200
        features = resp.json()["features"]
        assert len(features) > 0, "Expected at least one feature"
        for feat in features:
            assert feat["type"] == "Feature"
            assert "geometry" in feat
            assert "properties" in feat
            assert "id" in feat

    def test_anon_items_includes_seeded_feature(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """The seeded public feature appears in the unauthenticated listing."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"organization": "TestOrgA", "limit": "100"},
        )
        assert resp.status_code == 200
        features = resp.json()["features"]
        tagged = [f for f in features if f["properties"].get("anon_items_tag") == self._tag]
        assert len(tagged) >= 1, "Expected seeded public feature in results"
        assert tagged[0]["properties"]["name"] == "AnonItems-Public"


# ---------------------------------------------------------------------------
# GET /collections/{id}/items/{featureId}?organization=... — Single feature
# ---------------------------------------------------------------------------


class TestUnauthenticatedSingleFeature:
    """Unauthenticated GET single feature with organization param."""

    @pytest.fixture(autouse=True)
    def _seed_feature(
        self,
        admin_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Create a public feature and store its ID for retrieval tests."""
        self._feature_id, self._etag = create_feature(
            admin_client,
            test_run_id,
            name="AnonSingle-Public",
            visibility="public",
        )

    def test_anon_get_existing_public_feature(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """GET existing public feature with organization param returns 200."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items/{self._feature_id}",
            params={"organization": "TestOrgA"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "Feature"
        assert body["id"] == self._feature_id
        assert body["properties"]["name"] == "AnonSingle-Public"
        assert "geometry" in body
        assert "ETag" in resp.headers or "etag" in resp.headers

    def test_anon_get_nonexistent_feature_404(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """GET nonexistent feature returns 404."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items/does-not-exist-xyz",
            params={"organization": "TestOrgA"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Seed-feature discovery — unauthenticated without organization param
# ---------------------------------------------------------------------------


class TestSeedFeatureDiscovery:
    """Seed features are visible anonymously without the organization param.

    The acceptance-test collection has a single org (TestOrgA), so the
    server auto-defaults to it.  This is the same path OGC CITE tests
    follow (they don't know about the organization parameter).
    """

    def test_items_without_org_returns_200(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """GET items without organization param succeeds for single-org collection."""
        resp = anon_client.get(f"/collections/{COLLECTION_ID}/items")
        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "FeatureCollection"

    def test_seed_features_are_present(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """At least one seed feature is discoverable without auth."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"limit": "100"},
        )
        assert resp.status_code == 200
        features = resp.json()["features"]
        seed_names = {f["properties"].get("name") for f in features}
        # At least one of the three seed features
        expected = {"Alpha Cave", "Beta Cave", "Gamma Cave"}
        assert seed_names & expected, f"Expected seed features in {seed_names}"

    def test_single_seed_feature_by_id(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """A seed feature can be retrieved by ID without organization param."""
        resp = anon_client.get(f"/collections/{COLLECTION_ID}/items/seed-cave-alpha")
        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "Feature"
        assert body["id"] == "seed-cave-alpha"
        assert body["properties"]["name"] == "Alpha Cave"


# ---------------------------------------------------------------------------
# Query parameter validation (OGC req/core/query-param-unknown & invalid)
# ---------------------------------------------------------------------------


class TestQueryParamValidation:
    """OGC conformance: reject unknown and invalid query parameters."""

    def test_unknown_query_param_returns_400(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """Unknown query parameters must return 400."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"totallyBogusParam": "value"},
        )
        assert resp.status_code == 400

    def test_invalid_limit_returns_400(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """Non-integer limit must return 400."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"limit": "notAnInteger"},
        )
        assert resp.status_code == 400

    def test_invalid_bbox_returns_400(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """Malformed bbox must return 400."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"bbox": "x,y,z,w"},
        )
        assert resp.status_code == 400

    def test_valid_bbox_returns_200(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """Properly-formed bbox must be accepted."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"bbox": "-117,42,-111,49"},
        )
        assert resp.status_code == 200

    def test_known_property_filter_is_accepted(
        self,
        anon_client: httpx.Client,
    ) -> None:
        """A query parameter matching a collection property is valid."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"name": "test"},
        )
        assert resp.status_code == 200
