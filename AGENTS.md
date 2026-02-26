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

### Terminal Commands

Do not pipe long-running commands through `tail`, `head`, or other filters that hide intermediate output. Let commands print their full output so progress is visible in real time (e.g., test results, CDK deploy status, lint findings). Truncation makes it impossible to tell whether a command is still running or has stalled.

## Project Layout

```
.devcontainer/   # DevContainer configuration
src/oapif/       # Lambda backend (handlers/, dal/, auth/, models/)
plugin/          # QGIS plugin (PyQGIS / Qt) — see plugin/TODO.md
  plugin/scripts/  # Plugin quality gate (runs inside QGIS container)
deploy/          # CDK app and stacks
tests/           # pytest suite (unit/, integration/, acceptance/)
scripts/         # Quality-gate, deploy, acceptance, and QGIS test scripts
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
- QGIS plugin tests run in a persistent Docker container (`qgis/qgis:ltr`) managed via DinD — setup/teardown scripts mirror the acceptance test pattern. See `plugin/TODO.md` for test tiers and execution methodology.
- Plugin targets Python 3.12 (QGIS-bundled), not the backend's Python 3.14

### Acceptance Tests (Remote)

End-to-end tests against a live deployed endpoint. Managed by setup/teardown scripts
and a pytest suite. Full plan in `tests/TODO.md`.

**Flow:**

```bash
./scripts/acceptance-setup.sh          # 1. Create Cognito users, groups, seed collection
pytest -m acceptance                   # 2. Run acceptance tests
./scripts/acceptance-teardown.sh       # 3. Clean up test fixtures
```

**What the setup script creates** (idempotent, reads all config from CFN outputs):

- Cognito users with permanent passwords and group memberships:
  - `test-editor` — `org:TestOrgA`, `editor`, `TestOrgA:members`
  - `test-admin`  — `org:TestOrgA`, `admin`, `TestOrgA:members`, `TestOrgA:restricted`
  - `test-viewer` — `org:TestOrgA`, `viewer`
- DynamoDB config item: `acceptance-test` collection (Point, single org TestOrgA)

**What the teardown script removes:**

- The three test users
- All features and the config item for `acceptance-test`

**Test conftest** authenticates users via `admin-initiate-auth` (ADMIN_USER_PASSWORD_AUTH)
to get real ID tokens with `cognito:groups` claims. Base URL is derived from CFN stack
outputs. No manual env var config beyond `OAPIF_ENVIRONMENT` and AWS credentials.

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

The pre-commit hook classifies staged files and requires the appropriate
check suite(s) to have run recently (default: within 60 seconds,
configurable via `OAPIF_CHECK_MAX_AGE`):

| Staged files | Check required | Stamp file |
|---|---|---|
| Only docs (`*.md`, `LICENSE`, `.gitignore`, `.env.example`) | None | — |
| Backend (`src/`, `deploy/`, `tests/`, `scripts/`) | `check-backend.sh` | `.checks_passed_backend` |
| Plugin (`plugin/*.py` at any depth) | `check-plugin.sh` | `.checks_passed_plugin` |
| Mix of backend + plugin | Both | Both stamps |

### Backend Quality Gate

Covers `src/`, `deploy/`, `tests/`, `scripts/` — does **not** touch `plugin/`:

```bash
./scripts/check-backend.sh             # ALL backend checks — required before backend commits
./scripts/check-backend.sh --fix       # auto-fix lint/format, then run all checks
```

Available subsets (for iterating during development):

```bash
./scripts/check-backend.sh lint        # ruff lint + format only
./scripts/check-backend.sh types       # mypy only
./scripts/check-backend.sh unit        # unit tests only
./scripts/check-backend.sh integration # integration tests only
./scripts/check-backend.sh synth       # CDK synth only
./scripts/check-backend.sh lint types  # combine any subset
./scripts/check-backend.sh --fix lint  # auto-fix lint/format only
```

### Plugin-Only Quality Gate

Runs ruff and mypy inside the QGIS Docker container (Python 3.12,
matching the plugin target). Does **not** touch backend code:

```bash
./scripts/check-plugin.sh              # ALL plugin checks — required before plugin-only commits
./scripts/check-plugin.sh --fix        # auto-fix lint/format, then run all checks
./scripts/check-plugin.sh lint         # ruff only
./scripts/check-plugin.sh types        # mypy only
```

Requires the QGIS container (`./scripts/qgis-test-setup.sh`). The wrapper
calls `docker exec oapif-qgis-test /plugin/scripts/check.sh` — all tools
run natively in the container.

If the hook is missing:

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
# test
