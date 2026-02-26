"""Unit tests for the OAPIF HTTP client.

Pure Python — no QGIS dependency.  Uses ``unittest.mock`` to simulate
HTTP responses and validate URL construction, header injection, and
pagination link following.
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from plugin.client import (
    CollectionMetadata,
    FeatureCollection,
    FeatureResult,
    LandingPage,
    MutationResult,
    NotFoundError,
    OapifClient,
    OapifClientError,
    PreconditionFailedError,
    UnauthorizedError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(
    status: int = 200,
    body: dict[str, Any] | list[Any] | None = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Build a mock ``urllib.request.urlopen`` context manager response."""
    if body is None:
        body = {}
    resp = MagicMock()
    resp.status = status
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.return_value = json.dumps(body).encode("utf-8")
    resp_headers = headers or {}
    resp.getheaders.return_value = list(resp_headers.items())
    resp.info.return_value = resp_headers
    return resp


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestGetLandingPage:
    """GET / — landing page."""

    @patch("plugin.client.urllib.request.urlopen")
    def test_returns_landing_page(self, mock_urlopen: MagicMock) -> None:
        body = {
            "title": "TestAPI",
            "description": "A test API",
            "links": [
                {
                    "href": "https://api.example.com/",
                    "rel": "self",
                    "type": "application/json",
                    "title": "This doc",
                },
            ],
        }
        mock_urlopen.return_value = _mock_response(200, body)
        client = OapifClient("https://api.example.com")
        result = client.get_landing_page()

        assert isinstance(result, LandingPage)
        assert result.title == "TestAPI"
        assert result.description == "A test API"
        assert len(result.links) == 1
        assert result.links[0].rel == "self"

    @patch("plugin.client.urllib.request.urlopen")
    def test_strips_trailing_slash(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _mock_response(200, {"title": "T", "links": []})
        client = OapifClient("https://api.example.com/")
        client.get_landing_page()

        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://api.example.com/"

    @patch("plugin.client.urllib.request.urlopen")
    def test_sends_auth_header(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _mock_response(200, {"links": []})
        client = OapifClient("https://api.example.com")
        client.get_landing_page(token="my-jwt-token")

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer my-jwt-token"

    @patch("plugin.client.urllib.request.urlopen")
    def test_no_auth_header_when_no_token(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _mock_response(200, {"links": []})
        client = OapifClient("https://api.example.com")
        client.get_landing_page()

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") is None


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestGetCollections:
    """GET /collections."""

    @patch("plugin.client.urllib.request.urlopen")
    def test_returns_collection_list(self, mock_urlopen: MagicMock) -> None:
        body = {
            "collections": [
                {
                    "id": "caves",
                    "title": "Caves",
                    "description": "Cave features",
                    "links": [],
                },
                {
                    "id": "springs",
                    "title": "Springs",
                    "description": "Spring features",
                    "links": [],
                },
            ],
        }
        mock_urlopen.return_value = _mock_response(200, body)
        client = OapifClient("https://api.example.com")
        result = client.get_collections()

        assert len(result) == 2
        assert all(isinstance(c, CollectionMetadata) for c in result)
        assert result[0].id == "caves"
        assert result[1].title == "Springs"

    @patch("plugin.client.urllib.request.urlopen")
    def test_single_collection(self, mock_urlopen: MagicMock) -> None:
        body = {
            "id": "caves",
            "title": "Caves",
            "description": "Cave data",
            "links": [],
        }
        mock_urlopen.return_value = _mock_response(200, body)
        client = OapifClient("https://api.example.com")
        result = client.get_collection("caves")

        assert isinstance(result, CollectionMetadata)
        assert result.id == "caves"

        req = mock_urlopen.call_args[0][0]
        assert "/collections/caves" in req.full_url


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestGetFeatures:
    """GET /collections/{id}/items."""

    @patch("plugin.client.urllib.request.urlopen")
    def test_returns_feature_collection(self, mock_urlopen: MagicMock) -> None:
        body = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": "f1", "geometry": None, "properties": {}}
            ],
            "links": [],
            "numberMatched": 1,
            "numberReturned": 1,
        }
        mock_urlopen.return_value = _mock_response(200, body)
        client = OapifClient("https://api.example.com")
        result = client.get_features("caves")

        assert isinstance(result, FeatureCollection)
        assert len(result.features) == 1
        assert result.number_matched == 1

    @patch("plugin.client.urllib.request.urlopen")
    def test_bbox_query_param(self, mock_urlopen: MagicMock) -> None:
        body = {"type": "FeatureCollection", "features": [], "links": []}
        mock_urlopen.return_value = _mock_response(200, body)
        client = OapifClient("https://api.example.com")
        client.get_features("caves", bbox=(-116.0, 43.0, -114.0, 45.0))

        req = mock_urlopen.call_args[0][0]
        assert "bbox=-116.0%2C43.0%2C-114.0%2C45.0" in req.full_url

    @patch("plugin.client.urllib.request.urlopen")
    def test_limit_query_param(self, mock_urlopen: MagicMock) -> None:
        body = {"type": "FeatureCollection", "features": [], "links": []}
        mock_urlopen.return_value = _mock_response(200, body)
        client = OapifClient("https://api.example.com")
        client.get_features("caves", limit=50)

        req = mock_urlopen.call_args[0][0]
        assert "limit=50" in req.full_url

    @patch("plugin.client.urllib.request.urlopen")
    def test_organization_query_param(self, mock_urlopen: MagicMock) -> None:
        body = {"type": "FeatureCollection", "features": [], "links": []}
        mock_urlopen.return_value = _mock_response(200, body)
        client = OapifClient("https://api.example.com")
        client.get_features("caves", organization="TestOrgA")

        req = mock_urlopen.call_args[0][0]
        assert "organization=TestOrgA" in req.full_url

    @patch("plugin.client.urllib.request.urlopen")
    def test_extra_params(self, mock_urlopen: MagicMock) -> None:
        body = {"type": "FeatureCollection", "features": [], "links": []}
        mock_urlopen.return_value = _mock_response(200, body)
        client = OapifClient("https://api.example.com")
        client.get_features("caves", extra_params={"status": "active"})

        req = mock_urlopen.call_args[0][0]
        assert "status=active" in req.full_url


# ---------------------------------------------------------------------------
# Single feature with ETag
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestGetFeature:
    """GET /collections/{id}/items/{featureId}."""

    @patch("plugin.client.urllib.request.urlopen")
    def test_returns_feature_with_etag(self, mock_urlopen: MagicMock) -> None:
        body = {
            "type": "Feature",
            "id": "f1",
            "geometry": None,
            "properties": {"name": "Cave A"},
        }
        mock_urlopen.return_value = _mock_response(
            200, body, headers={"ETag": '"abc123"'}
        )
        client = OapifClient("https://api.example.com")
        result = client.get_feature("caves", "f1")

        assert isinstance(result, FeatureResult)
        assert result.feature_id == "f1"
        assert result.etag == '"abc123"'
        assert result.feature["properties"]["name"] == "Cave A"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestPagination:
    """Automatic pagination via ``next`` links."""

    @patch("plugin.client.urllib.request.urlopen")
    def test_follows_next_links(self, mock_urlopen: MagicMock) -> None:
        page1 = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": "f1", "geometry": None, "properties": {}}
            ],
            "links": [
                {
                    "href": "https://api.example.com/collections/caves/items?cursor=abc",
                    "rel": "next",
                }
            ],
        }
        page2 = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": "f2", "geometry": None, "properties": {}}
            ],
            "links": [],
        }
        mock_urlopen.side_effect = [
            _mock_response(200, page1),
            _mock_response(200, page2),
        ]

        client = OapifClient("https://api.example.com")
        all_features = client.get_all_features("caves")

        assert len(all_features) == 2
        assert all_features[0]["id"] == "f1"
        assert all_features[1]["id"] == "f2"
        assert mock_urlopen.call_count == 2

    @patch("plugin.client.urllib.request.urlopen")
    def test_single_page_no_next(self, mock_urlopen: MagicMock) -> None:
        body = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": "f1", "geometry": None, "properties": {}}
            ],
            "links": [],
        }
        mock_urlopen.return_value = _mock_response(200, body)
        client = OapifClient("https://api.example.com")
        all_features = client.get_all_features("caves")

        assert len(all_features) == 1
        assert mock_urlopen.call_count == 1


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestWriteOperations:
    """POST, PUT, PATCH, DELETE endpoints."""

    @patch("plugin.client.urllib.request.urlopen")
    def test_create_feature(self, mock_urlopen: MagicMock) -> None:
        body: dict[str, Any] = {
            "type": "Feature",
            "id": "new-id",
            "geometry": None,
            "properties": {},
        }
        mock_urlopen.return_value = _mock_response(
            201,
            body,
            headers={"ETag": '"etag1"', "Location": "/collections/caves/items/new-id"},
        )
        client = OapifClient("https://api.example.com")
        result = client.create_feature(
            "caves", {"type": "Feature", "geometry": None, "properties": {}}, "token123"
        )

        assert isinstance(result, MutationResult)
        assert result.feature_id == "new-id"
        assert result.etag == '"etag1"'

        req = mock_urlopen.call_args[0][0]
        assert req.method == "POST"
        assert req.get_header("Authorization") == "Bearer token123"
        assert req.get_header("Content-type") == "application/geo+json"

    @patch("plugin.client.urllib.request.urlopen")
    def test_update_feature_sends_etag(self, mock_urlopen: MagicMock) -> None:
        body: dict[str, Any] = {
            "type": "Feature",
            "id": "f1",
            "geometry": None,
            "properties": {},
        }
        mock_urlopen.return_value = _mock_response(
            200, body, headers={"ETag": '"etag2"'}
        )
        client = OapifClient("https://api.example.com")
        result = client.update_feature(
            "caves",
            "f1",
            {"type": "Feature", "geometry": None, "properties": {"name": "Updated"}},
            '"etag1"',
            "token123",
        )

        assert result.etag == '"etag2"'
        req = mock_urlopen.call_args[0][0]
        assert req.method == "PUT"
        assert req.get_header("If-match") == '"etag1"'

    @patch("plugin.client.urllib.request.urlopen")
    def test_patch_feature(self, mock_urlopen: MagicMock) -> None:
        body: dict[str, Any] = {
            "type": "Feature",
            "id": "f1",
            "geometry": None,
            "properties": {},
        }
        mock_urlopen.return_value = _mock_response(
            200, body, headers={"ETag": '"etag3"'}
        )
        client = OapifClient("https://api.example.com")
        result = client.patch_feature(
            "caves",
            "f1",
            {"properties": {"name": "Patched"}},
            '"etag2"',
            "token123",
        )

        assert result.etag == '"etag3"'
        req = mock_urlopen.call_args[0][0]
        assert req.method == "PATCH"
        assert req.get_header("Content-type") == "application/merge-patch+json"

    @patch("plugin.client.urllib.request.urlopen")
    def test_delete_feature(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _mock_response(204)
        client = OapifClient("https://api.example.com")
        client.delete_feature("caves", "f1", '"etag1"', "token123")

        req = mock_urlopen.call_args[0][0]
        assert req.method == "DELETE"
        assert req.get_header("If-match") == '"etag1"'
        assert req.get_header("Authorization") == "Bearer token123"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestErrorHandling:
    """HTTP error response mapping."""

    @patch("plugin.client.urllib.request.urlopen")
    def test_404_raises_not_found(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        exc = urllib.error.HTTPError(
            url="https://api.example.com/collections/nope",
            code=404,
            msg="Not Found",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(json.dumps({"detail": "Collection not found"}).encode()),
        )
        mock_urlopen.side_effect = exc

        client = OapifClient("https://api.example.com")
        with pytest.raises(NotFoundError) as exc_info:
            client.get_collection("nope")
        assert exc_info.value.status_code == 404

    @patch("plugin.client.urllib.request.urlopen")
    def test_412_raises_precondition_failed(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        exc = urllib.error.HTTPError(
            url="https://api.example.com/collections/caves/items/f1",
            code=412,
            msg="Precondition Failed",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(json.dumps({"detail": "ETag mismatch"}).encode()),
        )
        mock_urlopen.side_effect = exc

        client = OapifClient("https://api.example.com")
        with pytest.raises(PreconditionFailedError):
            client.update_feature("caves", "f1", {}, '"stale"', "token")

    @patch("plugin.client.urllib.request.urlopen")
    def test_401_raises_unauthorized(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        exc = urllib.error.HTTPError(
            url="https://api.example.com/",
            code=401,
            msg="Unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(b'{"message":"Unauthorized"}'),
        )
        mock_urlopen.side_effect = exc

        client = OapifClient("https://api.example.com")
        with pytest.raises(UnauthorizedError):
            client.get_landing_page(token="bad-token")

    @patch("plugin.client.urllib.request.urlopen")
    def test_500_raises_generic_error(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        exc = urllib.error.HTTPError(
            url="https://api.example.com/",
            code=500,
            msg="Internal Server Error",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(b"Internal error"),
        )
        mock_urlopen.side_effect = exc

        client = OapifClient("https://api.example.com")
        with pytest.raises(OapifClientError) as exc_info:
            client.get_landing_page()
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# Content-Type negotiation
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestContentType:
    """Accept header is set correctly."""

    @patch("plugin.client.urllib.request.urlopen")
    def test_accept_header_includes_geojson(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _mock_response(200, {"links": []})
        client = OapifClient("https://api.example.com")
        client.get_landing_page()

        req = mock_urlopen.call_args[0][0]
        accept = req.get_header("Accept")
        assert "application/geo+json" in accept
        assert "application/json" in accept
