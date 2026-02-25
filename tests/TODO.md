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

Test fixtures (Cognito users, groups, collection config) are managed by
standalone scripts — not embedded in pytest fixtures — so they can be
inspected and re-run independently:

```bash
./scripts/acceptance-setup.sh          # create users, groups, seed collection
./scripts/acceptance-setup.sh --status # show current state
./scripts/acceptance-teardown.sh       # remove everything the setup created
```

Both scripts derive all values from CloudFormation stack outputs — no manual
env var configuration beyond `OAPIF_ENVIRONMENT` (default: `dev`) and standard
AWS credentials.

**Test users created by setup:**

| Username | Email | Org Group | Role | Visibility Groups |
|---|---|---|---|---|
| `test-editor` | test-editor@oapif.test | `org:GemStateGrotto` | `editor` | `GemStateGrotto:members` |
| `test-admin` | test-admin@oapif.test | `org:GemStateGrotto` | `admin` | `GemStateGrotto:members`, `GemStateGrotto:restricted` |
| `test-viewer` | test-viewer@oapif.test | `org:GemStateGrotto` | `viewer` | — |
| `test-other-org` | test-other-org@oapif.test | `org:TestOrgB` | `editor` | `TestOrgB:members` |

**Test collection:** `acceptance-caves` — a Point collection with `name` (required),
`depth_m`, `survey_date`, `status` properties; mapped to both `GemStateGrotto` and
`TestOrgB` organizations.

---

## Infrastructure & Conventions

- [ ] Create `tests/acceptance/` directory with its own `conftest.py`
- [ ] Add `acceptance` marker to `pyproject.toml` (`markers = ["acceptance: …"]`)
- [ ] `conftest.py`: derive base URL from CFN stack outputs at session startup
  - `oapif-{env}-api` stack → `ApiUrl` (or `CustomDomainTarget` → `https://{custom_domain}`)
  - `oapif-{env}-auth` stack → `UserPoolId`, `UserPoolDomainUrl`
  - `OAPIF_ENVIRONMENT` env var (default: `dev`)
- [ ] `conftest.py`: authenticate test users via `admin-initiate-auth` (ADMIN_USER_PASSWORD_AUTH) to obtain real JWT tokens with Cognito group claims
- [ ] Fixture: `editor_client` — authenticated `httpx.Client` for `test-editor`
- [ ] Fixture: `admin_client` — authenticated `httpx.Client` for `test-admin`
- [ ] Fixture: `viewer_client` — authenticated `httpx.Client` for `test-viewer`
- [ ] Fixture: `other_org_client` — authenticated `httpx.Client` for `test-other-org`
- [ ] Fixture: `anon_client` — unauthenticated `httpx.Client`
- [ ] Tag every feature created during tests with a unique test-run ID in a property; session-scoped finalizer deletes features matching that tag
- [ ] Each test module scopes queries using the test-run tag to avoid cross-run interference

## 1. Read Endpoints (Unauthenticated)

- [ ] `GET /` — 200, valid landing page with required links (self, service-desc, conformance, data)
- [ ] `GET /conformance` — 200, `conformsTo` array contains expected conformance classes
- [ ] `GET /api` — 200, valid OpenAPI 3.0 JSON
- [ ] `GET /collections` — 200, `collections` array, each entry has id/title/links
- [ ] `GET /collections/{id}` — 200 for existing collection; 404 for nonexistent
- [ ] `GET /collections/{id}/schema` — 200, valid JSON Schema with `x-ogc-role`
- [ ] `GET /collections/{id}/items?organization=...` — 200, GeoJSON FeatureCollection
- [ ] `GET /collections/{id}/items/{featureId}?organization=...` — 200 for existing public feature; 404 for nonexistent
- [ ] Verify all response `links[].href` values use the custom domain, not the raw API Gateway URL

## 2. Authentication & Token Lifecycle

- [ ] Authenticate `test-editor` via `admin-initiate-auth` — assert `IdToken` present with `cognito:groups` claim
- [ ] `editor_client` `GET /collections` — 200, response shape matches unauthenticated
- [ ] Request with invalid/garbage Bearer token — assert 401

## 3. Full CRUD Lifecycle (Authenticated)

- [ ] `POST /collections/{id}/items` — 201, `Location` header present, response contains assigned feature ID and ETag
- [ ] `GET` the created feature by ID — 200, body matches what was posted, `ETag` header present
- [ ] `PUT /collections/{id}/items/{featureId}` with `If-Match` — 200, updated body, new ETag
- [ ] `PATCH /collections/{id}/items/{featureId}` with JSON Merge Patch and `If-Match` — 200, verify partial update applied
- [ ] `DELETE /collections/{id}/items/{featureId}` with `If-Match` — 204
- [ ] `GET` the deleted feature — 404

## 4. ETag / Optimistic Concurrency

- [ ] `PUT` without `If-Match` — 428 Precondition Required
- [ ] `PATCH` without `If-Match` — 428
- [ ] `DELETE` without `If-Match` — 428
- [ ] `PUT` with stale `If-Match` — 412 Precondition Failed
- [ ] `PATCH` with stale `If-Match` — 412
- [ ] `DELETE` with stale `If-Match` — 412

## 5. Schema Validation

- [ ] `POST` with missing required properties — 422
- [ ] `POST` with wrong property types — 422
- [ ] `PUT` with body violating collection schema — 422

## 6. Row-Level Access Control (Org + Visibility)

- [ ] `anon_client` `GET /items` without `organization` param — 400
- [ ] `anon_client` `GET /items?organization=GemStateGrotto` — only `public` features returned
- [ ] `editor_client` (members group) — sees `public` + `members` but not `restricted`
- [ ] `admin_client` (members + restricted groups) — sees `public` + `members` + `restricted`
- [ ] `viewer_client` (no visibility groups) — sees only `public`
- [ ] `other_org_client` (org:TestOrgB) — never sees GemStateGrotto features
- [ ] `editor_client` `POST` — `organization` auto-populated as `GemStateGrotto` from token
- [ ] `editor_client` `PUT`/`PATCH` attempting to change `organization` — rejected

## 7. Field-Level Authorization

- [ ] `editor_client` can modify geometry and properties — 200
- [ ] `editor_client` cannot modify `visibility` — 403
- [ ] `admin_client` can modify `visibility` — 200
- [ ] `admin_client` cannot modify `organization` — 403 or rejected
- [ ] `viewer_client` cannot write at all — 403

## 8. Pagination

- [ ] `GET /items?limit=2` — response has ≤ 2 features and a `next` link
- [ ] Follow `next` link — 200, returns next page
- [ ] Paginate until no `next` link — all features retrieved without duplicates

## 9. Filtering

- [ ] `bbox` query parameter — only features within bbox returned
- [ ] `datetime` query parameter — only features matching temporal filter returned
- [ ] Property filter query parameters — correct subset returned

## 10. OPTIONS / CORS

- [ ] `OPTIONS /collections/{id}/items` — `Allow` header lists GET, POST, OPTIONS
- [ ] `OPTIONS /collections/{id}/items/{featureId}` — `Allow` header lists GET, PUT, PATCH, DELETE, OPTIONS

## 11. Error Responses

- [ ] 404 for nonexistent collection
- [ ] 404 for nonexistent feature
- [ ] 405 for unsupported method on a valid path
- [ ] Response bodies follow OGC exception schema (`code`, `description`)
