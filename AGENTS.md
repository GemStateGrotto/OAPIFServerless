# AGENTS.md — Agent Baseline Expectations

This file provides context and guidelines for AI coding agents working on this project.

## Project Summary

OAPIFServerless is an AWS Serverless OGC API - Features implementation backed by DynamoDB, with Cognito auth, a QGIS plugin, and full IaC deployment. See README.md for the full scope.

## Language and Runtime

- **Backend:** Python 3.14 (Lambda runtime)
- **Infrastructure:** AWS CDK (Python) — `deploy/` directory
- **QGIS Plugin:** Python (PyQGIS / Qt)
- **Tests:** pytest for backend; Qt test framework for plugin

## Development Environment

This project uses a **DevContainer** (VS Code Dev Containers / GitHub Codespaces). All development should happen inside the container — do not rely on the host Python installation.

- The DevContainer provides Python 3.14, Node.js 22, AWS CLI, and DynamoDB Local.
- Dependencies are installed automatically via `postCreateCommand` in `.devcontainer/devcontainer.json`.
- DynamoDB Local runs as a sibling container, reachable at `http://dynamodb-local:8000` from inside the dev container.
- To open: VS Code → "Reopen in Container" (or `Dev Containers: Reopen in Container` from the command palette).

## Project Layout

```
OAPIFServerless/
├── .devcontainer/       # DevContainer configuration
│   ├── devcontainer.json
│   └── docker-compose.yml
├── src/oapif/           # Lambda backend source
│   ├── handlers/        # API Gateway Lambda handlers
│   ├── dal/             # DynamoDB data access layer
│   ├── auth/            # Auth & authorization logic
│   ├── models/          # Data models and schemas
│   └── config.py        # Runtime config from env vars
├── deploy/              # CDK app and stacks (Python)
│   ├── app.py           # CDK entry point
│   ├── config.py        # Deployment config loader
│   └── stacks/          # CDK stack definitions
├── tests/               # pytest test suite
│   ├── conftest.py      # Shared fixtures (moto, DynamoDB Local)
│   ├── unit/            # Unit tests (no external deps)
│   └── integration/     # Integration tests (DynamoDB Local)
├── .github/workflows/   # CI pipeline
├── pyproject.toml       # Python project config (deps, tools)
├── .env.example         # Environment variable reference
└── docker-compose.yml   # Standalone DynamoDB Local (outside devcontainer)
```

## Key Standards

- OGC API - Features Part 1: Core (OGC 17-069r4) — read-only endpoints
- OGC API - Features Part 4: CRUD (OGC 20-002r1, draft) — transactional operations
- OGC API - Features Part 5: Schemas (OGC 23-058, draft) — schema publishing
- GeoJSON (RFC 7946) — feature encoding
- JSON Merge Patch (RFC 7396) — PATCH request format
- HTTP Semantics (RFC 9110) — ETag / If-Match optimistic concurrency
- OpenAPI 3.0 — API definition

## Coding Conventions

- Follow PEP 8 for Python code
- Use type hints on all function signatures
- Prefer `pathlib.Path` over `os.path`
- Prefer `boto3` resource/client patterns with explicit typing
- All DynamoDB operations should go through a data access layer, never called directly from request handlers
- Use structured logging (JSON) suitable for CloudWatch
- Feature GeoJSON must conform to RFC 7946 (longitude/latitude, WGS 84)

## Infrastructure Architecture

The CDK app (`deploy/app.py`) produces two stacks per environment:

| Stack | Contains | Notes |
|-------|----------|-------|
| `oapif-{env}-data` | DynamoDB tables, S3 bucket | **Stateful.** `RETAIN` policy in staging/prod; termination protection enabled. |
| `oapif-{env}-api` | Lambda, API Gateway | **Stateless.** Can be freely destroyed and redeployed without affecting data. |

Configuration is via `OAPIF_*` environment variables or CDK `--context` flags. Defaults live in `deploy/config.py` (`DeploymentConfig` dataclass). See `.env.example` for the full variable list.

### Deploying Changes

- `cdk deploy oapif-dev-api` — deploys only Lambda + API Gateway (~15-30s for code changes)
- `cdk diff oapif-dev-api` — preview what will change before deploying
- `cdk deploy --all` — deploy both stacks
- Never run `cdk destroy` on the data stack in production

## Testing Expectations

- Unit tests for all business logic (authorization, schema validation, data access)
- Integration tests against DynamoDB Local for data layer
- Mock AWS services with `moto` where DynamoDB Local is not available
- QGIS plugin tests should be runnable headless where possible

## Security Principles

- Never log or expose full JWTs, secrets, or PII
- All authorization decisions happen server-side in Lambda; never trust client claims alone
- Organization (`organization` field) is a hard tenant boundary — all queries are scoped to the caller's org; no response ever mixes orgs
- Unauthenticated GET requests are allowed but must include an `organization` query parameter and only see `public` features
- `organization` is auto-populated on feature creation from Cognito group and is immutable after creation
- Row-level visibility filtering (`public`/`members`/`restricted`) is applied at the query layer, not post-query
- Field-level write restrictions are enforced before DynamoDB writes, not after
- IAM roles use least-privilege; Lambda functions only get access to the specific tables and buckets they need

## Commit and PR Expectations

- Commit messages should be concise and imperative ("Add feature schema endpoint", not "Added feature schema endpoint")
- One logical change per commit
- PRs should include tests for new behavior
- Breaking changes to the API must update the OpenAPI definition and schema endpoints

## Documentation Accuracy

- Always verify that documentation (README.md, AGENTS.md, TODO.md, .env.example, inline comments) matches the actual state of the code
- If you find a mismatch between docs and implementation, fix the documentation to reflect reality
- When making code changes, update all affected documentation in the same pass — do not leave stale references
- Treat outdated documentation as a bug

## What NOT to Do

- Do not hardcode AWS account IDs, region, or resource names — use environment variables or CDK context
- Do not store feature data in S3 (S3 is only for QGIS project files)
- Do not implement automated rollback — change tracking is append-only for audit; manual restore only
- Do not return features the caller is not authorized to see — filter before response, not after
