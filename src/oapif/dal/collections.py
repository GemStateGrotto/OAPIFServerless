"""Data Access Layer for collection configuration operations against DynamoDB.

All DynamoDB interactions for collection configs go through
:class:`CollectionDAL`.  Lambda handlers must never call DynamoDB directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from oapif.dal.exceptions import CollectionNotFoundError
from oapif.models.collection import CollectionConfig

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBServiceResource

logger = logging.getLogger(__name__)


class CollectionDAL:
    """Data access layer for collection configuration CRUD.

    Parameters
    ----------
    dynamodb_resource:
        A ``boto3.resource("dynamodb")`` instance.
    config_table_name:
        Name of the DynamoDB config table.
    """

    def __init__(
        self,
        dynamodb_resource: DynamoDBServiceResource,
        config_table_name: str,
    ) -> None:
        self._resource = dynamodb_resource
        self._config_table = dynamodb_resource.Table(config_table_name)

    # ------------------------------------------------------------------
    # READ (single)
    # ------------------------------------------------------------------

    def get_collection(self, collection_id: str) -> CollectionConfig:
        """Retrieve a single collection configuration by ID.

        Parameters
        ----------
        collection_id:
            The collection's unique identifier.

        Returns
        -------
        CollectionConfig
            The full collection configuration.

        Raises
        ------
        CollectionNotFoundError
            If the collection does not exist.
        """
        response = self._config_table.get_item(
            Key={
                "PK": CollectionConfig.make_pk(collection_id),
                "SK": CollectionConfig.make_sk(),
            },
        )

        item = response.get("Item")
        if item is None:
            raise CollectionNotFoundError(collection_id)

        return CollectionConfig.from_dynamodb_item(item)

    # ------------------------------------------------------------------
    # READ (list all)
    # ------------------------------------------------------------------

    def list_collections(self) -> list[CollectionConfig]:
        """List all collection configurations.

        Scans the config table for all items where ``SK = CONFIG``.
        Since the number of collections is expected to be small (tens,
        not thousands), a scan is acceptable here.

        Returns
        -------
        list[CollectionConfig]
            All collection configurations.
        """
        collections: list[CollectionConfig] = []

        # Use scan with a filter on SK since configs share the table
        # with potential future item types.
        scan_kwargs: dict[str, Any] = {
            "FilterExpression": "SK = :sk",
            "ExpressionAttributeValues": {":sk": "CONFIG"},
        }

        while True:
            response = self._config_table.scan(**scan_kwargs)
            for item in response.get("Items", []):
                collections.append(CollectionConfig.from_dynamodb_item(item))

            last_key = response.get("LastEvaluatedKey")
            if last_key:
                scan_kwargs["ExclusiveStartKey"] = last_key
            else:
                break

        # Sort by collection_id for deterministic ordering
        collections.sort(key=lambda c: c.collection_id)
        return collections

    # ------------------------------------------------------------------
    # CREATE / UPDATE
    # ------------------------------------------------------------------

    def put_collection(self, config: CollectionConfig) -> CollectionConfig:
        """Create or replace a collection configuration.

        Parameters
        ----------
        config:
            The collection configuration to store.

        Returns
        -------
        CollectionConfig
            The stored configuration.
        """
        self._config_table.put_item(Item=config.to_dynamodb_item())

        logger.info(
            "Stored collection config",
            extra={"collection_id": config.collection_id},
        )
        return config

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    def delete_collection(self, collection_id: str) -> None:
        """Delete a collection configuration.

        Parameters
        ----------
        collection_id:
            The collection to delete.

        Raises
        ------
        CollectionNotFoundError
            If the collection does not exist.
        """
        # Verify it exists first
        self.get_collection(collection_id)

        self._config_table.delete_item(
            Key={
                "PK": CollectionConfig.make_pk(collection_id),
                "SK": CollectionConfig.make_sk(),
            },
        )

        logger.info(
            "Deleted collection config",
            extra={"collection_id": collection_id},
        )
