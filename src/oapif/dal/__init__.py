"""Data Access Layer for DynamoDB operations.

All DynamoDB operations go through this module. Lambda handlers must
never call DynamoDB directly — they always go through the DAL.
"""
