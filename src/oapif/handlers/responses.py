"""HTTP response helpers for Lambda handlers.

Centralizes response construction so handlers return consistent
API Gateway v2 response structures with proper content types and headers.
"""

from __future__ import annotations

import json
from typing import Any


def json_response(
    status_code: int,
    body: dict[str, Any] | list[Any],
    *,
    content_type: str = "application/json",
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build an API Gateway v2 JSON response.

    Parameters
    ----------
    status_code:
        HTTP status code.
    body:
        Serializable response body.
    content_type:
        Content-Type header value.
    headers:
        Additional headers to include.
    """
    resp_headers: dict[str, str] = {
        "Content-Type": content_type,
    }
    if headers:
        resp_headers.update(headers)

    return {
        "statusCode": status_code,
        "headers": resp_headers,
        "body": json.dumps(body, default=str),
    }


def geojson_response(
    status_code: int,
    body: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build an API Gateway v2 GeoJSON response.

    Parameters
    ----------
    status_code:
        HTTP status code.
    body:
        GeoJSON response body.
    headers:
        Additional headers to include.
    """
    return json_response(
        status_code,
        body,
        content_type="application/geo+json",
        headers=headers,
    )


def no_content_response(
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build an API Gateway v2 204 No Content response.

    Parameters
    ----------
    headers:
        Additional headers to include (e.g. ETag).
    """
    resp_headers: dict[str, str] = {}
    if headers:
        resp_headers.update(headers)
    return {
        "statusCode": 204,
        "headers": resp_headers,
        "body": "",
    }


def error_response(
    status_code: int,
    title: str,
    *,
    detail: str = "",
) -> dict[str, Any]:
    """Build an RFC 9457 Problem Details error response.

    Parameters
    ----------
    status_code:
        HTTP status code.
    title:
        Short, human-readable summary.
    detail:
        Longer explanation (optional).
    """
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
    }
    if detail:
        body["detail"] = detail

    return json_response(
        status_code,
        body,
        content_type="application/problem+json",
    )
