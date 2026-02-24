"""Cursor-based pagination for DynamoDB queries.

Cursors are opaque, URL-safe tokens that encode a DynamoDB
``ExclusiveStartKey``.  The client receives the cursor in a response
and passes it back to fetch the next page.
"""

from __future__ import annotations

import base64
import json
from typing import Any


def encode_cursor(last_evaluated_key: dict[str, Any]) -> str:
    """Encode a DynamoDB ``LastEvaluatedKey`` into an opaque cursor string."""
    payload = json.dumps(last_evaluated_key, sort_keys=True)
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> dict[str, Any] | None:
    """Decode an opaque cursor string back to a DynamoDB ``ExclusiveStartKey``.

    Returns ``None`` if the cursor is invalid or cannot be decoded.
    """
    try:
        payload = base64.urlsafe_b64decode(cursor.encode()).decode()
        result: dict[str, Any] = json.loads(payload)
        if not isinstance(result, dict):
            return None
        return result
    except ValueError, json.JSONDecodeError:
        return None
