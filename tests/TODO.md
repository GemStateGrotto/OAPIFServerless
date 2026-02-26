# TODO — Remote Acceptance Test Suite

This document tracks the build-out of the acceptance test suite that exercises the
live deployed endpoint.  Like the main TODO, treat these as guidelines — if you see
a better approach, deviate.  The goal is thorough remote validation of every
capability the backend exposes.

Tests live in `tests/acceptance/`, are marked `@pytest.mark.acceptance`, and are
excluded from normal `unit`/`integration` runs.  Run them on demand:

```bash
pytest -m acceptance
```

### Setup / Teardown Scripts

Test fixtures (Cognito users, groups, collection config, seed features) are managed
by standalone scripts — not embedded in pytest fixtures — so they can be inspected
and re-run independently:

```bash
./scripts/acceptance-setup.sh          # create users, groups, seed collection & features
./scripts/acceptance-setup.sh --status # show current state
./scripts/acceptance-teardown.sh       # remove everything the setup created
```

Both scripts derive all values from CloudFormation stack outputs — no manual
env var configuration beyond `OAPIF_ENVIRONMENT` (default: `dev`) and standard
AWS credentials.

**Test users created by setup:**

| Username | Email | Org Group | Role | Visibility Groups |
|---|---|---|---|---|
| `test-editor` | test-editor@oapif.test | `org:TestOrgA` | `editor` | `TestOrgA:members` |
| `test-admin` | test-admin@oapif.test | `org:TestOrgA` | `admin` | `TestOrgA:members`, `TestOrgA:restricted` |
| `test-viewer` | test-viewer@oapif.test | `org:TestOrgA` | `viewer` | — |

**Test collection:** `acceptance-test` — a single-org (TestOrgA) Point collection
with `name` (required), `depth_m`, `survey_date`, `status` properties.
Three public seed features are created for OGC CITE conformance testing.

> Cross-org isolation (TestOrgB) is tested at the integration level only.
> See `tests/integration/test_handlers_integration.py`.

For OGC CITE conformance testing, see [CITE.md](CITE.md).

---

All sections below are **complete**. They are retained as a reference for what
the acceptance test suite covers.

## Completed

- Infrastructure & conventions
- Read endpoints (unauthenticated)
- Authentication & token lifecycle
- Full CRUD lifecycle (authenticated)
- ETag / optimistic concurrency
- Schema validation
- Row-level access control (org + visibility)
- Field-level authorization
- Pagination
- Filtering
- OPTIONS / CORS
- Error responses
- Seed-feature discovery (single-org default, no `organization` param)
- Query parameter validation (unknown → 400, invalid → 400)
- OGC CITE Part 1 Core conformance (89 passed, 0 failed)
