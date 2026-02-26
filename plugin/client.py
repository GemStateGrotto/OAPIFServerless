"""OAPIF HTTP client — pure Python, no PyQGIS dependency.

Wraps all OGC API - Features endpoints with typed return values.
Uses ``urllib.request`` (stdlib) so it works in both the DevContainer
and the QGIS Docker container without extra dependencies.

All methods accept an optional ``token`` parameter for authenticated
requests.  Unauthenticated requests omit the Authorization header.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Link:
    """A single OAPIF link object."""

    href: str
    rel: str
    type: str = ""
    title: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Link:
        return cls(
            href=data["href"],
            rel=data.get("rel", ""),
            type=data.get("type", ""),
            title=data.get("title", ""),
        )


@dataclass(frozen=True)
class LandingPage:
    """OAPIF landing page response."""

    title: str
    description: str
    links: list[Link]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LandingPage:
        return cls(
            title=data.get("title", ""),
            description=data.get("description", ""),
            links=[Link.from_dict(lnk) for lnk in data.get("links", [])],
        )


@dataclass(frozen=True)
class CollectionMetadata:
    """Metadata for a single OAPIF collection."""

    id: str
    title: str
    description: str
    links: list[Link]
    extent: dict[str, Any] = field(default_factory=dict)
    item_type: str = "feature"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CollectionMetadata:
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            description=data.get("description", ""),
            links=[Link.from_dict(lnk) for lnk in data.get("links", [])],
            extent=data.get("extent", {}),
            item_type=data.get("itemType", "feature"),
        )


@dataclass(frozen=True)
class FeatureCollection:
    """GeoJSON FeatureCollection with pagination metadata."""

    type: str
    features: list[dict[str, Any]]
    links: list[Link]
    number_matched: int | None
    number_returned: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureCollection:
        return cls(
            type=data.get("type", "FeatureCollection"),
            features=data.get("features", []),
            links=[Link.from_dict(lnk) for lnk in data.get("links", [])],
            number_matched=data.get("numberMatched"),
            number_returned=data.get("numberReturned", len(data.get("features", []))),
        )


@dataclass(frozen=True)
class FeatureResult:
    """A single GeoJSON Feature with its ETag."""

    feature: dict[str, Any]
    etag: str

    @property
    def feature_id(self) -> str:
        return str(self.feature.get("id", ""))


@dataclass(frozen=True)
class MutationResult:
    """Result of a create/update/delete operation."""

    feature_id: str
    etag: str
    location: str = ""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class OapifClientError(Exception):
    """Base exception for OAPIF client errors."""

    def __init__(self, status_code: int, message: str, detail: str = "") -> None:
        self.status_code = status_code
        self.message = message
        self.detail = detail
        super().__init__(
            f"{status_code} {message}: {detail}"
            if detail
            else f"{status_code} {message}"
        )


class NotFoundError(OapifClientError):
    """404 Not Found."""

    def __init__(self, message: str = "Not found", detail: str = "") -> None:
        super().__init__(404, message, detail)


class PreconditionFailedError(OapifClientError):
    """412 Precondition Failed — ETag mismatch."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(412, "Precondition Failed", detail)


class UnauthorizedError(OapifClientError):
    """401 Unauthorized."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(401, "Unauthorized", detail)


class ForbiddenError(OapifClientError):
    """403 Forbidden."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(403, "Forbidden", detail)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _build_request(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    etag: str | None = None,
) -> urllib.request.Request:
    """Build a ``urllib.request.Request`` with common headers."""
    req_headers: dict[str, str] = {
        "Accept": "application/geo+json, application/json;q=0.9",
    }
    if token:
        req_headers["Authorization"] = f"Bearer {token}"
    if etag:
        req_headers["If-Match"] = etag

    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/geo+json")

    # Custom headers override defaults (e.g. Content-Type for PATCH)
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    return req


