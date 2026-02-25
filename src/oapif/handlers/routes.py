"""Route handler functions for OGC API - Features endpoints.

Each function receives the raw API Gateway event, the derived base URL,
and extracted path parameters.  They interact with the DAL and return
API Gateway v2-compatible response dicts.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import boto3
import jsonschema

from oapif.auth import (
    AuthContext,
    check_field_permissions_for_create,
    check_field_permissions_for_replace,
    check_field_permissions_for_update,
    require_write_role,
    resolve_auth_context,
)
from oapif.config import RuntimeConfig
from oapif.dal.collections import CollectionDAL
from oapif.dal.exceptions import (
    CollectionNotFoundError,
    ETagMismatchError,
    ETagRequiredError,
    FeatureNotFoundError,
    OrganizationImmutableError,
)
from oapif.dal.features import FeatureDAL
from oapif.handlers.responses import (
    error_response,
    geojson_response,
    json_response,
    no_content_response,
)
from oapif.models.feature import utcnow_iso
from oapif.schema import generate_schema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conformance classes declared by this server
# ---------------------------------------------------------------------------

CONFORMANCE_CLASSES: list[str] = [
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
    "http://www.opengis.net/spec/ogcapi-features-4/0.0/conf/crud",
    "http://www.opengis.net/spec/ogcapi-features-5/0.0/conf/schemas",
]

# ---------------------------------------------------------------------------
# Lazy-initialized singletons (created on first use / Lambda cold start)
# ---------------------------------------------------------------------------

_config: RuntimeConfig | None = None
_collection_dal: CollectionDAL | None = None
_feature_dal: FeatureDAL | None = None


def _get_config() -> RuntimeConfig:
    global _config
    if _config is None:
        _config = RuntimeConfig.from_env()
    return _config


def _get_collection_dal() -> CollectionDAL:
    global _collection_dal
    if _collection_dal is None:
        cfg = _get_config()
        resource = boto3.resource("dynamodb", region_name=cfg.aws_region)
        _collection_dal = CollectionDAL(
            dynamodb_resource=resource,
            config_table_name=cfg.config_table,
        )
    return _collection_dal


def _get_feature_dal() -> FeatureDAL:
    global _feature_dal
    if _feature_dal is None:
        cfg = _get_config()
        resource = boto3.resource("dynamodb", region_name=cfg.aws_region)
        _feature_dal = FeatureDAL(
            dynamodb_resource=resource,
            features_table_name=cfg.features_table,
            changes_table_name=cfg.changes_table,
        )
    return _feature_dal


def reset_singletons() -> None:
    """Reset lazy singletons — used by tests to inject mocks."""
    global _config, _collection_dal, _feature_dal
    _config = None
    _collection_dal = None
    _feature_dal = None


def set_collection_dal(dal: CollectionDAL) -> None:
    """Inject a CollectionDAL instance - used by tests."""
    global _collection_dal
    _collection_dal = dal


def set_feature_dal(dal: FeatureDAL) -> None:
    """Inject a FeatureDAL instance - used by tests."""
    global _feature_dal
    _feature_dal = dal


# ---------------------------------------------------------------------------
# Query parameter helpers
# ---------------------------------------------------------------------------


def _get_query_params(event: dict[str, Any]) -> dict[str, str]:
    """Extract query string parameters from the event."""
    return event.get("queryStringParameters") or {}


def _parse_bbox(raw: str) -> tuple[float, float, float, float] | None:
    """Parse a ``bbox`` query parameter into a 4-tuple, or None on failure."""
    try:
        parts = [float(x.strip()) for x in raw.split(",")]
        if len(parts) == 4:
            return (parts[0], parts[1], parts[2], parts[3])
    except ValueError, TypeError:
        pass
    return None


def _parse_limit(raw: str | None, default: int = 10, maximum: int = 1000) -> int:
    """Parse a ``limit`` query parameter, clamped to [1, maximum]."""
    if raw is None:
        return default
    try:
        val = int(raw)
        return max(1, min(val, maximum))
    except ValueError, TypeError:
        return default


# ---------------------------------------------------------------------------
# GET / — Landing page (OGC 17-069r4 §7.2)
# ---------------------------------------------------------------------------


def handle_landing_page(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Return the API landing page with required links."""
    body: dict[str, Any] = {
        "title": "OAPIFServerless",
        "description": "OGC API - Features backed by AWS DynamoDB",
        "links": [
            {
                "href": f"{base_url}/",
                "rel": "self",
                "type": "application/json",
                "title": "This document",
            },
            {
                "href": f"{base_url}/api",
                "rel": "service-desc",
                "type": "application/vnd.oai.openapi+json;version=3.0",
                "title": "OpenAPI definition",
            },
            {
                "href": f"{base_url}/conformance",
                "rel": "conformance",
                "type": "application/json",
                "title": "Conformance declaration",
            },
            {
                "href": f"{base_url}/collections",
                "rel": "data",
                "type": "application/json",
                "title": "Feature collections",
            },
        ],
    }
    return json_response(200, body)


