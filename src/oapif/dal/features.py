"""Data Access Layer for feature CRUD operations against DynamoDB.

All DynamoDB interactions for features and change tracking go through
:class:`FeatureDAL`.  Lambda handlers must never call DynamoDB directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from oapif.dal.exceptions import ETagMismatchError, FeatureNotFoundError
from oapif.dal.pagination import decode_cursor, encode_cursor
from oapif.models.feature import (
    ChangeRecord,
    Feature,
    QueryResult,
    generate_etag,
    generate_feature_id,
    utcnow_iso,
)

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBServiceResource

logger = logging.getLogger(__name__)

# Safety limit for internal pagination loops when post-filtering (e.g. bbox)
# results in fewer items than the requested limit per DynamoDB page.
_MAX_QUERY_PAGES = 50


class FeatureDAL:
    """Data access layer for feature CRUD operations.

    Parameters
    ----------
    dynamodb_resource:
        A ``boto3.resource("dynamodb")`` instance.
    features_table_name:
        Name of the DynamoDB features table.
    changes_table_name:
        Name of the DynamoDB change-tracking table.
    """

    def __init__(
        self,
        dynamodb_resource: DynamoDBServiceResource,
        features_table_name: str,
        changes_table_name: str,
    ) -> None:
        self._resource = dynamodb_resource
        self._features_table = dynamodb_resource.Table(features_table_name)
        self._changes_table = dynamodb_resource.Table(changes_table_name)

    # ------------------------------------------------------------------
    # CREATE
    # ------------------------------------------------------------------

    def create_feature(
        self,
        collection_id: str,
        feature_data: dict[str, Any],
        organization: str,
        visibility: str = "public",
    ) -> Feature:
        """Create a new feature, assigning it an ID and ETag.

        Writes to both the features table and the change log.

        Parameters
        ----------
        collection_id:
            Target collection identifier.
        feature_data:
            Dict containing ``geometry`` and ``properties`` keys (GeoJSON-like).
        organization:
            Owning organization (server-populated, immutable).
        visibility:
            Default visibility level.  May be overridden if the incoming
            ``properties`` contains a ``visibility`` key.

        Returns
        -------
        Feature
            The newly created feature with assigned ID and ETag.
        """
        now = utcnow_iso()

        # Extract properties; pull out server-managed fields
        properties = dict(feature_data.get("properties") or {})
        visibility = properties.pop("visibility", visibility)
        properties.pop("organization", None)  # Never trust client-supplied org

        feature = Feature(
            id=generate_feature_id(),
            collection_id=collection_id,
            organization=organization,
            visibility=visibility,
            geometry=feature_data.get("geometry"),
            properties=properties,
            etag=generate_etag(),
            created_at=now,
            updated_at=now,
            deleted=False,
        )

        # Prevent overwriting an existing item (UUID collision guard)
        self._features_table.put_item(
            Item=feature.to_dynamodb_item(),
            ConditionExpression=Attr("PK").not_exists(),
        )

        self._write_change(feature, "CREATE")

        logger.info(
            "Created feature",
            extra={
                "collection_id": collection_id,
                "feature_id": feature.id,
                "organization": organization,
            },
        )
        return feature

    # ------------------------------------------------------------------
    # READ (single)
    # ------------------------------------------------------------------

    def get_feature(
        self,
        collection_id: str,
        feature_id: str,
        organization: str,
    ) -> Feature:
        """Retrieve a single feature by ID.

        Parameters
        ----------
        collection_id:
            Collection containing the feature.
        feature_id:
            The feature's unique identifier.
        organization:
            Organization scope (hard tenant boundary).

        Returns
        -------
        Feature
            The feature with its current ETag.

        Raises
        ------
        FeatureNotFoundError
            If the feature does not exist or has been soft-deleted.
        """
        response = self._features_table.get_item(
            Key={
                "PK": Feature.make_pk(organization, collection_id),
                "SK": Feature.make_sk(feature_id),
            },
        )

        item = response.get("Item")
        if item is None:
            raise FeatureNotFoundError(collection_id, feature_id)

        feature = Feature.from_dynamodb_item(item)
        if feature.deleted:
            raise FeatureNotFoundError(collection_id, feature_id)

        return feature

    # ------------------------------------------------------------------
    # READ (query / list)
    # ------------------------------------------------------------------

    def query_features(
        self,
        collection_id: str,
        organization: str,
        *,
        limit: int = 10,
        cursor: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        datetime_filter: str | None = None,
        property_filters: dict[str, Any] | None = None,
        visibility_filter: list[str] | None = None,
    ) -> QueryResult:
        """Query features in a collection with pagination and filtering.

        Server-side DynamoDB filters are applied for ``deleted``,
        ``visibility``, and ``property_filters``.  ``bbox`` filtering is
        applied post-query in Python (spatial indexing is planned for Phase 14).

        Parameters
        ----------
        collection_id:
            Collection to query.
        organization:
            Organization scope.
        limit:
            Maximum number of features to return (page size).
        cursor:
            Opaque pagination token from a previous ``QueryResult``.
        bbox:
            Bounding box ``(west, south, east, north)`` in WGS 84.
        datetime_filter:
            ISO 8601 instant or interval — *not yet implemented*.
        property_filters:
            Key-value pairs to match against feature properties.
        visibility_filter:
            Allowed visibility levels for the caller (e.g. ``["public"]``).

        Returns
        -------
        QueryResult
            Features and an optional cursor for the next page.
        """
        if datetime_filter is not None:
            logger.warning("datetime_filter is accepted but not yet implemented")

        pk = Feature.make_pk(organization, collection_id)
        key_condition = Key("PK").eq(pk) & Key("SK").begins_with("FEATURE#")

        # Always exclude soft-deleted items
        filter_expr: Any = Attr("deleted").ne(True)

        if visibility_filter:
            filter_expr = filter_expr & Attr("visibility").is_in(visibility_filter)

        if property_filters:
            for prop_name, prop_value in property_filters.items():
                filter_expr = filter_expr & Attr(f"properties.{prop_name}").eq(prop_value)

        # Decode incoming cursor
        exclusive_start_key = decode_cursor(cursor) if cursor else None

        collected: list[Feature] = []
        has_more_in_dynamo = True
        pages = 0

        while len(collected) < limit and has_more_in_dynamo and pages < _MAX_QUERY_PAGES:
            pages += 1

            query_kwargs: dict[str, Any] = {
                "KeyConditionExpression": key_condition,
                "FilterExpression": filter_expr,
            }
            if exclusive_start_key:
                query_kwargs["ExclusiveStartKey"] = exclusive_start_key

            response = self._features_table.query(**query_kwargs)
            items = [Feature.from_dynamodb_item(i) for i in response.get("Items", [])]

            # Post-filter: bounding box (Phase 14 will use spatial index)
            if bbox:
                items = _filter_by_bbox(items, bbox)

            collected.extend(items)

            last_key = response.get("LastEvaluatedKey")
            if last_key:
                exclusive_start_key = last_key
            else:
                has_more_in_dynamo = False

        # Trim to requested limit
        features = collected[:limit]

        # Build cursor from the last returned feature's key so that
        # post-filtered results paginate correctly.
        next_cursor = None
        if (has_more_in_dynamo or len(collected) > limit) and features:
            last = features[-1]
            cursor_key = {
                "PK": Feature.make_pk(organization, collection_id),
                "SK": Feature.make_sk(last.id),
            }
            next_cursor = encode_cursor(cursor_key)

        return QueryResult(features=features, next_cursor=next_cursor)

    # ------------------------------------------------------------------
    # REPLACE (PUT)
    # ------------------------------------------------------------------

    def replace_feature(
        self,
        collection_id: str,
        feature_id: str,
        feature_data: dict[str, Any],
        if_match: str,
        organization: str,
    ) -> Feature:
        """Replace a feature entirely (PUT semantics).

        Parameters
        ----------
        collection_id:
            Collection containing the feature.
        feature_id:
            Feature to replace.
        feature_data:
            Complete GeoJSON-like dict with ``geometry`` and ``properties``.
        if_match:
            ETag the client believes is current (``If-Match`` header value).
        organization:
            Organization scope.

        Returns
        -------
        Feature
            The replaced feature with a new ETag.

        Raises
        ------
        FeatureNotFoundError
            If the feature does not exist or is deleted.
        ETagMismatchError
            If the provided ETag does not match.
        """
        current = self._get_feature_or_raise(collection_id, feature_id, organization, if_match)

        now = utcnow_iso()
        new_etag = generate_etag()

        properties = dict(feature_data.get("properties") or {})
        visibility = properties.pop("visibility", current.visibility)
        properties.pop("organization", None)

        updated = Feature(
            id=feature_id,
            collection_id=collection_id,
            organization=organization,
            visibility=visibility,
            geometry=feature_data.get("geometry"),
            properties=properties,
            etag=new_etag,
            created_at=current.created_at,
            updated_at=now,
            deleted=False,
        )

        self._conditional_put(updated, if_match)
        self._write_change(updated, "REPLACE")

        logger.info(
            "Replaced feature",
            extra={"collection_id": collection_id, "feature_id": feature_id},
        )
        return updated

    # ------------------------------------------------------------------
    # UPDATE (PATCH — JSON Merge Patch)
    # ------------------------------------------------------------------

    def update_feature(
        self,
        collection_id: str,
        feature_id: str,
        patch: dict[str, Any],
        if_match: str,
        organization: str,
    ) -> Feature:
        """Apply a JSON Merge Patch (RFC 7396) to a feature.

        Parameters
        ----------
        collection_id:
            Collection containing the feature.
        feature_id:
            Feature to update.
        patch:
            Dict with optional ``geometry`` and/or ``properties`` keys.
            Within ``properties``, ``null`` values remove keys.
        if_match:
            Current ETag for conditional write.
        organization:
            Organization scope.

        Returns
        -------
        Feature
            The updated feature with a new ETag.

        Raises
        ------
        FeatureNotFoundError
            If the feature does not exist or is deleted.
        ETagMismatchError
            If the provided ETag does not match.
        """
        current = self._get_feature_or_raise(collection_id, feature_id, organization, if_match)

        # Merge geometry
        new_geometry = current.geometry
        if "geometry" in patch:
            new_geometry = patch["geometry"]

        # Merge properties
        new_properties = dict(current.properties)
        if "properties" in patch:
            new_properties = _json_merge_patch(new_properties, patch["properties"])

        # Extract server-managed visibility from merged properties
        new_visibility = new_properties.pop("visibility", current.visibility)
        new_properties.pop("organization", None)

        now = utcnow_iso()
        new_etag = generate_etag()

        updated = Feature(
            id=feature_id,
            collection_id=collection_id,
            organization=organization,
            visibility=new_visibility,
            geometry=new_geometry,
            properties=new_properties,
            etag=new_etag,
            created_at=current.created_at,
            updated_at=now,
            deleted=False,
        )

        self._conditional_put(updated, if_match)
        self._write_change(updated, "UPDATE")

        logger.info(
            "Updated feature",
            extra={"collection_id": collection_id, "feature_id": feature_id},
        )
        return updated

    # ------------------------------------------------------------------
    # DELETE (soft)
    # ------------------------------------------------------------------

    def delete_feature(
        self,
        collection_id: str,
        feature_id: str,
        if_match: str,
        organization: str,
    ) -> None:
        """Soft-delete a feature.

        The item remains in DynamoDB with ``deleted=True`` and will not
        appear in queries or direct lookups.

        Parameters
        ----------
        collection_id:
            Collection containing the feature.
        feature_id:
            Feature to delete.
        if_match:
            Current ETag for conditional write.
        organization:
            Organization scope.

        Raises
        ------
        FeatureNotFoundError
            If the feature does not exist or is already deleted.
        ETagMismatchError
            If the provided ETag does not match.
        """
        current = self._get_feature_or_raise(collection_id, feature_id, organization, if_match)

        now = utcnow_iso()

        try:
            self._features_table.update_item(
                Key={
                    "PK": Feature.make_pk(organization, collection_id),
                    "SK": Feature.make_sk(feature_id),
                },
                UpdateExpression="SET deleted = :t, updated_at = :now",
                ConditionExpression=Attr("etag").eq(if_match) & Attr("deleted").ne(True),
                ExpressionAttributeValues={":t": True, ":now": now},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ETagMismatchError(if_match) from exc
            raise

        # Record the deleted feature's last known state
        change = ChangeRecord(
            collection_id=collection_id,
            feature_id=feature_id,
            organization=organization,
            operation="DELETE",
            timestamp=now,
            feature_snapshot=current.to_geojson(),
        )
        self._changes_table.put_item(Item=change.to_dynamodb_item())

        logger.info(
            "Deleted feature",
            extra={"collection_id": collection_id, "feature_id": feature_id},
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_feature_or_raise(
        self,
        collection_id: str,
        feature_id: str,
        organization: str,
        if_match: str,
    ) -> Feature:
        """Read a feature and check the ETag precondition."""
        feature = self.get_feature(collection_id, feature_id, organization)
        if feature.etag != if_match:
            raise ETagMismatchError(if_match)
        return feature

    def _conditional_put(self, feature: Feature, expected_etag: str) -> None:
        """Put a feature item with an ETag condition expression.

        Raises :class:`ETagMismatchError` if the condition fails (race).
        """
        try:
            self._features_table.put_item(
                Item=feature.to_dynamodb_item(),
                ConditionExpression=Attr("etag").eq(expected_etag) & Attr("deleted").ne(True),
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ETagMismatchError(expected_etag) from exc
            raise

    def _write_change(self, feature: Feature, operation: str) -> None:
        """Write a change-tracking record for a feature mutation."""
        change = ChangeRecord(
            collection_id=feature.collection_id,
            feature_id=feature.id,
            organization=feature.organization,
            operation=operation,
            timestamp=feature.updated_at,
            feature_snapshot=feature.to_geojson(),
        )
        self._changes_table.put_item(Item=change.to_dynamodb_item())


# ======================================================================
# Module-level helpers (used by FeatureDAL but also independently testable)
# ======================================================================


def _json_merge_patch(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Apply JSON Merge Patch (RFC 7396) to *target*.

    * Keys in *patch* with a ``None`` value remove the corresponding
      key from the result.
    * Dict values are merged recursively.
    * All other values are replaced.
    """
    result = dict(target)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _json_merge_patch(result[key], value)
        else:
            result[key] = value
    return result


