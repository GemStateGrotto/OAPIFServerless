# TODO — QGIS Plugin Build Plan

This document tracks the build-out of the OAPIFServerless QGIS plugin. Phases are
organized by **testing methodology** — each phase groups features by the testing
infrastructure required to validate them, progressing from the simplest (standard
pytest) to the most complex (GUI widget tests with QTest + Xvfb).

Plugin source lives in `plugin/`. Tests live in `plugin/tests/`.

See the root [TODO.md](../TODO.md) for overall project status and the Phase 10
backend (Lambda endpoints, CDK) that supports project file sync.

---

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| QGIS version | **LTR** (`qgis/qgis:ltr`) | Stable; matches what most users run |
| Python target | **3.12** (QGIS-bundled) | Plugin must target QGIS's bundled Python, not the backend's 3.14 |
| OAPIF provider | **Built-in + custom auth** | Leverages QGIS-maintained OAPIF provider; only auth injection is custom |
| Test environment | **Docker** (QGIS image + Xvfb) | Full isolation; reproducible; CI-friendly; no DevContainer bloat |
| Display backend | **Xvfb** for GUI widget tests; `offscreen` for headless | Xvfb gives truer rendering for widget tests; offscreen is lighter for headless tests |

## Test Tiers

All plugin tests run inside the QGIS Docker container (except Tier 1 unit tests,
which can also run in the DevContainer with standard pytest). Tests are organized
into tiers based on infrastructure requirements:

| Tier | Marker | Requires | Runs in |
|------|--------|----------|---------|
| **1. Unit** | `@pytest.mark.qgis_unit` | Nothing (pure Python) | DevContainer pytest **or** QGIS Docker |
| **2. Headless** | `@pytest.mark.qgis_headless` | `QgsApplication([], False)` | QGIS Docker (`QT_QPA_PLATFORM=offscreen`) |
| **3. Widget** | `@pytest.mark.qgis_widget` | `QgsApplication([], True)` + QTest | QGIS Docker + Xvfb |

Run tiers selectively:

```bash
./scripts/qgis-test.sh                    # all tiers
./scripts/qgis-test.sh unit               # unit only (no QGIS needed)
./scripts/qgis-test.sh headless           # headless PyQGIS
./scripts/qgis-test.sh widget             # GUI widget tests
./scripts/qgis-test.sh headless widget    # combine tiers
```

---

## Phase P0: Test Infrastructure

Docker Compose service, test runner, CI integration, and the bare plugin skeleton
needed to validate that the test environment works.

- [ ] Add `qgis-test` service to `.devcontainer/docker-compose.yml`
  - [ ] Image: `qgis/qgis:ltr`
  - [ ] Xvfb startup in entrypoint (`Xvfb :99 -screen 0 1024x768x24 &`)
  - [ ] Volume mounts: `./plugin:/plugin` (source), `./tests:/tests` (shared fixtures)
  - [ ] Environment: `QT_QPA_PLATFORM`, `DISPLAY=:99`, `OAPIF_ENVIRONMENT`
  - [ ] AWS credentials forwarded for live API tests
- [ ] Create `scripts/qgis-test.sh` test runner
  - [ ] Accept tier arguments (`unit`, `headless`, `widget`, or omit for all)
  - [ ] Pull/build QGIS Docker image
  - [ ] Run pytest inside the container with appropriate markers
  - [ ] Copy screenshot output to host-accessible directory
  - [ ] Exit with pytest's exit code for CI integration
- [ ] Create `plugin/tests/conftest.py`
  - [ ] `QgsApplication` init/teardown fixture (session-scoped, GUI mode based on tier)
  - [ ] Plugin path injection (`sys.path` for plugin imports inside QGIS container)
  - [ ] Base URL fixture (from CloudFormation outputs, shared with acceptance tests)
  - [ ] Authenticated token fixture (Cognito `admin-initiate-auth` for headless tests)
- [ ] Create pytest marker definitions and config for plugin test tiers
- [ ] Add `.gitignore` entries for `plugin/tests/output/`
- [ ] Smoke test: start `QgsApplication`, assert `QgsProviderRegistry` has `OAPIF` provider, exit
- [ ] Add GitHub Actions CI job for QGIS plugin tests (runs after acceptance-setup)

## Phase P1: Plugin Scaffolding + Pure Python Core

Everything in this phase is plain Python with **no PyQGIS dependency**. Tests run
with standard pytest in the DevContainer or in QGIS Docker with `qgis_unit` marker.

### Plugin Structure

- [ ] Create plugin directory layout:
  - [ ] `plugin/metadata.txt` — QGIS plugin metadata (name, version, `qgisMinimumVersion`, author, description, repository URL, tracker URL)
  - [ ] `plugin/__init__.py` — plugin entry point (`classFactory`)
  - [ ] `plugin/plugin.py` — main `QgsPluginInterface` implementation (stub for now)
  - [ ] `plugin/resources/` — icons and UI resources

