#!/usr/bin/env python3
"""CDK application entry point for OAPIFServerless.

Usage:
    npx cdk deploy --app "python deploy/app.py"
    npx cdk synth  --app "python deploy/app.py"
    npx cdk deploy --app "python deploy/app.py" oapif-dev-api   # deploy only the API stack
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so that ``from deploy.config …``
# resolves correctly when CDK invokes ``python deploy/app.py``.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import aws_cdk as cdk

from deploy.config import load_deployment_config
from deploy.stacks.api import ApiStack
from deploy.stacks.data import DataStack

app = cdk.App()
config = load_deployment_config(app)

env = cdk.Environment(
    account=config.aws_account or None,
    region=config.aws_region,
)

# --- Stateful stack: DynamoDB tables + S3 bucket ---
# Safe to deploy repeatedly; uses RETAIN policy in non-dev environments.
data_stack = DataStack(
    app,
    f"{config.stack_prefix}-{config.environment}-data",
    config=config,
    env=env,
)

# --- Stateless stack: Lambda + API Gateway ---
# Can be destroyed and redeployed freely without affecting data.
api_stack = ApiStack(
    app,
    f"{config.stack_prefix}-{config.environment}-api",
    config=config,
    features_table=data_stack.features_table,
    changes_table=data_stack.changes_table,
    config_table=data_stack.config_table,
    project_bucket=data_stack.project_bucket,
    env=env,
)
api_stack.add_dependency(data_stack)

# Future: AuthStack for Cognito (Phase 4)

app.synth()