def _execute(req: urllib.request.Request) -> tuple[int, dict[str, str], bytes]:
    """Execute a request and return (status, headers, body).

    Raises ``OapifClientError`` subclasses for known error codes.
    """
    try:
        with urllib.request.urlopen(req) as resp:
            status: int = resp.status
            headers = {k.lower(): v for k, v in resp.getheaders()}
            body = resp.read()
            return status, headers, body
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read()
        detail = ""
        try:
            err_json = json.loads(body)
            detail = err_json.get("detail", err_json.get("description", ""))
        except (json.JSONDecodeError, AttributeError):
            detail = body.decode("utf-8", errors="replace")

        if status == 404:
            raise NotFoundError(detail=detail) from exc
        if status == 412:
            raise PreconditionFailedError(detail=detail) from exc
        if status == 401:
            raise UnauthorizedError(detail=detail) from exc
        if status == 403:
            raise ForbiddenError(detail=detail) from exc
        raise OapifClientError(status, "HTTP Error", detail) from exc


def _json_body(body: bytes) -> dict[str, Any]:
    """Parse JSON response body."""
    result: dict[str, Any] = json.loads(body)
    return result


# ---------------------------------------------------------------------------
# Client class
# ---------------------------------------------------------------------------


class OapifClient:
    """Pure Python client for OGC API - Features endpoints.

    Parameters
    ----------
    base_url:
        The root URL of the OAPIF API (e.g. ``https://api.example.com``).
        Trailing slashes are stripped.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    # -- Read endpoints ----------------------------------------------------

    def get_landing_page(self, *, token: str | None = None) -> LandingPage:
        """``GET /`` — landing page with links."""
        req = _build_request(f"{self.base_url}/", token=token)
        _status, _headers, body = _execute(req)
        return LandingPage.from_dict(_json_body(body))

    def get_collections(self, *, token: str | None = None) -> list[CollectionMetadata]:
        """``GET /collections`` — list all collections."""
        req = _build_request(f"{self.base_url}/collections", token=token)
        _status, _headers, body = _execute(req)
        data = _json_body(body)
        return [CollectionMetadata.from_dict(c) for c in data.get("collections", [])]

    def get_collection(
        self, collection_id: str, *, token: str | None = None
    ) -> CollectionMetadata:
        """``GET /collections/{collectionId}`` — single collection metadata."""
        url = f"{self.base_url}/collections/{_quote(collection_id)}"
        req = _build_request(url, token=token)
        _status, _headers, body = _execute(req)
        return CollectionMetadata.from_dict(_json_body(body))

    def get_features(
        self,
        collection_id: str,
        *,
        token: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        organization: str | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> FeatureCollection:
        """``GET /collections/{collectionId}/items`` — feature collection (single page)."""
        url = self._items_url(
            collection_id,
            bbox=bbox,
            limit=limit,
            cursor=cursor,
            organization=organization,
            extra_params=extra_params,
        )
        req = _build_request(url, token=token)
        _status, _headers, body = _execute(req)
        return FeatureCollection.from_dict(_json_body(body))

    def get_all_features(
        self,
        collection_id: str,
        *,
        token: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int | None = None,
        organization: str | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all features across all pages by following ``next`` links.

        Returns the concatenated list of GeoJSON Feature dicts.
        """
        all_features: list[dict[str, Any]] = []
        url: str | None = self._items_url(
            collection_id,
            bbox=bbox,
            limit=limit,
            organization=organization,
            extra_params=extra_params,
        )

        while url is not None:
            req = _build_request(url, token=token)
            _status, _headers, body = _execute(req)
            data = _json_body(body)
            all_features.extend(data.get("features", []))

            # Follow the ``next`` link if present
            url = None
            for link in data.get("links", []):
                if link.get("rel") == "next":
                    url = link["href"]
                    break

        return all_features

    def get_feature(
        self,
        collection_id: str,
        feature_id: str,
        *,
        token: str | None = None,
        organization: str | None = None,
    ) -> FeatureResult:
        """``GET /collections/{collectionId}/items/{featureId}`` — single feature + ETag."""
        url = f"{self.base_url}/collections/{_quote(collection_id)}/items/{_quote(feature_id)}"
        if organization:
            url += f"?organization={_quote(organization)}"
        req = _build_request(url, token=token)
        _status, headers, body = _execute(req)
        etag = headers.get("etag", "")
        return FeatureResult(feature=_json_body(body), etag=etag)

    # -- Write endpoints ---------------------------------------------------

    def create_feature(
        self,
        collection_id: str,
        feature: dict[str, Any],
        token: str,
    ) -> MutationResult:
        """``POST /collections/{collectionId}/items`` — create a feature.

        Returns the feature ID and ETag from the response.
        """
        url = f"{self.base_url}/collections/{_quote(collection_id)}/items"
        req = _build_request(url, method="POST", token=token, body=feature)
        _status, headers, body = _execute(req)
        data = _json_body(body)
        return MutationResult(
            feature_id=str(data.get("id", "")),
            etag=headers.get("etag", ""),
            location=headers.get("location", ""),
        )

    def update_feature(
        self,
        collection_id: str,
        feature_id: str,
        feature: dict[str, Any],
        etag: str,
        token: str,
    ) -> MutationResult:
        """``PUT /collections/{collectionId}/items/{featureId}`` — replace a feature.

        Requires a valid ETag for optimistic concurrency control.
        """
        url = f"{self.base_url}/collections/{_quote(collection_id)}/items/{_quote(feature_id)}"
        req = _build_request(url, method="PUT", token=token, body=feature, etag=etag)
        _status, headers, body = _execute(req)
        data = _json_body(body)
        return MutationResult(
            feature_id=str(data.get("id", feature_id)),
            etag=headers.get("etag", ""),
        )

    def patch_feature(
        self,
        collection_id: str,
        feature_id: str,
        patch: dict[str, Any],
        etag: str,
        token: str,
    ) -> MutationResult:
        """``PATCH /collections/{collectionId}/items/{featureId}`` — partial update.

        Uses JSON Merge Patch (RFC 7396).  Requires a valid ETag.
        """
        url = f"{self.base_url}/collections/{_quote(collection_id)}/items/{_quote(feature_id)}"
        req = _build_request(
            url,
            method="PATCH",
            token=token,
            body=patch,
            etag=etag,
            headers={"Content-Type": "application/merge-patch+json"},
        )
        _status, headers, body = _execute(req)
        data = _json_body(body)
        return MutationResult(
            feature_id=str(data.get("id", feature_id)),
            etag=headers.get("etag", ""),
        )

    def delete_feature(
        self,
        collection_id: str,
        feature_id: str,
        etag: str,
        token: str,
    ) -> None:
        """``DELETE /collections/{collectionId}/items/{featureId}`` — delete a feature.

        Requires a valid ETag for optimistic concurrency control.
        """
        url = f"{self.base_url}/collections/{_quote(collection_id)}/items/{_quote(feature_id)}"
        req = _build_request(url, method="DELETE", token=token, etag=etag)
        _execute(req)

    # -- URL helpers -------------------------------------------------------

    def _items_url(
        self,
        collection_id: str,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        organization: str | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> str:
        """Build the items endpoint URL with query parameters."""
        base = f"{self.base_url}/collections/{_quote(collection_id)}/items"
        params: dict[str, str] = {}
        if bbox is not None:
            params["bbox"] = ",".join(str(v) for v in bbox)
        if limit is not None:
            params["limit"] = str(limit)
        if cursor is not None:
            params["cursor"] = cursor
        if organization is not None:
            params["organization"] = organization
        if extra_params:
            params.update(extra_params)
        if params:
            return f"{base}?{urllib.parse.urlencode(params)}"
        return base


def _quote(segment: str) -> str:
    """URL-encode a path segment."""
    return urllib.parse.quote(segment, safe="")
