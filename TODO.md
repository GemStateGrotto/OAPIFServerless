# TODO — OAPIFServerless Build Plan

This document tracks the full build-out of the project. Phases are roughly sequential but some tasks within a phase can be parallelized.

---

## Phase 0: Project Scaffolding

- [x] Choose IaC approach (CDK vs SAM) and initialize project skeleton
  - Decision: **AWS CDK (Python)** — single language, no TypeScript/Python mix
- [x] Set up Python project structure with `pyproject.toml`, linting (ruff), and formatting (black)
- [x] Set up pytest with DynamoDB Local for integration tests
- [x] Create CI pipeline (GitHub Actions) for lint, test, and deploy
- [ ] Re-enable `--cov-fail-under=80` for integration test CI job once integration tests exist
- [x] Define environment variable / config schema for deployment parameters

## Phase 1: DynamoDB Data Layer

- [ ] Design and document final DynamoDB table schemas (features, change tracking, collection config)
- [ ] Implement data access layer (DAL) for feature CRUD against DynamoDB
  - [ ] `create_feature(collection_id, feature)` → assigns ID, sets ETag, writes to features + change log
  - [ ] `get_feature(collection_id, feature_id)` → returns feature with ETag
  - [ ] `query_features(collection_id, limit, cursor, bbox?, datetime?, property_filters?)` → paged results
  - [ ] `replace_feature(collection_id, feature_id, feature, if_match)` → conditional write, change log
  - [ ] `update_feature(collection_id, feature_id, patch, if_match)` → merge patch, conditional write, change log
  - [ ] `delete_feature(collection_id, feature_id, if_match)` → soft-delete, change log
- [ ] Implement ETag generation and conditional expression enforcement in DynamoDB
- [ ] Implement cursor-based pagination (encode/decode opaque cursor tokens)
- [ ] Write unit and integration tests for the DAL

## Phase 2: Collection Configuration and Schema

- [ ] Design collection configuration format defining:
  - [ ] Collection ID, title, description, extent
  - [ ] Feature schema (property names, types, required fields, enums)
  - [ ] `visibility` enum values for this collection
  - [ ] Organization-to-Cognito-group mapping
  - [ ] Access control group mappings
- [ ] Implement config loader (read from DynamoDB config table)
- [ ] Implement dynamic schema endpoint (`/collections/{collectionId}/schema`) returning JSON Schema
  - [ ] Mark `id` as `readOnly`
  - [ ] Mark geometry role with `x-ogc-role: primary-geometry`
  - [ ] Include `visibility` as enum per collection config
  - [ ] Include `organization` as read-only / server-populated field
  - [ ] Distinguish returnables vs receivables per Part 5
- [ ] Write tests for schema generation

## Phase 3: OAPIF Core (Read) Endpoints

- [ ] Implement Lambda request handler (API Gateway HTTP API event → response)
- [ ] Implement OAPIF Part 1 endpoints:
  - [ ] `GET /` — Landing page with required links (self, service-desc, service-doc, conformance, data)
  - [ ] `GET /conformance` — Conformance declaration
  - [ ] `GET /api` — OpenAPI 3.0 definition (dynamically generated from collection configs)
  - [ ] `GET /collections` — List all collections with extent, links, itemType
  - [ ] `GET /collections/{collectionId}` — Single collection metadata
  - [ ] `GET /collections/{collectionId}/items` — Feature collection with paging, bbox, datetime, property filters
  - [ ] `GET /collections/{collectionId}/items/{featureId}` — Single feature with ETag header
  - [ ] `GET /collections/{collectionId}/schema` — JSON Schema for the collection
- [ ] Implement content negotiation (GeoJSON primary; JSON for non-feature resources)
- [ ] Implement `Link` headers and response link objects (self, alternate, next, collection)
- [ ] Implement `numberMatched` / `numberReturned` / `timeStamp` in collection responses
- [ ] Write integration tests against DynamoDB Local for all read endpoints

## Phase 4: Authentication and Authorization Infrastructure

- [ ] Define Cognito User Pool with OIDC configuration (CDK)
  - [ ] Configure hosted UI domain for OIDC authorization code flow
  - [ ] Define app client for QGIS plugin (PKCE, authorization code flow)
  - [ ] Define app client for machine-to-machine (client credentials, optional)
- [ ] Define Cognito groups matching access control model:
  - [ ] Organization groups (one per org, e.g., `org:GemStateGrotto`)
  - [ ] Visibility-level groups within each org (e.g., `GemStateGrotto:restricted`, `GemStateGrotto:members`)
  - [ ] Role groups (e.g., `editor`, `admin`, `viewer`, per-collection variants)
- [ ] Configure API Gateway with optional JWT authorizer (allow unauthenticated GET requests)
- [ ] Implement Lambda middleware to extract and validate Cognito claims and group memberships
- [ ] Implement unauthenticated path: require `organization` query parameter, restrict to `public` visibility
- [ ] For authenticated requests, derive org from JWT; validate `organization` param if provided
- [ ] Write tests for token parsing, group extraction, and unauthenticated org-parameter flow

## Phase 5: Row-Level Access Control

