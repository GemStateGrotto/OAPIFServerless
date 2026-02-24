"""Custom exceptions for the data access layer."""

from __future__ import annotations


class FeatureNotFoundError(Exception):
    """Raised when a requested feature does not exist or is soft-deleted."""

    def __init__(self, collection_id: str, feature_id: str) -> None:
        self.collection_id = collection_id
        self.feature_id = feature_id
        super().__init__(f"Feature '{feature_id}' not found in collection '{collection_id}'")


class ETagMismatchError(Exception):
    """Raised when the provided ETag does not match (HTTP 412 Precondition Failed)."""

    def __init__(self, provided_etag: str) -> None:
        self.provided_etag = provided_etag
        super().__init__(f"ETag mismatch: provided '{provided_etag}' does not match current")


class ETagRequiredError(Exception):
    """Raised when If-Match header is required but missing (HTTP 428)."""

    def __init__(self) -> None:
        super().__init__("If-Match header with ETag is required for this operation")


class CollectionNotFoundError(Exception):
    """Raised when a requested collection configuration does not exist."""

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
        super().__init__(f"Collection '{collection_id}' not found")


class OrganizationImmutableError(Exception):
    """Raised when a request attempts to change the organization field.

    The ``organization`` field is server-populated on creation and
    must never be modified.
    """

    def __init__(self) -> None:
        super().__init__("The 'organization' field is immutable and cannot be changed")
