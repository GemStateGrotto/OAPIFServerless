# TODO — OAPIFServerless Build Plan

This document tracks the full build-out of the project. Phases are roughly sequential
but some tasks within a phase can be parallelized. While instructions here appear
explicit, treat these as guidelines rather than strict rules — if you see a better way
to implement something, feel free to deviate. The goal is a working implementation
that meets the project requirements, not strict adherence to this plan.

---

## Completed

The following phases are **complete**. They are retained as a reference for what
the backend, infrastructure, and acceptance test suite cover.

- **Phase 0:** Project scaffolding — CDK (Python), pyproject.toml, ruff, pytest, CI, config schema
- **Phase 1:** DynamoDB data layer — DAL with CRUD, ETag concurrency, cursor pagination, change tracking
- **Phase 2:** Collection config & schema — config loader, dynamic JSON Schema, Part 5 returnables/receivables
- **Phase 3:** OAPIF Core read endpoints — Part 1 (landing, conformance, collections, items, OpenAPI, schema)
- **Phase 4:** Authentication & authorization — Cognito User Pool, JWT authorizer, group extraction, unauth path
- **Phase 5:** Row-level access control — org tenant scoping, visibility filtering at query time, 404-not-403
- **Phase 6:** OAPIF Part 4 write endpoints — CRUD, ETag/If-Match, schema validation, change tracking
- **Phase 7:** Field-level authorization — editor/admin/viewer role enforcement on PUT/PATCH
- **Phase 11:** Deployment system — CDK stacks (data + api), deploy CLI, custom domain, dependency bundling
- **Phase 12:** OpenAPI definition — dynamic generation, CITE validation, served at `/api`
- **Phase 13 (partial):** Testing & compliance — OGC CITE Part 1 (89/89), full acceptance suite ([tests/TODO.md](tests/TODO.md))

---

## Phase 8–9: QGIS Plugin

See [plugin/TODO.md](plugin/TODO.md) for the detailed build plan, organized by
testing methodology (pure Python → headless PyQGIS → GUI widget tests).

Summary of plugin phases:

- [x] P0: Test infrastructure — QGIS Docker (LTR) container via DinD, setup/teardown scripts, `docker exec` test runner, CI workflow
- [x] P1: Plugin scaffolding + pure Python core — HTTP client, OIDC/PKCE token management, config
- [ ] P2: Auth + data provider — QgsAuthMethodConfig, Bearer token injection, built-in OAPIF provider, layer loading, pagination, bbox
- [ ] P3: Feature editing — create/update/delete via plugin, ETag concurrency, conflict resolution
- [ ] P4: GUI widgets — connection dialog, layer browser, edit forms, conflict dialog, project file browser, settings


## Phase 10: Project File Sync — Backend

Lambda endpoints and CDK infrastructure for S3 project file management.
Plugin UI for this phase is in [plugin/TODO.md](plugin/TODO.md) (Phase P4).

- [ ] Lambda endpoint: `GET /projects` → list available project files for the caller's org
- [ ] Lambda endpoint: `GET /projects/{projectId}/download` → presigned S3 GET URL
- [ ] Lambda endpoint: `PUT /projects/{projectId}/upload` → presigned S3 PUT URL
- [ ] Authorization: editor/admin for upload, all authenticated users for download
- [ ] CDK: S3 bucket configuration, Lambda IAM policy for `s3:GetObject` / `s3:PutObject`
- [ ] CDK: API Gateway routes for `/projects` endpoints
- [ ] Handle concurrent project edits (last-write-wins or warn user via ETag)
- [ ] Unit tests for Lambda handlers (mock S3)
- [ ] Integration tests with moto S3

## Phase 13: Testing and Compliance (remaining)

- [x] OGC CITE Part 1 Core conformance (89 passed, 0 failed)
- [x] Remote acceptance test suite (see [tests/TODO.md](tests/TODO.md))
- [ ] QGIS plugin end-to-end tests — see [plugin/TODO.md](plugin/TODO.md)
- [ ] Load test: verify Lambda concurrency and DynamoDB throughput under simulated load
- [ ] Security review: test auth bypass, row-level filter evasion, field-level enforcement
- [ ] Test deployment on a second AWS account to validate portability

## Phase 14 (v2): Spatial Indexing

- [ ] Research and select spatial indexing strategy (GeoHash, Z-order curve, Hilbert curve)
- [ ] Implement spatial index attribute computation on feature create/update
- [ ] Add DynamoDB GSI for spatial index
- [ ] Implement `bbox` query using spatial index (fan-out to relevant hash prefixes)
- [ ] Benchmark spatial query performance vs. full-table scan
- [ ] Update schema and documentation for v2 spatial support

## Backlog / Future Ideas

- [ ] Support HTML encoding for browser-based collection and feature browsing
- [ ] Support GML encoding (Part 1 conformance classes gmlsf0/gmlsf2)
- [ ] Implement `prev` link for bidirectional paging
- [ ] Support CRS negotiation (Part 2: Coordinate Reference Systems by Reference)
- [ ] WebSocket or SSE push notifications for feature changes
- [ ] Admin UI for collection and user management
- [ ] Batch import/export (GeoPackage, Shapefile upload)
- [ ] Rate limiting and usage quotas per API key
- [ ] Multi-tenant support (separate collections per organization)
