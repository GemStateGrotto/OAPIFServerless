"""Collection configuration and schema models.

DynamoDB Config Table Schema
-----------------------------
PK: ``COLLECTION#{collection_id}``
SK: ``CONFIG``

Each item stores the full collection configuration including title,
description, spatial/temporal extent, feature property schema, allowed
visibility values, geometry type constraints, and organization access
control mappings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from oapif.models.feature import decimal_to_python, python_to_dynamodb

# ---------------------------------------------------------------------------
# Sub-models for collection extent
# ---------------------------------------------------------------------------


@dataclass
class SpatialExtent:
    """Spatial extent of a collection (OGC bbox).

    ``bbox`` is a list of bounding boxes in ``[west, south, east, north]``
    order (WGS 84).  Typically a single bbox covering the whole collection.
    """

    bbox: list[list[float]] = field(default_factory=lambda: [[-180.0, -90.0, 180.0, 90.0]])
    crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

    def to_dict(self) -> dict[str, Any]:
        return {"bbox": self.bbox, "crs": self.crs}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpatialExtent:
        bbox_raw = data.get("bbox", [[-180.0, -90.0, 180.0, 90.0]])
        bbox = [[float(v) for v in box] for box in bbox_raw]
        return cls(bbox=bbox, crs=data.get("crs", cls.crs))


@dataclass
class TemporalExtent:
    """Temporal extent of a collection.

    ``interval`` is a list of ``[start, end]`` pairs (ISO 8601 or ``None``
    for open-ended).
    """

    interval: list[list[str | None]] = field(default_factory=lambda: [[None, None]])

    def to_dict(self) -> dict[str, Any]:
        return {"interval": self.interval}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemporalExtent:
        return cls(interval=data.get("interval", [[None, None]]))


@dataclass
class CollectionExtent:
    """Combined spatial and temporal extent."""

    spatial: SpatialExtent = field(default_factory=SpatialExtent)
    temporal: TemporalExtent = field(default_factory=TemporalExtent)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spatial": self.spatial.to_dict(),
            "temporal": self.temporal.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CollectionExtent:
        return cls(
            spatial=SpatialExtent.from_dict(data.get("spatial", {})),
            temporal=TemporalExtent.from_dict(data.get("temporal", {})),
        )


# ---------------------------------------------------------------------------
# Property schema definition
# ---------------------------------------------------------------------------


@dataclass
class PropertySchema:
    """Schema definition for a single feature property.

    Maps directly to a JSON Schema property definition for OGC Part 5.
    """

    type: str  # "string", "number", "integer", "boolean", "array", "object"
    description: str = ""
    enum: list[Any] | None = None
    format: str | None = None  # e.g. "date-time", "date", "uri"
    min_value: float | None = None  # JSON Schema "minimum"
    max_value: float | None = None  # JSON Schema "maximum"
    min_length: int | None = None
    max_length: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type}
        if self.description:
            d["description"] = self.description
        if self.enum is not None:
            d["enum"] = self.enum
        if self.format is not None:
            d["format"] = self.format
        if self.min_value is not None:
            d["minimum"] = self.min_value
        if self.max_value is not None:
            d["maximum"] = self.max_value
        if self.min_length is not None:
            d["minLength"] = self.min_length
        if self.max_length is not None:
            d["maxLength"] = self.max_length
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PropertySchema:
        return cls(
            type=data.get("type", "string"),
            description=data.get("description", ""),
            enum=data.get("enum"),
            format=data.get("format"),
            min_value=_to_float_or_none(data.get("minimum")),
            max_value=_to_float_or_none(data.get("maximum")),
            min_length=_to_int_or_none(data.get("minLength")),
            max_length=_to_int_or_none(data.get("maxLength")),
        )


# ---------------------------------------------------------------------------
# Organization access control mapping
# ---------------------------------------------------------------------------


@dataclass
class OrgAccessConfig:
    """Per-organization access configuration for a collection.

    Maps the organization name to its Cognito group and visibility-level
    access groups.
    """

    cognito_group: str  # e.g. "org:GemStateGrotto"
    access_groups: dict[str, str] = field(default_factory=dict)
    # e.g. {"members": "GemStateGrotto:members", "restricted": "GemStateGrotto:restricted"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "cognito_group": self.cognito_group,
            "access_groups": self.access_groups,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrgAccessConfig:
        return cls(
            cognito_group=data.get("cognito_group", ""),
            access_groups=data.get("access_groups", {}),
        )


# ---------------------------------------------------------------------------
# Main collection configuration model
# ---------------------------------------------------------------------------


@dataclass
class CollectionConfig:
    """Full configuration for an OGC API - Features collection.

    Stored as a single item in the DynamoDB config table.
    """

    collection_id: str
    title: str
    description: str = ""
    extent: CollectionExtent = field(default_factory=CollectionExtent)
    properties_schema: dict[str, PropertySchema] = field(default_factory=dict)
    required_properties: list[str] = field(default_factory=list)
    visibility_values: list[str] = field(default_factory=lambda: ["public", "members", "restricted"])
    geometry_type: str | None = None  # None = any geometry type allowed
    organizations: dict[str, OrgAccessConfig] = field(default_factory=dict)
    crs: list[str] = field(default_factory=lambda: ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"])
    storage_crs: str = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
    item_type: str = "feature"
    links: list[dict[str, str]] = field(default_factory=list)

    # --- Key helpers ---

    @staticmethod
    def make_pk(collection_id: str) -> str:
        """Build the DynamoDB partition key for the config table."""
        return f"COLLECTION#{collection_id}"

    @staticmethod
    def make_sk() -> str:
        """Build the DynamoDB sort key for a collection config item."""
        return "CONFIG"

    # --- Serialization ---

    def to_dynamodb_item(self) -> dict[str, Any]:
        """Serialize to a DynamoDB item dict."""
        props_schema: dict[str, Any] = {
            name: python_to_dynamodb(schema.to_dict()) for name, schema in self.properties_schema.items()
        }
        orgs: dict[str, Any] = {name: python_to_dynamodb(org.to_dict()) for name, org in self.organizations.items()}
        item: dict[str, Any] = {
            "PK": self.make_pk(self.collection_id),
            "SK": self.make_sk(),
            "collection_id": self.collection_id,
            "title": self.title,
            "description": self.description,
            "extent": python_to_dynamodb(self.extent.to_dict()),
            "properties_schema": props_schema,
            "required_properties": self.required_properties,
            "visibility_values": self.visibility_values,
            "organizations": orgs,
            "crs": self.crs,
            "storage_crs": self.storage_crs,
            "item_type": self.item_type,
            "links": python_to_dynamodb(self.links),
        }
        if self.geometry_type is not None:
            item["geometry_type"] = self.geometry_type
        return item

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> CollectionConfig:
        """Deserialize from a DynamoDB item dict."""
        item = decimal_to_python(item)

        props_schema: dict[str, PropertySchema] = {}
        for name, schema_dict in item.get("properties_schema", {}).items():
            props_schema[name] = PropertySchema.from_dict(schema_dict)

        orgs: dict[str, OrgAccessConfig] = {}
        for name, org_dict in item.get("organizations", {}).items():
            orgs[name] = OrgAccessConfig.from_dict(org_dict)

        return cls(
            collection_id=item["collection_id"],
            title=item.get("title", ""),
            description=item.get("description", ""),
            extent=CollectionExtent.from_dict(item.get("extent", {})),
            properties_schema=props_schema,
            required_properties=item.get("required_properties", []),
            visibility_values=item.get("visibility_values", ["public", "members", "restricted"]),
            geometry_type=item.get("geometry_type"),
            organizations=orgs,
            crs=item.get("crs", ["http://www.opengis.net/def/crs/OGC/1.3/CRS84"]),
            storage_crs=item.get("storage_crs", "http://www.opengis.net/def/crs/OGC/1.3/CRS84"),
            item_type=item.get("item_type", "feature"),
            links=item.get("links", []),
        )

    def to_oapif_metadata(self, base_url: str = "") -> dict[str, Any]:
        """Serialize to OGC API - Features collection metadata (JSON).

        Returns the collection description object as specified in
        OGC 17-069r4 §7.14.
        """
        meta: dict[str, Any] = {
            "id": self.collection_id,
            "title": self.title,
            "description": self.description,
            "itemType": self.item_type,
            "extent": self.extent.to_dict(),
            "crs": self.crs,
            "storageCrs": self.storage_crs,
        }

        links: list[dict[str, str]] = []
        if base_url:
            col_url = f"{base_url}/collections/{self.collection_id}"
            links.extend(
                [
                    {"href": col_url, "rel": "self", "type": "application/json"},
                    {"href": f"{col_url}/items", "rel": "items", "type": "application/geo+json"},
                    {"href": f"{col_url}/schema", "rel": "describedby", "type": "application/schema+json"},
                ]
            )
        links.extend(self.links)
        meta["links"] = links

        return meta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_float_or_none(value: Any) -> float | None:
    """Convert a value to float, returning None if value is None."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _to_int_or_none(value: Any) -> int | None:
    """Convert a value to int, returning None if value is None."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return int(value)
    return int(value)