def _filter_by_bbox(
    features: list[Feature],
    bbox: tuple[float, float, float, float],
) -> list[Feature]:
    """Filter features whose geometry intersects the bounding box.

    Uses simple bounding-box envelope overlap.  A proper spatial index
    (GeoHash / Hilbert curve) is planned for Phase 14.
    """
    west, south, east, north = bbox
    result: list[Feature] = []
    for feature in features:
        if feature.geometry is None:
            continue
        feature_bbox = _compute_geometry_bbox(feature.geometry)
        if feature_bbox is None:
            continue
        fw, fs, fe, fn = feature_bbox
        if fw <= east and fe >= west and fs <= north and fn >= south:
            result.append(feature)
    return result


def _compute_geometry_bbox(
    geometry: dict[str, Any],
) -> tuple[float, float, float, float] | None:
    """Compute the bounding box of a GeoJSON geometry.

    Returns ``(west, south, east, north)`` or ``None`` if there are no
    coordinates.
    """
    coords = _extract_all_positions(geometry)
    if not coords:
        return None
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return (min(lons), min(lats), max(lons), max(lats))


def _extract_all_positions(geometry: dict[str, Any]) -> list[list[float]]:
    """Recursively extract all ``[lon, lat, ...]`` positions from a GeoJSON geometry."""
    geom_type = geometry.get("type", "")
    coordinates = geometry.get("coordinates")

    if geom_type == "GeometryCollection":
        positions: list[list[float]] = []
        for geom in geometry.get("geometries", []):
            positions.extend(_extract_all_positions(geom))
        return positions

    if coordinates is None:
        return []

    if geom_type == "Point":
        return [coordinates]
    if geom_type in ("MultiPoint", "LineString"):
        return list(coordinates)
    if geom_type in ("MultiLineString", "Polygon"):
        return [pos for ring in coordinates for pos in ring]
    if geom_type == "MultiPolygon":
        return [pos for polygon in coordinates for ring in polygon for pos in ring]

    return []
