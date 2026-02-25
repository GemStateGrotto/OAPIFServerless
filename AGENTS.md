# AGENTS.md — Agent Baseline Expectations

> Keep this file concise. Every line consumes context window. Avoid redundancy — if something is clear from the code, don't repeat it here. Prune on every edit.

This file provides context and guidelines for AI coding agents working on this project.

## Project Summary

OAPIFServerless is an AWS Serverless OGC API - Features implementation backed by DynamoDB, with Cognito auth, a QGIS plugin, and full IaC deployment. See README.md for the full scope.

## Language and Runtime

- **Backend:** Python 3.14 (Lambda runtime)
- **Infrastructure:** AWS CDK (Python) — `deploy/` directory
- **QGIS Plugin:** Python (PyQGIS / Qt)
- **Tests:** pytest for backend; Qt test framework for plugin

## Development Environment

All development happens inside the **DevContainer**. It provides Python 3.14, Node.js 22, AWS CLI, and DynamoDB Local (`http://dynamodb-local:8000`). Dependencies are auto-installed via `postCreateCommand`.

### AWS Access

AWS credentials are available in the DevContainer environment. Read-only AWS operations (e.g., `aws s3 ls`, `aws dynamodb describe-table`) may be run freely. **Any AWS command that creates, modifies, or deletes resources must be explicitly approved or requested by the user before execution.**

## Project Layout

```
.devcontainer/   # DevContainer configuration
src/oapif/       # Lambda backend (handlers/, dal/, auth/, models/)
deploy/          # CDK app and stacks
tests/           # pytest suite (unit/, integration/)
scripts/         # Quality-gate script and pre-commit hook
.github/         # CI workflows
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

- `./scripts/deploy.sh deploy api` — deploys only Lambda + API Gateway (~15-30s for code changes)
- `./scripts/deploy.sh diff` — preview what will change before deploying
- `./scripts/deploy.sh deploy` — deploy all stacks
- `./scripts/deploy.sh status` — show deployment status of all stacks
- Never run `./scripts/deploy.sh destroy` on the data stack in production

## Testing Expectations

- Unit tests for all business logic (authorization, schema validation, data access)
- Integration tests against DynamoDB Local for data layer
- Mock AWS services with `moto` where DynamoDB Local is not available
- QGIS plugin tests should be runnable headless where possible

## Security Principles

- Never log or expose full JWTs, secrets, or PII
- Files in ~vscode/.secrets/ must not be printed to the console, committed to git, or read by agents
- All authorization decisions happen server-side in Lambda; never trust client claims alone
- Organization (`organization` field) is a hard tenant boundary — all queries are scoped to the caller's org; no response ever mixes orgs
- Unauthenticated GET requests are allowed but must include an `organization` query parameter and only see `public` features
- `organization` is auto-populated on feature creation from Cognito group and is immutable after creation
- Row-level visibility filtering (`public`/`members`/`restricted`) is applied at the query layer, not post-query
- Field-level write restrictions are enforced before DynamoDB writes, not after
- IAM roles use least-privilege; Lambda functions only get access to the specific tables and buckets they need

## Pre-Commit Quality Gate

Run before every commit:

```bash
./scripts/check.sh                 # ALL checks (lint, format, types, tests, CDK synth)
./scripts/check.sh lint            # ruff lint + format only
./scripts/check.sh types           # mypy only
./scripts/check.sh unit            # unit tests only
./scripts/check.sh integration     # integration tests only
./scripts/check.sh synth           # CDK synth only
./scripts/check.sh lint types      # combine any subset
./scripts/check.sh --fix           # auto-fix lint/format, then run all checks
./scripts/check.sh --fix lint      # auto-fix lint/format only
```

A git pre-commit hook enforces this automatically (installed by DevContainer `postCreateCommand`). Do not use `--no-verify`. If the hook is missing:

```bash
cp scripts/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

## Commits & PRs

- **Do not commit unless explicitly directed by the user.** Never push or write to upstream.
- Imperative, concise commit messages ("Add schema endpoint", not "Added schema endpoint")
- One logical change per commit
- PRs must include tests for new behavior
- API-breaking changes must update the OpenAPI definition

## Documentation

- Docs must match code — treat stale docs as bugs
- Update all affected docs (README, AGENTS, TODO, .env.example) in the same pass as code changes

## Don'ts

- No hardcoded AWS account IDs, regions, or resource names — use env vars or CDK context
- S3 is for QGIS project files only — not feature data
- No automated rollback — change tracking is append-only
- Never return features the caller isn't authorized to see
