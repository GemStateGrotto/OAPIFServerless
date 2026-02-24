"""Data Access Layer for DynamoDB operations.

All DynamoDB operations go through this module. Lambda handlers must
never call DynamoDB directly — they always go through the DAL.
"""

from oapif.dal.collections import CollectionDAL
from oapif.dal.exceptions import (
    CollectionNotFoundError,
    ETagMismatchError,
    ETagRequiredError,
    FeatureNotFoundError,
)
from oapif.dal.features import FeatureDAL
from oapif.dal.pagination import decode_cursor, encode_cursor

__all__ = [
    "CollectionDAL",
    "CollectionNotFoundError",
    "ETagMismatchError",
    "ETagRequiredError",
    "FeatureDAL",
    "FeatureNotFoundError",
    "decode_cursor",
    "encode_cursor",
]