### HTTP Client

- [ ] Implement OAPIF HTTP client wrapper (pure Python, `urllib` or `httpx`)
  - [ ] `get_landing_page(base_url)` → landing page JSON with links
  - [ ] `get_collections(base_url)` → list of collection metadata
  - [ ] `get_collection(base_url, collection_id)` → single collection
  - [ ] `get_features(base_url, collection_id, bbox?, limit?)` → feature collection
  - [ ] `get_feature(base_url, collection_id, feature_id)` → single feature + ETag
  - [ ] `create_feature(base_url, collection_id, feature, token)` → feature ID + ETag
  - [ ] `update_feature(base_url, collection_id, feature_id, feature, etag, token)` → new ETag
  - [ ] `delete_feature(base_url, collection_id, feature_id, etag, token)` → success
  - [ ] Pagination: follow `next` links automatically, collect all pages
  - [ ] `Content-Type` negotiation (request `application/geo+json`)

### OIDC / PKCE Token Management

- [ ] Implement OIDC discovery: fetch `.well-known/openid-configuration` from Cognito
- [ ] Implement PKCE authorization URL construction (`code_challenge`, `state`, `nonce`)
- [ ] Implement localhost redirect listener (ephemeral port, capture authorization code)
- [ ] Implement code-to-token exchange (POST to Cognito token endpoint)
- [ ] Implement token parsing: extract `access_token`, `id_token`, `refresh_token`, expiry
- [ ] Implement token refresh flow (use `refresh_token` before `access_token` expires)
- [ ] Implement secure token storage (platform keyring or encrypted file)

### Configuration

- [ ] Implement server connection config (base URL, Cognito domain, client ID)
- [ ] Implement config persistence (QSettings-compatible, JSON file fallback)
- [ ] Implement collection selection state management

### Tests (Tier 1: Unit)

- [ ] HTTP client: mock responses for all endpoints, validate URL construction, header injection, pagination link following
- [ ] OIDC/PKCE: mock Cognito discovery and token exchange, validate PKCE challenge/verifier generation
- [ ] Token lifecycle: mock token expiry detection and refresh flow, validate error handling on refresh failure
- [ ] Config: serialize/deserialize settings, validate defaults, test edge cases (missing fields, invalid URLs)

## Phase P2: Auth + Data Provider — Headless PyQGIS

Integrates the pure Python core with QGIS's auth system and built-in OAPIF data
provider. Tests require headless PyQGIS (`QgsApplication([], False)`) running in
QGIS Docker.

### Auth Integration

- [ ] Register `QgsAuthMethodConfig` for OAuth2 Bearer token injection
- [ ] Implement `QgsNetworkAccessManager` request interceptor: add `Authorization: Bearer <token>` header to outbound OAPIF requests
- [ ] Implement automatic token refresh on 401 response inside the QGIS network stack
- [ ] Validate auth config survives `QgsProject` save/load cycle

### Data Provider Connection

- [ ] Configure QGIS built-in OAPIF provider to use the registered auth config ID
- [ ] Create `QgsVectorLayer` from OAPIF endpoint URL with auth
- [ ] Validate layer validity, CRS (`EPSG:4326`), geometry type detection
- [ ] Validate feature attribute mapping (collection schema properties → `QgsFields`)
- [ ] Validate feature count matches server `numberMatched`
- [ ] Validate pagination: provider auto-follows `next` links to load all features
- [ ] Validate bbox filter: request features within a specified extent

### Tests (Tier 2: Headless)

- [ ] Auth config registration: create config, inject into `QgsAuthManager`, validate token appears in outbound request headers
- [ ] Unauthenticated connectivity: load public features from `acceptance-test` collection with `?organization=TestOrgA`, assert `layer.isValid()`, assert `featureCount() >= 3`
- [ ] Authenticated connectivity: configure auth, load features as `test-editor`, validate access to `members`-visibility features
- [ ] Feature attribute mapping: verify `name`, `depth_m`, `survey_date`, `status` fields exist with correct `QVariant` types
- [ ] Geometry validation: iterate features, assert Point geometry type, validate coordinates within expected bbox (roughly Idaho/Montana area)
- [ ] Pagination: if enough features exist, verify all pages loaded (feature count matches `numberMatched`)
- [ ] Bbox filter: request features within a sub-extent, verify only features within bbox returned

## Phase P3: Feature Editing — Headless PyQGIS

Extends Phase P2 with write operations through the plugin. Tests run headless in
QGIS Docker against the live deployed API.

### Edit Operations

