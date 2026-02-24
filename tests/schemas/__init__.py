"""Reference JSON Schemas from OGC API - Features and RFC 7946 (GeoJSON).

These schemas are derived from the normative definitions in:

- **OGC 17-069r4** (OGC API - Features Part 1: Core)
  https://schemas.opengis.net/ogcapi/features/part1/1.0/openapi/schemas/

- **RFC 7946** (The GeoJSON Format) §3

- **JSON Schema 2020-12** meta-schema (for validating generated schemas)

They are used by conformance tests to validate our model outputs
*before* we have live HTTP endpoints.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# GeoJSON Feature (RFC 7946 §3.2)
# ---------------------------------------------------------------------------

GEOJSON_GEOMETRY_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "required": ["type", "coordinates"],
            "properties": {
                "type": {"type": "string", "enum": ["Point"]},
                "coordinates": {"type": "array", "minItems": 2, "items": {"type": "number"}},
            },
        },
        {
            "type": "object",
            "required": ["type", "coordinates"],
            "properties": {
                "type": {"type": "string", "enum": ["MultiPoint"]},
                "coordinates": {
                    "type": "array",
                    "items": {"type": "array", "minItems": 2, "items": {"type": "number"}},
                },
            },
        },
        {
            "type": "object",
            "required": ["type", "coordinates"],
            "properties": {
                "type": {"type": "string", "enum": ["LineString"]},
                "coordinates": {
                    "type": "array",
                    "minItems": 2,
                    "items": {"type": "array", "minItems": 2, "items": {"type": "number"}},
                },
            },
        },
        {
            "type": "object",
            "required": ["type", "coordinates"],
            "properties": {
                "type": {"type": "string", "enum": ["MultiLineString"]},
                "coordinates": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "minItems": 2,
                        "items": {"type": "array", "minItems": 2, "items": {"type": "number"}},
                    },
                },
            },
        },
        {
            "type": "object",
            "required": ["type", "coordinates"],
            "properties": {
                "type": {"type": "string", "enum": ["Polygon"]},
                "coordinates": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "minItems": 4,
                        "items": {"type": "array", "minItems": 2, "items": {"type": "number"}},
                    },
                },
            },
        },
        {
            "type": "object",
            "required": ["type", "coordinates"],
            "properties": {
                "type": {"type": "string", "enum": ["MultiPolygon"]},
                "coordinates": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "minItems": 4,
                            "items": {"type": "array", "minItems": 2, "items": {"type": "number"}},
                        },
                    },
                },
            },
        },
        {"type": "null"},
    ],
}

GEOJSON_FEATURE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "GeoJSON Feature (RFC 7946 §3.2)",
    "type": "object",
    "required": ["type", "geometry", "properties"],
    "properties": {
        "type": {"type": "string", "enum": ["Feature"]},
        "id": {"oneOf": [{"type": "string"}, {"type": "number"}]},
        "geometry": GEOJSON_GEOMETRY_SCHEMA,
        "properties": {"oneOf": [{"type": "object"}, {"type": "null"}]},
    },
}

GEOJSON_FEATURE_COLLECTION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "GeoJSON FeatureCollection (RFC 7946 §3.3)",
    "type": "object",
    "required": ["type", "features"],
    "properties": {
        "type": {"type": "string", "enum": ["FeatureCollection"]},
        "features": {
            "type": "array",
            "items": GEOJSON_FEATURE_SCHEMA,
        },
    },
}

# ---------------------------------------------------------------------------
# OGC API - Features Part 1: Core — Collection metadata (OGC 17-069r4 §7.14)
# ---------------------------------------------------------------------------

_LINK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["href", "rel"],
    "properties": {
        "href": {"type": "string", "format": "uri-reference"},
        "rel": {"type": "string"},
        "type": {"type": "string"},
        "hreflang": {"type": "string"},
        "title": {"type": "string"},
        "length": {"type": "integer"},
    },
}

_EXTENT_SPATIAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bbox": {
            "type": "array",
            "items": {
                "type": "array",
                "minItems": 4,
                "items": {"type": "number"},
            },
        },
        "crs": {"type": "string"},
    },
}

_EXTENT_TEMPORAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "interval": {
            "type": "array",
            "items": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {"oneOf": [{"type": "string"}, {"type": "null"}]},
            },
        },
    },
}

_EXTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "spatial": _EXTENT_SPATIAL_SCHEMA,
        "temporal": _EXTENT_TEMPORAL_SCHEMA,
    },
}

OGC_COLLECTION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "OGC API Features Collection (OGC 17-069r4 §7.14)",
    "type": "object",
    "required": ["id", "links"],
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "links": {"type": "array", "items": _LINK_SCHEMA},
        "extent": _EXTENT_SCHEMA,
        "itemType": {"type": "string"},
        "crs": {"type": "array", "items": {"type": "string"}},
        "storageCrs": {"type": "string"},
    },
}

OGC_COLLECTIONS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "OGC API Features Collections (OGC 17-069r4 §7.13)",
    "type": "object",
    "required": ["links", "collections"],
    "properties": {
        "links": {"type": "array", "items": _LINK_SCHEMA},
        "collections": {"type": "array", "items": OGC_COLLECTION_SCHEMA},
    },
}

# ---------------------------------------------------------------------------
# OGC API - Features Part 1: Core — Landing Page (OGC 17-069r4 §7.2)
# ---------------------------------------------------------------------------

OGC_LANDING_PAGE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "OGC API Features Landing Page (OGC 17-069r4 §7.2)",
    "type": "object",
    "required": ["links"],
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "links": {"type": "array", "items": _LINK_SCHEMA},
    },
}

# ---------------------------------------------------------------------------
# OGC API - Features Part 1: Core — Conformance (OGC 17-069r4 §7.4)
# ---------------------------------------------------------------------------

OGC_CONFORMANCE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "OGC API Features Conformance Declaration (OGC 17-069r4 §7.4)",
    "type": "object",
    "required": ["conformsTo"],
    "properties": {
        "conformsTo": {"type": "array", "items": {"type": "string", "format": "uri"}},
    },
}

# ---------------------------------------------------------------------------
# OGC API - Features Part 1: Core — Items response (FeatureCollection+)
# ---------------------------------------------------------------------------

OGC_ITEMS_RESPONSE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "OGC API Features Items Response (OGC 17-069r4 §7.15.4)",
    "type": "object",
    "required": ["type", "features"],
    "properties": {
        "type": {"type": "string", "enum": ["FeatureCollection"]},
        "features": {"type": "array", "items": GEOJSON_FEATURE_SCHEMA},
        "links": {"type": "array", "items": _LINK_SCHEMA},
        "timeStamp": {"type": "string", "format": "date-time"},
        "numberMatched": {"type": "integer", "minimum": 0},
        "numberReturned": {"type": "integer", "minimum": 0},
    },
}
