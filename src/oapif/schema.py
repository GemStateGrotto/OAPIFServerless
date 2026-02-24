"""OGC API - Features Part 5 JSON Schema generation.

Generates JSON Schema documents from :class:`CollectionConfig` for the
``/collections/{collectionId}/schema`` endpoint.

Per OGC 23-058 (Part 5: Schemas), two schema variants are produced:

* **Returnables** — the full schema describing features as returned by the
  API (GET responses).  Includes server-populated read-only fields like
  ``id`` and ``organization``.

* **Receivables** — the schema for features as submitted by clients
  (POST/PUT/PATCH bodies).  Omits read-only fields and marks required
  properties.
"""

from __future__ import annotations

from typing import Any

from oapif.models.collection import CollectionConfig

# Supported GeoJSON geometry types for ``x-ogc-role: primary-geometry``
_GEOJSON_GEOMETRY_TYPES: dict[str, dict[str, Any]] = {
    "Point": {
        "type": "object",
        "required": ["type", "coordinates"],
        "properties": {
            "type": {"type": "string", "enum": ["Point"]},
            "coordinates": {
                "type": "array",
                "minItems": 2,
                "maxItems": 3,
                "items": {"type": "number"},
            },
        },
    },
    "MultiPoint": {
        "type": "object",
        "required": ["type", "coordinates"],
        "properties": {
            "type": {"type": "string", "enum": ["MultiPoint"]},
            "coordinates": {
                "type": "array",
                "items": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 3,
                    "items": {"type": "number"},
                },
            },
        },
    },
    "LineString": {
        "type": "object",
        "required": ["type", "coordinates"],
        "properties": {
            "type": {"type": "string", "enum": ["LineString"]},
            "coordinates": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 3,
                    "items": {"type": "number"},
                },
            },
        },
    },
    "MultiLineString": {
        "type": "object",
        "required": ["type", "coordinates"],
        "properties": {
            "type": {"type": "string", "enum": ["MultiLineString"]},
            "coordinates": {
                "type": "array",
                "items": {
                    "type": "array",
                    "minItems": 2,
                    "items": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 3,
                        "items": {"type": "number"},
                    },
                },
            },
        },
    },
    "Polygon": {
        "type": "object",
        "required": ["type", "coordinates"],
        "properties": {
            "type": {"type": "string", "enum": ["Polygon"]},
            "coordinates": {
                "type": "array",
                "items": {
                    "type": "array",
                    "minItems": 4,
                    "items": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 3,
                        "items": {"type": "number"},
                    },
                },
            },
        },
    },
    "MultiPolygon": {
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
                        "items": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 3,
                            "items": {"type": "number"},
                        },
                    },
                },
            },
        },
    },
}


def _build_geometry_schema(geometry_type: str | None) -> dict[str, Any]:
    """Build a GeoJSON geometry schema.

    Parameters
    ----------
    geometry_type:
        A specific GeoJSON geometry type (e.g. ``"Point"``) or ``None``
        to allow any geometry type.

    Returns
    -------
    dict
        JSON Schema for the geometry, annotated with
        ``x-ogc-role: primary-geometry``.
    """
    geom_schema: dict[str, Any]
    if geometry_type and geometry_type in _GEOJSON_GEOMETRY_TYPES:
        geom_schema = dict(_GEOJSON_GEOMETRY_TYPES[geometry_type])
    else:
        # anyOf all geometry types
        geom_schema = {
            "oneOf": [_GEOJSON_GEOMETRY_TYPES[gt] for gt in _GEOJSON_GEOMETRY_TYPES],
        }

    geom_schema["x-ogc-role"] = "primary-geometry"
    return geom_schema


def _build_properties_schema(
    config: CollectionConfig,
    *,
    receivable: bool = False,
) -> dict[str, Any]:
    """Build the JSON Schema ``properties`` object for feature properties.

    Parameters
    ----------
    config:
        The collection configuration.
    receivable:
        If ``True``, omit read-only server-populated fields.
        If ``False``, include all fields (returnables).
    """
    props: dict[str, Any] = {}

    # User-defined properties from collection schema
    for name, prop_schema in config.properties_schema.items():
        props[name] = prop_schema.to_dict()

    # Server-managed fields
    if not receivable:
        props["organization"] = {
            "type": "string",
            "description": "Owning organization (server-populated, immutable).",
            "readOnly": True,
        }

    # Visibility — always present in returnables; optional in receivables
    visibility_schema: dict[str, Any] = {
        "type": "string",
        "description": "Feature visibility level.",
    }
    if config.visibility_values:
        visibility_schema["enum"] = config.visibility_values
    if not receivable:
        # In returnables, visibility is always present
        props["visibility"] = visibility_schema
    else:
        # In receivables, visibility is settable but optional
        props["visibility"] = visibility_schema

    return props


def generate_schema(
    config: CollectionConfig,
    *,
    receivable: bool = False,
) -> dict[str, Any]:
    """Generate a JSON Schema document for a collection's features.

    Parameters
    ----------
    config:
        The collection configuration defining property schemas.
    receivable:
        If ``True``, generate the *receivable* schema (for POST/PUT/PATCH
        request bodies).  If ``False`` (default), generate the *returnable*
        schema (for GET responses).

    Returns
    -------
    dict
        A JSON Schema document conforming to OGC API - Features Part 5.
    """
    properties_schema = _build_properties_schema(config, receivable=receivable)

    # Required properties
    required_props: list[str] = []
    if receivable:
        required_props = list(config.required_properties)
    else:
        # In returnables, organization and visibility are always present
        required_props = [*config.required_properties, "organization", "visibility"]

    properties_obj: dict[str, Any] = {
        "type": "object",
        "properties": properties_schema,
    }
    if required_props:
        properties_obj["required"] = sorted(set(required_props))

    # Build the full Feature schema
    feature_schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://api.example.com/collections/{config.collection_id}/schema",
        "title": f"{config.title} Feature",
        "description": f"{'Receivable' if receivable else 'Returnable'} schema for features "
        f"in the {config.title} collection.",
        "type": "object",
        "required": ["type", "geometry", "properties"],
        "properties": {
            "type": {
                "type": "string",
                "enum": ["Feature"],
            },
            "id": {
                "type": "string",
                "description": "Server-generated unique feature identifier.",
                "readOnly": True,
            },
            "geometry": _build_geometry_schema(config.geometry_type),
            "properties": properties_obj,
        },
    }

    # In the receivable schema, id is not required (server-generated)
    if receivable:
        feature_schema["required"] = ["type", "geometry", "properties"]
        # Remove readOnly from id since clients shouldn't send it
        del feature_schema["properties"]["id"]
    else:
        feature_schema["required"] = ["type", "id", "geometry", "properties"]

    return feature_schema