- [ ] Implement feature creation flow: build GeoJSON from `QgsFeature`, POST via HTTP client
- [ ] Implement feature update flow: detect modified attributes/geometry, PUT/PATCH with ETag
- [ ] Implement feature delete flow: DELETE with ETag from last-fetched feature
- [ ] Implement ETag tracking: cache ETags per feature ID, update on every server response
- [ ] Implement conflict detection: catch `412 Precondition Failed`, fetch latest version from server
- [ ] Implement conflict resolution data model: store both local and server versions for later UI prompt
- [ ] Implement layer refresh after successful write (re-fetch affected features from provider)

### Tests (Tier 2: Headless)

- [ ] Create feature: POST a new Point feature via plugin, verify it appears in subsequent GET
- [ ] Update feature: modify attributes, PUT with correct ETag, verify update persisted on server
- [ ] Delete feature: DELETE with correct ETag, verify feature no longer returned
- [ ] ETag tracking: create feature, verify ETag cached; update feature, verify ETag updated
- [ ] ETag concurrency: create feature, modify server-side (via acceptance test HTTP client to simulate second user), attempt PUT from plugin → expect 412
- [ ] Conflict resolution data: after 412, verify plugin fetches latest version and stores both local and server copies
- [ ] Cleanup: all test-created features are deleted after test session (session-scoped finalizer fixture)

## Phase P4: GUI Widgets — QTest + Xvfb

All plugin GUI components. Tests use `QTest` to simulate user interactions (mouse
clicks, keyboard input, dialog accept/reject) running under Xvfb in QGIS Docker.

### Dialogs and Panels

- [ ] **Server connection dialog**
  - [ ] URL input field with validation (must resolve to a valid OAPIF landing page)
  - [ ] "Test Connection" button → hit landing page, show success/failure indicator
  - [ ] "Authenticate" button → trigger OIDC/PKCE flow (launch system browser)
  - [ ] Auth status indicator (authenticated username, token expiry countdown, refresh button)
  - [ ] Save/load named server profiles
- [ ] **Layer browser panel**
  - [ ] List collections from connected server (title, geometry type, feature count)
  - [ ] Collection metadata tooltip or expandable detail (description, extent, properties)
  - [ ] "Add to Map" button → create `QgsVectorLayer` from selected collection
  - [ ] Filter/search collections by name
- [ ] **Feature edit form**
  - [ ] Custom `QgsEditorWidgetWrapper` for OAPIF-specific field behavior
  - [ ] Enforce field-level authorization hints in UI (gray out / disable immutable fields like `organization`)
  - [ ] Show ETag / version info for the current feature
- [ ] **Conflict resolution dialog**
  - [ ] Show local vs. server version side-by-side (table of changed fields)
  - [ ] "Use Server Version" / "Force Overwrite" / "Cancel" action buttons
  - [ ] Highlight changed fields between local and server versions
- [ ] **Project file browser dialog** (Phase 10 plugin UI)
  - [ ] List available project files from `/projects` endpoint
  - [ ] "Download & Open" action → fetch presigned URL → download `.qgz` → open in QGIS
  - [ ] "Upload Current Project" action → save `.qgz` → fetch presigned URL → upload (editor/admin only)
  - [ ] Show upload/download progress bar
- [ ] **Settings panel**
  - [ ] Default server URL
  - [ ] Auth configuration preferences
  - [ ] Cache and refresh behavior

### Tests (Tier 3: Widget)

- [ ] Connection dialog: simulate URL text input → click "Test Connection" → assert success indicator shown after mock response
- [ ] Connection dialog: enter invalid URL → click "Test Connection" → assert error message displayed
- [ ] Connection dialog: click "Authenticate" → verify OIDC flow signal emitted (mock browser launch)
- [ ] Connection dialog: save profile → close → reopen → verify profile restored
- [ ] Layer browser: connect to server → verify collection list populated with correct titles → select collection → click "Add to Map" → verify `QgsVectorLayer` added to `QgsProject.instance()`
- [ ] Layer browser: type in filter field → verify collection list filtered to matching names
- [ ] Conflict dialog: instantiate with mock local/server feature data → click "Use Server Version" → verify correct signal emitted with server feature
- [ ] Conflict dialog: click "Force Overwrite" → verify overwrite signal emitted with local feature
- [ ] Project browser: list projects from mock response → click "Download & Open" → verify presigned URL fetch initiated
- [ ] Project browser: verify "Upload Current Project" button disabled for viewer role
- [ ] Settings panel: change values → save → reopen → verify values persisted via QSettings

---

## Appendix: Test Prerequisites

- Docker available in the DevContainer (Docker-in-Docker is pre-configured)
- Deployed API with `acceptance-test` collection (run `./scripts/acceptance-setup.sh` first)
- AWS credentials configured and `OAPIF_ENVIRONMENT` set
- Phase 10 backend (Lambda + CDK) deployed for project file browser tests
