"""Feature, change tracking, and query result models.

DynamoDB Table Schema (Features Table)
--------------------------------------
PK: ``{organization}#COLLECTION#{collection_id}``
SK: ``FEATURE#{feature_id}``

Additional attributes stored per item:
  feature_id, collection_id, organization, visibility, geometry,
  properties, etag, created_at, updated_at, deleted

DynamoDB Table Schema (Changes Table)
-------------------------------------
PK: ``{organization}#COLLECTION#{collection_id}``
SK: ``CHANGE#{iso_timestamp}#{feature_id}``

Each change record captures the operation type, timestamp, and a
snapshot of the feature after the mutation (or before, for deletes).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def generate_feature_id() -> str:
    """Generate a new unique feature ID (UUID v4)."""
    return str(uuid.uuid4())


def generate_etag() -> str:
    """Generate a new opaque ETag value (UUID v4)."""
    return str(uuid.uuid4())


def utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def decimal_to_python(obj: Any) -> Any:
    """Recursively convert DynamoDB ``Decimal`` values to ``int`` or ``float``."""
    if isinstance(obj, Decimal):
        if obj == int(obj):
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: decimal_to_python(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decimal_to_python(v) for v in obj]
    return obj


def python_to_dynamodb(obj: Any) -> Any:
    """Recursively convert Python ``float`` values to ``Decimal`` for DynamoDB.

    The boto3 Table resource rejects native floats; they must be
    ``Decimal`` instances.
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: python_to_dynamodb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [python_to_dynamodb(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Feature model
# ---------------------------------------------------------------------------


@dataclass
class Feature:
    """Internal representation of a GeoJSON Feature with server metadata.

    ``organization`` and ``visibility`` are stored as top-level DynamoDB
    attributes for efficient filtering, and are injected into ``properties``
    when converting to GeoJSON for API responses.
    """

    id: str
    collection_id: str
    organization: str
    visibility: str = "public"
    geometry: dict[str, Any] | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    etag: str = ""
    created_at: str = ""
    updated_at: str = ""
    deleted: bool = False

    # --- Key helpers ---

    @staticmethod
    def make_pk(organization: str, collection_id: str) -> str:
        """Build the DynamoDB partition key for the features table."""
        return f"{organization}#COLLECTION#{collection_id}"

    @staticmethod
    def make_sk(feature_id: str) -> str:
        """Build the DynamoDB sort key for a feature item."""
        return f"FEATURE#{feature_id}"

    # --- Serialization ---

    def to_dynamodb_item(self) -> dict[str, Any]:
        """Serialize to a DynamoDB item dict.

        Floats are converted to ``Decimal`` because the boto3 Table
        resource does not accept native Python floats.
        """
        item: dict[str, Any] = {
            "PK": self.make_pk(self.organization, self.collection_id),
            "SK": self.make_sk(self.id),
            "feature_id": self.id,
            "collection_id": self.collection_id,
            "organization": self.organization,
            "visibility": self.visibility,
            "properties": python_to_dynamodb(self.properties),
            "etag": self.etag,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted": self.deleted,
        }
        if self.geometry is not None:
            item["geometry"] = python_to_dynamodb(self.geometry)
        return item

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> Feature:
        """Deserialize from a DynamoDB item dict."""
        return cls(
            id=item["feature_id"],
            collection_id=item["collection_id"],
            organization=item["organization"],
            visibility=item.get("visibility", "public"),
            geometry=decimal_to_python(item.get("geometry")),
            properties=decimal_to_python(item.get("properties", {})),
            etag=item.get("etag", ""),
            created_at=item.get("created_at", ""),
            updated_at=item.get("updated_at", ""),
            deleted=item.get("deleted", False),
        )

    def to_geojson(self) -> dict[str, Any]:
        """Serialize to a GeoJSON Feature dict for API responses.

        ``organization`` and ``visibility`` are injected into ``properties``
        so consumers see them as standard feature attributes.
        """
        props = dict(self.properties)
        props["organization"] = self.organization
        props["visibility"] = self.visibility
        return {
            "type": "Feature",
            "id": self.id,
            "geometry": self.geometry,
            "properties": props,
        }


# ---------------------------------------------------------------------------
# Change tracking model
# ---------------------------------------------------------------------------


@dataclass
class ChangeRecord:
    """Append-only audit record for a feature mutation."""

    collection_id: str
    feature_id: str
    organization: str
    operation: str  # CREATE | REPLACE | UPDATE | DELETE
    timestamp: str  # ISO 8601
    feature_snapshot: dict[str, Any] | None = None

    @staticmethod
    def make_pk(organization: str, collection_id: str) -> str:
        """Build the DynamoDB partition key for the changes table."""
        return f"{organization}#COLLECTION#{collection_id}"

    def make_sk(self) -> str:
        """Build the DynamoDB sort key for a change record."""
        return f"CHANGE#{self.timestamp}#{self.feature_id}"

    def to_dynamodb_item(self) -> dict[str, Any]:
        """Serialize to a DynamoDB item dict."""
        item: dict[str, Any] = {
            "PK": self.make_pk(self.organization, self.collection_id),
            "SK": self.make_sk(),
            "collection_id": self.collection_id,
            "feature_id": self.feature_id,
            "organization": self.organization,
            "operation": self.operation,
            "timestamp": self.timestamp,
        }
        if self.feature_snapshot is not None:
            item["feature_snapshot"] = python_to_dynamodb(self.feature_snapshot)
        return item


# ---------------------------------------------------------------------------
# Query result
# ---------------------------------------------------------------------------


@dataclass
class QueryResult:
    """Result of a paginated feature query."""

    features: list[Feature]
    next_cursor: str | None = None
    number_matched: int | None = None