# ---------------------------------------------------------------------------
# GET /conformance — Conformance declaration (OGC 17-069r4 §7.4)
# ---------------------------------------------------------------------------


def handle_conformance(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Return the conformance declaration."""
    body: dict[str, Any] = {
        "conformsTo": CONFORMANCE_CLASSES,
    }
    return json_response(200, body)


# ---------------------------------------------------------------------------
# GET /collections — Collection list (OGC 17-069r4 §7.13)
# ---------------------------------------------------------------------------


def handle_collections(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Return all collections."""
    dal = _get_collection_dal()
    configs = dal.list_collections()

    collections = [cfg.to_oapif_metadata(base_url=base_url) for cfg in configs]

    body: dict[str, Any] = {
        "links": [
            {
                "href": f"{base_url}/collections",
                "rel": "self",
                "type": "application/json",
                "title": "Collections",
            },
        ],
        "collections": collections,
    }
    return json_response(200, body)


# ---------------------------------------------------------------------------
# GET /collections/{collectionId} — Single collection (OGC 17-069r4 §7.14)
# ---------------------------------------------------------------------------


def handle_single_collection(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Return metadata for a single collection."""
    collection_id = path_params["collectionId"]
    dal = _get_collection_dal()

    try:
        config = dal.get_collection(collection_id)
    except CollectionNotFoundError:
        return error_response(404, "Collection not found", detail=f"Collection '{collection_id}' does not exist.")

    body = config.to_oapif_metadata(base_url=base_url)
    return json_response(200, body)


# ---------------------------------------------------------------------------
# GET /collections/{collectionId}/items — Feature collection (§7.15)
# ---------------------------------------------------------------------------


def handle_items(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Return a paged feature collection.

    Supports query parameters: ``limit``, ``cursor``, ``bbox``,
    and arbitrary property filters.
    """
    collection_id = path_params["collectionId"]
    params = _get_query_params(event)

    # Validate collection exists
    col_dal = _get_collection_dal()
    try:
        col_dal.get_collection(collection_id)
    except CollectionNotFoundError:
        return error_response(404, "Collection not found", detail=f"Collection '{collection_id}' does not exist.")

    # Parse standard parameters
    limit = _parse_limit(params.get("limit"))
    cursor = params.get("cursor")
    bbox = _parse_bbox(params["bbox"]) if "bbox" in params else None

    # Resolve authentication and authorization context
    auth: AuthContext = resolve_auth_context(event, query_params=params)
    organization = auth.organization
    visibility_filter = list(auth.visibility_filter)

    # Known non-property params to exclude from property filters
    reserved = {"limit", "cursor", "bbox", "organization", "f"}
    property_filters = {k: v for k, v in params.items() if k not in reserved}

    feat_dal = _get_feature_dal()
    result = feat_dal.query_features(
        collection_id=collection_id,
        organization=organization,
        limit=limit,
        cursor=cursor,
        bbox=bbox,
        property_filters=property_filters if property_filters else None,
        visibility_filter=visibility_filter,
    )

    features_geojson = [f.to_geojson() for f in result.features]

    # Build links
    items_url = f"{base_url}/collections/{collection_id}/items"
    links: list[dict[str, str]] = [
        {"href": items_url, "rel": "self", "type": "application/geo+json"},
    ]
    if result.next_cursor:
        next_href = f"{items_url}?cursor={result.next_cursor}"
        if organization:
            next_href += f"&organization={organization}"
        links.append({"href": next_href, "rel": "next", "type": "application/geo+json"})

    # Collection link
    links.append(
        {
            "href": f"{base_url}/collections/{collection_id}",
            "rel": "collection",
            "type": "application/json",
        }
    )

    body: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": features_geojson,
        "links": links,
        "timeStamp": utcnow_iso(),
        "numberReturned": len(features_geojson),
    }

    # Include numberMatched if the DAL was able to compute it
    if result.number_matched is not None:
        body["numberMatched"] = result.number_matched

    return geojson_response(200, body)


# ---------------------------------------------------------------------------
# GET /collections/{collectionId}/items/{featureId} — Single feature (§7.16)
# ---------------------------------------------------------------------------


def handle_feature(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Return a single feature with ETag header."""
    collection_id = path_params["collectionId"]
    feature_id = path_params["featureId"]
    params = _get_query_params(event)

    # Resolve authentication and authorization context
    auth: AuthContext = resolve_auth_context(event, query_params=params)
    organization = auth.organization
    visibility_filter = list(auth.visibility_filter)

    feat_dal = _get_feature_dal()
    try:
        feature = feat_dal.get_feature(
            collection_id,
            feature_id,
            organization,
            visibility_filter=visibility_filter,
        )
    except FeatureNotFoundError:
        return error_response(404, "Feature not found", detail=f"Feature '{feature_id}' not found.")

    geojson = feature.to_geojson()

    # Links
    feature_url = f"{base_url}/collections/{collection_id}/items/{feature_id}"
    geojson["links"] = [
        {"href": feature_url, "rel": "self", "type": "application/geo+json"},
        {
            "href": f"{base_url}/collections/{collection_id}",
            "rel": "collection",
            "type": "application/json",
        },
    ]

    return geojson_response(
        200,
        geojson,
        headers={"ETag": f'"{feature.etag}"'},
    )


# ---------------------------------------------------------------------------
# GET /collections/{collectionId}/schema — JSON Schema (Part 5)
# ---------------------------------------------------------------------------


def handle_schema(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Return the JSON Schema for a collection's features."""
    collection_id = path_params["collectionId"]
    params = _get_query_params(event)

    col_dal = _get_collection_dal()
    try:
        config = col_dal.get_collection(collection_id)
    except CollectionNotFoundError:
        return error_response(404, "Collection not found", detail=f"Collection '{collection_id}' does not exist.")

    # Determine schema variant from query parameter
    schema_type = params.get("type", "returnable")
    receivable = schema_type == "receivable"

    schema = generate_schema(config, receivable=receivable)

    # Override the $id to use the actual API base URL
    schema["$id"] = f"{base_url}/collections/{collection_id}/schema"

    return json_response(200, schema, content_type="application/schema+json")


# ---------------------------------------------------------------------------
# GET /api — OpenAPI definition (OGC 17-069r4 §7.3)
# ---------------------------------------------------------------------------


def handle_api(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Return a dynamically generated OpenAPI 3.0 definition.

    Enumerates all collections and builds paths for each.
    """
    col_dal = _get_collection_dal()
    configs = col_dal.list_collections()

    paths: dict[str, Any] = {
        "/": {
            "get": {
                "summary": "Landing page",
                "operationId": "getLandingPage",
                "tags": ["Capabilities"],
                "responses": {"200": {"description": "Landing page"}},
            },
        },
        "/conformance": {
            "get": {
                "summary": "Conformance declaration",
                "operationId": "getConformance",
                "tags": ["Capabilities"],
                "responses": {"200": {"description": "Conformance classes"}},
            },
        },
        "/collections": {
            "get": {
                "summary": "List collections",
                "operationId": "getCollections",
                "tags": ["Collections"],
                "responses": {"200": {"description": "List of feature collections"}},
            },
        },
    }

    for cfg in configs:
        cid = cfg.collection_id
        paths[f"/collections/{cid}"] = {
            "get": {
                "summary": f"Collection metadata for {cfg.title}",
                "operationId": f"getCollection_{cid}",
                "tags": ["Collections"],
                "responses": {"200": {"description": "Collection metadata"}},
            },
        }
        paths[f"/collections/{cid}/items"] = {
            "get": {
                "summary": f"Features in {cfg.title}",
                "operationId": f"getItems_{cid}",
                "tags": ["Features"],
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 10, "maximum": 1000}},
                    {"name": "cursor", "in": "query", "schema": {"type": "string"}},
                    {"name": "bbox", "in": "query", "schema": {"type": "string"}},
                    {"name": "organization", "in": "query", "required": True, "schema": {"type": "string"}},
                ],
                "responses": {"200": {"description": "GeoJSON FeatureCollection"}},
            },
        }
        paths[f"/collections/{cid}/items/{{featureId}}"] = {
            "get": {
                "summary": f"Single feature from {cfg.title}",
                "operationId": f"getFeature_{cid}",
                "tags": ["Features"],
                "parameters": [
                    {"name": "featureId", "in": "path", "required": True, "schema": {"type": "string"}},
                    {"name": "organization", "in": "query", "required": True, "schema": {"type": "string"}},
                ],
                "responses": {"200": {"description": "GeoJSON Feature"}},
            },
        }
        paths[f"/collections/{cid}/schema"] = {
            "get": {
                "summary": f"Schema for {cfg.title}",
                "operationId": f"getSchema_{cid}",
                "tags": ["Schemas"],
                "parameters": [
                    {
                        "name": "type",
                        "in": "query",
                        "schema": {"type": "string", "enum": ["returnable", "receivable"]},
                    },
                ],
                "responses": {"200": {"description": "JSON Schema"}},
            },
        }

    openapi: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {
            "title": "OAPIFServerless",
            "description": "OGC API - Features backed by AWS DynamoDB",
            "version": "0.1.0",
        },
        "servers": [{"url": base_url}],
        "paths": paths,
    }

    return json_response(200, openapi, content_type="application/vnd.oai.openapi+json;version=3.0")


# ---------------------------------------------------------------------------
# Request body / header helpers
# ---------------------------------------------------------------------------


def _parse_request_body(event: dict[str, Any]) -> dict[str, Any] | None:
    """Extract and parse the JSON request body from an API Gateway v2 event.

    Returns ``None`` if the body is missing or empty.
    Raises ``ValueError`` if the body is not valid JSON.
    """
    raw = event.get("body")
    if not raw:
        return None

    if event.get("isBase64Encoded", False):
        raw = base64.b64decode(raw).decode("utf-8")

    return json.loads(raw)  # type: ignore[no-any-return]


def _get_if_match(event: dict[str, Any]) -> str | None:
    """Extract the ``If-Match`` header ETag value from the event.

    Strips surrounding quotes per RFC 9110.
    """
    headers = event.get("headers") or {}
    # API Gateway v2 lowercases all header names
    raw = headers.get("if-match")
    if raw is None:
        return None
    result: str = raw.strip().strip('"')
    return result


def _require_if_match(event: dict[str, Any]) -> str:
    """Extract and return the ``If-Match`` ETag, or raise 428 if missing."""
    etag = _get_if_match(event)
    if not etag:
        raise ETagRequiredError()
    return etag


def _validate_feature_body(
    body: dict[str, Any],
    collection_config: Any,
) -> str | None:
    """Validate a feature body against the collection's receivable schema.

    Returns ``None`` on success or an error detail string on validation failure.
    """
    schema = generate_schema(collection_config, receivable=True)
    try:
        jsonschema.validate(body, schema)
    except jsonschema.ValidationError as exc:
        msg: str = exc.message
        return msg
    return None


def _require_auth(event: dict[str, Any], params: dict[str, str]) -> AuthContext:
    """Resolve auth context, requiring authentication for write operations.

    Unauthenticated callers get a 401 response.
    """
    from oapif.auth import AuthError

    auth = resolve_auth_context(event, query_params=params)
    if not auth.authenticated:
        raise AuthError(
            status_code=401,
            message="Authentication required",
            detail="Write operations require a valid JWT token.",
        )
    return auth


# ---------------------------------------------------------------------------
# POST /collections/{collectionId}/items — Create feature (Part 4 §7.1)
# ---------------------------------------------------------------------------


def handle_create_feature(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Create a new feature in a collection.

    Returns 201 Created with a Location header pointing to the new feature.
    """
    collection_id = path_params["collectionId"]
    params = _get_query_params(event)

    # Require authentication for write operations
    auth = _require_auth(event, params)
    require_write_role(auth)

    # Validate collection exists
    col_dal = _get_collection_dal()
    try:
        config = col_dal.get_collection(collection_id)
    except CollectionNotFoundError:
        return error_response(404, "Collection not found", detail=f"Collection '{collection_id}' does not exist.")

    # Parse and validate request body
    try:
        body = _parse_request_body(event)
    except ValueError, json.JSONDecodeError:
        return error_response(400, "Invalid JSON", detail="Request body is not valid JSON.")

    if body is None:
        return error_response(400, "Missing request body", detail="POST request requires a JSON body.")

    # Field-level authorization (editors cannot set visibility)
    check_field_permissions_for_create(auth, body)

    # Schema validation
    validation_error = _validate_feature_body(body, config)
    if validation_error:
        return error_response(422, "Schema validation failed", detail=validation_error)

    feat_dal = _get_feature_dal()
    feature = feat_dal.create_feature(
        collection_id=collection_id,
        feature_data=body,
        organization=auth.organization,
    )

    location = f"{base_url}/collections/{collection_id}/items/{feature.id}"
    geojson = feature.to_geojson()
    geojson["links"] = [
        {"href": location, "rel": "self", "type": "application/geo+json"},
        {
            "href": f"{base_url}/collections/{collection_id}",
            "rel": "collection",
            "type": "application/json",
        },
    ]

    return geojson_response(
        201,
        geojson,
        headers={
            "Location": location,
            "ETag": f'"{feature.etag}"',
        },
    )


# ---------------------------------------------------------------------------
# PUT /collections/{collectionId}/items/{featureId} — Replace feature
# ---------------------------------------------------------------------------


def handle_replace_feature(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Replace a feature entirely (PUT semantics).

    Requires ``If-Match`` header with the current ETag.
    Returns 200 with the updated feature and new ETag.
    """
    collection_id = path_params["collectionId"]
    feature_id = path_params["featureId"]
    params = _get_query_params(event)

    auth = _require_auth(event, params)
    require_write_role(auth)

    # Validate collection exists
    col_dal = _get_collection_dal()
    try:
        config = col_dal.get_collection(collection_id)
    except CollectionNotFoundError:
        return error_response(404, "Collection not found", detail=f"Collection '{collection_id}' does not exist.")

    # Require If-Match
    try:
        if_match = _require_if_match(event)
    except ETagRequiredError:
        return error_response(428, "Precondition Required", detail="If-Match header with ETag is required.")

    # Parse and validate request body
    try:
        body = _parse_request_body(event)
    except ValueError, json.JSONDecodeError:
        return error_response(400, "Invalid JSON", detail="Request body is not valid JSON.")

    if body is None:
        return error_response(400, "Missing request body", detail="PUT request requires a JSON body.")

    validation_error = _validate_feature_body(body, config)
    if validation_error:
        return error_response(422, "Schema validation failed", detail=validation_error)

    # Field-level authorization: fetch existing feature to compare visibility
    feat_dal = _get_feature_dal()
    try:
        existing = feat_dal.get_feature(collection_id, feature_id, auth.organization)
    except FeatureNotFoundError:
        return error_response(404, "Feature not found", detail=f"Feature '{feature_id}' not found.")
    check_field_permissions_for_replace(auth, body, existing.visibility)

    try:
        feature = feat_dal.replace_feature(
            collection_id=collection_id,
            feature_id=feature_id,
            feature_data=body,
            if_match=if_match,
            organization=auth.organization,
        )
    except FeatureNotFoundError:
        return error_response(404, "Feature not found", detail=f"Feature '{feature_id}' not found.")
    except ETagMismatchError:
        return error_response(412, "Precondition Failed", detail="The ETag does not match the current version.")
    except OrganizationImmutableError:
        return error_response(422, "Organization immutable", detail="The 'organization' field cannot be changed.")

    geojson = feature.to_geojson()
    feature_url = f"{base_url}/collections/{collection_id}/items/{feature_id}"
    geojson["links"] = [
        {"href": feature_url, "rel": "self", "type": "application/geo+json"},
        {
            "href": f"{base_url}/collections/{collection_id}",
            "rel": "collection",
            "type": "application/json",
        },
    ]

    return geojson_response(
        200,
        geojson,
        headers={"ETag": f'"{feature.etag}"'},
    )


# ---------------------------------------------------------------------------
# PATCH /collections/{collectionId}/items/{featureId} — Update feature
# ---------------------------------------------------------------------------


def handle_update_feature(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Apply a JSON Merge Patch (RFC 7396) to a feature.

    Requires ``If-Match`` header with the current ETag.
    Returns 200 with the updated feature and new ETag.
    """
    collection_id = path_params["collectionId"]
    feature_id = path_params["featureId"]
    params = _get_query_params(event)

    auth = _require_auth(event, params)
    require_write_role(auth)

    # Validate collection exists
    col_dal = _get_collection_dal()
    try:
        col_dal.get_collection(collection_id)
    except CollectionNotFoundError:
        return error_response(404, "Collection not found", detail=f"Collection '{collection_id}' does not exist.")

    # Require If-Match
    try:
        if_match = _require_if_match(event)
    except ETagRequiredError:
        return error_response(428, "Precondition Required", detail="If-Match header with ETag is required.")

    # Parse request body (no full schema validation for PATCH — partial updates allowed)
    try:
        body = _parse_request_body(event)
    except ValueError, json.JSONDecodeError:
        return error_response(400, "Invalid JSON", detail="Request body is not valid JSON.")

    if body is None:
        return error_response(400, "Missing request body", detail="PATCH request requires a JSON body.")

    # Field-level authorization (editors cannot change visibility)
    check_field_permissions_for_update(auth, body)

    feat_dal = _get_feature_dal()
    try:
        feature = feat_dal.update_feature(
            collection_id=collection_id,
            feature_id=feature_id,
            patch=body,
            if_match=if_match,
            organization=auth.organization,
        )
    except FeatureNotFoundError:
        return error_response(404, "Feature not found", detail=f"Feature '{feature_id}' not found.")
    except ETagMismatchError:
        return error_response(412, "Precondition Failed", detail="The ETag does not match the current version.")
    except OrganizationImmutableError:
        return error_response(422, "Organization immutable", detail="The 'organization' field cannot be changed.")

    geojson = feature.to_geojson()
    feature_url = f"{base_url}/collections/{collection_id}/items/{feature_id}"
    geojson["links"] = [
        {"href": feature_url, "rel": "self", "type": "application/geo+json"},
        {
            "href": f"{base_url}/collections/{collection_id}",
            "rel": "collection",
            "type": "application/json",
        },
    ]

    return geojson_response(
        200,
        geojson,
        headers={"ETag": f'"{feature.etag}"'},
    )


# ---------------------------------------------------------------------------
# DELETE /collections/{collectionId}/items/{featureId} — Delete feature
# ---------------------------------------------------------------------------


def handle_delete_feature(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Soft-delete a feature.

    Requires ``If-Match`` header with the current ETag.
    Returns 204 No Content on success.
    """
    collection_id = path_params["collectionId"]
    feature_id = path_params["featureId"]
    params = _get_query_params(event)

    auth = _require_auth(event, params)
    require_write_role(auth)

    # Require If-Match
    try:
        if_match = _require_if_match(event)
    except ETagRequiredError:
        return error_response(428, "Precondition Required", detail="If-Match header with ETag is required.")

    feat_dal = _get_feature_dal()
    try:
        feat_dal.delete_feature(
            collection_id=collection_id,
            feature_id=feature_id,
            if_match=if_match,
            organization=auth.organization,
        )
    except FeatureNotFoundError:
        return error_response(404, "Feature not found", detail=f"Feature '{feature_id}' not found.")
    except ETagMismatchError:
        return error_response(412, "Precondition Failed", detail="The ETag does not match the current version.")

    return no_content_response()


# ---------------------------------------------------------------------------
# OPTIONS /collections/{collectionId}/items — Supported methods
# ---------------------------------------------------------------------------


def handle_options_items(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Return supported methods for the items endpoint."""
    return no_content_response(
        headers={
            "Allow": "GET, POST, OPTIONS",
            "Accept-Patch": "application/merge-patch+json",
        },
    )


# ---------------------------------------------------------------------------
# OPTIONS /collections/{collectionId}/items/{featureId} — Supported methods
# ---------------------------------------------------------------------------


def handle_options_feature(
    *,
    event: dict[str, Any],
    base_url: str,
    path_params: dict[str, str],
) -> dict[str, Any]:
    """Return supported methods for the single feature endpoint."""
    return no_content_response(
        headers={
            "Allow": "GET, PUT, PATCH, DELETE, OPTIONS",
            "Accept-Patch": "application/merge-patch+json",
        },
    )
