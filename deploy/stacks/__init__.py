"""OAPIFServerless CDK stacks."""

from deploy.stacks.api import ApiStack
from deploy.stacks.auth import AuthStack
from deploy.stacks.data import DataStack

__all__ = ["ApiStack", "AuthStack", "DataStack"]