- [ ] Implement organization tenant scoping: extract caller's org from JWT (authenticated) or `organization` query param (unauthenticated), scope all queries to that org (hard boundary, never cross-org)
- [ ] For unauthenticated requests: require `organization` query parameter, enforce `visibility = public` only
- [ ] For authenticated requests: derive org from Cognito groups, validate `organization` param if provided
- [ ] Auto-populate `organization` on feature creation from caller's Cognito org group
- [ ] Reject PUT/PATCH attempts to change `organization` field
- [ ] Implement visibility filter builder: given a user's Cognito groups, build a filter for `visibility` within the org
- [ ] Apply org + visibility filters in `query_features` and `get_feature` DAL methods (filter at query time, not post-query)
- [ ] Return `404` (not `403`) when a user requests a specific feature they cannot see
- [ ] Ensure `numberMatched` and collection extents reflect only visible features within the caller's org and visibility level
- [ ] Write tests: unauthenticated user with `organization=X` sees only `public` items; user in org X never sees org Y features; user with `members` access sees `public` + `members` but not `restricted`

## Phase 6: OAPIF Part 4 (Write) Endpoints

- [ ] Implement write endpoints:
  - [ ] `POST /collections/{collectionId}/items` — Create feature (201 + Location header)
  - [ ] `PUT /collections/{collectionId}/items/{featureId}` — Replace feature (204, ETag in response)
  - [ ] `PATCH /collections/{collectionId}/items/{featureId}` — Update feature via JSON Merge Patch (200 or 204)
  - [ ] `DELETE /collections/{collectionId}/items/{featureId}` — Delete feature (204)
  - [ ] `OPTIONS` on items and item endpoints — Return Allow header with supported methods
- [ ] Enforce `If-Match` / ETag optimistic concurrency on PUT, PATCH, DELETE
  - [ ] Return `412 Precondition Failed` on ETag mismatch
  - [ ] Optionally return `428 Precondition Required` if `If-Match` is omitted
- [ ] Validate request bodies against collection schema; return `422` on schema violation
- [ ] Write all mutations to the change tracking table
- [ ] Write integration tests for the full CRUD lifecycle

## Phase 7: Field-Level Authorization

- [ ] Define field-level permission model:
  - [ ] `editor` groups can modify geometry + feature attribute properties
  - [ ] `admin` groups can modify `visibility` and group membership metadata (`organization` is always immutable)
  - [ ] Viewers cannot write at all
- [ ] Implement server-side field-level enforcement in PUT/PATCH handlers:
  - [ ] Parse incoming changes, compare to allowed fields for the caller's role
  - [ ] Reject with `403 Forbidden` and a clear error message if unauthorized fields are modified
- [ ] Write tests: editor can change geometry but not visibility; admin can change visibility but not organization; viewer is rejected

## Phase 8: QGIS Plugin — Authentication

- [ ] Scaffold QGIS plugin structure (`metadata.txt`, `__init__.py`, etc.)
- [ ] Implement OIDC authorization code flow with PKCE against Cognito hosted UI
  - [ ] Launch system browser for login
  - [ ] Listen on localhost redirect URI to capture authorization code
  - [ ] Exchange code for tokens; store refresh token securely
  - [ ] Auto-refresh access token before expiry
- [ ] Register a custom `QgsAuthMethodConfig` or `QgsNetworkAccessManager` handler to inject Bearer tokens
- [ ] Write tests for token lifecycle (mock Cognito responses)

## Phase 9: QGIS Plugin — Feature Layer Access

- [ ] Implement OAPIF data provider or use QGIS's built-in WFS/OAPIF provider with custom auth
- [ ] Connect to `/collections` to list available layers
- [ ] Load features from `/collections/{collectionId}/items` as a QGIS vector layer
- [ ] Support paging (follow `next` links automatically)
- [ ] Support `bbox` filter based on current map extent
- [ ] For authorized users, support editing features and pushing changes via PUT/PATCH/DELETE
- [ ] Handle `412 Precondition Failed` gracefully (prompt user to reload and retry)

## Phase 10: QGIS Plugin — Project File Sync

- [ ] Implement S3 presigned URL flow for project file download/upload
  - [ ] Lambda endpoint: `GET /projects/{projectId}/download` → presigned S3 GET URL
  - [ ] Lambda endpoint: `PUT /projects/{projectId}/upload` → presigned S3 PUT URL
- [ ] QGIS plugin UI to browse available projects, download `.qgz`, and open
- [ ] QGIS plugin UI to save current project and upload to S3 (editor/admin only)
- [ ] Handle concurrent project edits (last-write-wins or warn user)

## Phase 11: Deployment System

- [x] Define CDK stack architecture: `DataStack` (stateful) + `ApiStack` (stateless)
- [x] Implement `RemovalPolicy.RETAIN` and termination protection for non-dev environments
- [x] Implement deployment config via environment variables (`OAPIF_*`) and CDK context
- [ ] Finalize CDK stacks:
  - [ ] Auth stack: Cognito User Pool, clients, groups, domain (Phase 4)
  - [ ] Wire API Gateway routes to Lambda (Phase 3 / Phase 6)
- [ ] Create deployment CLI or Makefile with `bootstrap`, `deploy`, `destroy` commands
- [ ] Write deployment documentation with prerequisites (AWS CLI, Node.js, Python)
- [ ] Test full deploy-from-scratch on a clean AWS account
- [ ] Add support for custom domain name on API Gateway (optional)

## Phase 12: OpenAPI Definition and Documentation

- [ ] Generate OpenAPI 3.0 definition dynamically from collection configs
  - [ ] Include all Part 1 and Part 4 paths
  - [ ] Include per-collection schema references
  - [ ] Include security scheme (Cognito JWT bearer)
- [ ] Serve OpenAPI definition at `/api` (JSON) and link from landing page
- [ ] Optionally serve Swagger UI or Redoc at `/api.html`
- [ ] Validate generated OpenAPI definition against OGC API Features conformance tests

## Phase 13: Testing and Compliance

- [ ] Run OGC API - Features conformance test suite (CITE) against deployed instance
- [ ] Test QGIS plugin against the deployed API end-to-end
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
