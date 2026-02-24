"""Lambda request handler for OGC API - Features endpoints.

Handles API Gateway HTTP API (v2) events, routing requests to the
appropriate endpoint functions.  This is the entry point configured in
``deploy/stacks/api.py`` as ``oapif.handlers.main.handler``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from oapif.auth import AuthError
from oapif.handlers.responses import error_response
from oapif.handlers.routes import (
    handle_api,
    handle_collections,
    handle_conformance,
    handle_feature,
    handle_items,
    handle_landing_page,
    handle_schema,
    handle_single_collection,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Pre-compiled route patterns (order matters — most specific first)
_ROUTES: list[tuple[str, re.Pattern[str], Any]] = [
    ("GET", re.compile(r"^/collections/(?P<collectionId>[^/]+)/items/(?P<featureId>[^/]+)$"), handle_feature),
    ("GET", re.compile(r"^/collections/(?P<collectionId>[^/]+)/items$"), handle_items),
    ("GET", re.compile(r"^/collections/(?P<collectionId>[^/]+)/schema$"), handle_schema),
    ("GET", re.compile(r"^/collections/(?P<collectionId>[^/]+)$"), handle_single_collection),
    ("GET", re.compile(r"^/collections$"), handle_collections),
    ("GET", re.compile(r"^/conformance$"), handle_conformance),
    ("GET", re.compile(r"^/api$"), handle_api),
    ("GET", re.compile(r"^/$"), handle_landing_page),
]


def _extract_base_url(event: dict[str, Any]) -> str:
    """Derive the public base URL from the API Gateway event.

    Uses the ``requestContext.domainName`` and ``stage`` from the event.
    For the ``$default`` stage the stage prefix is omitted.
    """
    rc = event.get("requestContext", {})
    domain = rc.get("domainName", "localhost")
    stage = rc.get("stage", "$default")

    # HTTP API $default stage has no path prefix
    if stage == "$default":
        return f"https://{domain}"
    return f"https://{domain}/{stage}"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda handler for API Gateway HTTP API v2 events.

    Parameters
    ----------
    event:
        API Gateway HTTP API v2 payload.
    context:
        Lambda context object (unused).

    Returns
    -------
    dict
        API Gateway-compatible response with ``statusCode``, ``headers``,
        and ``body``.
    """
    logger.info("Incoming event", extra={"event": json.dumps(event, default=str)})

    rc = event.get("requestContext", {})
    http = rc.get("http", {})
    method = http.get("method", "GET").upper()
    raw_path = event.get("rawPath", "/")

    # Strip trailing slash (except root)
    path = raw_path.rstrip("/") if raw_path != "/" else raw_path

    base_url = _extract_base_url(event)

    for route_method, pattern, route_handler in _ROUTES:
        if method != route_method:
            continue
        match = pattern.match(path)
        if match:
            try:
                result: dict[str, Any] = route_handler(
                    event=event,
                    base_url=base_url,
                    path_params=match.groupdict(),
                )
                return result
            except AuthError as exc:
                return error_response(exc.status_code, exc.message, detail=exc.detail)
            except Exception:
                logger.exception("Unhandled error in route handler")
                return error_response(500, "Internal Server Error")

    return error_response(404, "Not Found", detail=f"No route matched {method} {path}")
