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
| Interactive display | **X11 forwarding** from WSL2 → DevContainer → DinD | Live QGIS GUI for plugin development; uses host X server via socket mount |
| Container execution | **`docker run -d` + `docker exec`** via DinD | Persistent container for fast iteration; mirrors acceptance test setup/teardown pattern |

### Why `docker exec` (not docker-compose service)

The DevContainer uses `docker-in-docker` (DinD), meaning the `docker` CLI inside
the DevContainer talks to its **own Docker daemon**, not the host daemon that runs
the `.devcontainer/docker-compose.yml` services. A `qgis-test` service added as a
compose sibling would run on the host daemon — unreachable via `docker exec` from
inside the DevContainer.

Instead, the QGIS container is managed entirely through the DinD daemon:

1. **`scripts/qgis-test-setup.sh`** — pulls the image, starts a named container
   (`oapif-qgis-test`) in detached mode with Xvfb, volume mounts, and env vars.
   Resolves CFN stack outputs (base URL, User Pool domain URL, Client ID) and
   authenticates test users via `admin-initiate-auth` in the DevContainer. Passes
   the API base URL, Cognito token endpoint, client ID, and **refresh tokens**
   (valid 365 days) into the container — no further AWS access required.
2. **`scripts/qgis-test.sh`** — uses `docker exec` to run pytest in the already-
   running container. The conftest exchanges refresh tokens for fresh ID tokens
   via a simple HTTPS POST to the Cognito `/oauth2/token` endpoint (public,
   no AWS SDK needed). Fast iteration: no startup overhead per test run.
3. **`scripts/qgis-test-teardown.sh`** — stops and removes the container.

This mirrors the acceptance test pattern (`acceptance-setup.sh` → `pytest` →
`acceptance-teardown.sh`). If tests behave unexpectedly, tear down and rebuild
the container to eliminate stale state.

### No AWS credentials inside the QGIS container

The QGIS container has **no AWS SDK, credentials, or direct AWS access**. All AWS
interaction happens once, in the DevContainer, during `qgis-test-setup.sh`:

| What | Where | When |
|------|-------|------|
| Resolve CFN outputs (base URL, domain URL, client ID) | DevContainer (`qgis-test-setup.sh`) | Container startup |
| Authenticate test users → refresh tokens | DevContainer (`qgis-test-setup.sh`) | Container startup |
| Pass values to QGIS container | `docker run -e` | Container startup |
| Exchange refresh token → fresh ID token | QGIS container conftest (`urllib` POST to Cognito `/oauth2/token`) | Each test session |

Refresh tokens are valid for 365 days (configured in the auth stack), so the
container can run for months without re-running setup. Fresh ID tokens (~1 hour)
are obtained at the start of each pytest session via the **public** Cognito token
endpoint — a plain HTTPS POST, no AWS SDK or credentials needed.

This keeps the QGIS image lightweight (no boto3 installation) and avoids
forwarding sensitive AWS credentials into a second container.

### Interactive QGIS sessions

For visual plugin development, QGIS can be launched with a full GUI from the
persistent container. The X11 display chain is:

```
WSL2 X server  →  DevContainer (/tmp/.X11-unix, DISPLAY=:0)  →  DinD QGIS container
```

The setup script bind-mounts `/tmp/.X11-unix` into the container at creation time.
The interactive script then launches QGIS with the host display:

```bash
./scripts/qgis-interactive.sh              # launch QGIS GUI with plugin loaded
```

This runs `docker exec` with `DISPLAY=$DISPLAY` and `QT_QPA_PLATFORM=xcb`,
overriding the container's default `offscreen` platform. The plugin source is
already volume-mounted, so code changes are visible immediately after restarting
QGIS — no container rebuild needed.

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
# First-time setup (or after teardown):
./scripts/qgis-test-setup.sh               # pull image, start container, install deps

# Run tests (repeatable, fast — container stays running):
./scripts/qgis-test.sh                     # all tiers
./scripts/qgis-test.sh unit                # unit only (no QGIS needed)
./scripts/qgis-test.sh headless            # headless PyQGIS
./scripts/qgis-test.sh widget              # GUI widget tests
./scripts/qgis-test.sh headless widget     # combine tiers

# Interactive QGIS GUI (plugin development — requires WSL2 / X11):
./scripts/qgis-interactive.sh              # launch QGIS with plugin loaded

# When done, or to reset stale state:
./scripts/qgis-test-teardown.sh            # stop and remove container
```

---

## Phase P0: Test Infrastructure

Container setup/teardown scripts, test runner, CI integration, and the bare plugin
skeleton needed to validate that the test environment works.

- [x] Create `scripts/qgis-test-setup.sh` (container setup)
  - [x] Pull `qgis/qgis:ltr` image via DinD daemon
  - [x] Resolve CFN stack outputs in the DevContainer:
    - [x] `OAPIF_BASE_URL` from API stack `ApiUrl` output
    - [x] `OAPIF_TOKEN_ENDPOINT` from auth stack `UserPoolDomainUrl` output + `/oauth2/token`
    - [x] `OAPIF_CLIENT_ID` from auth stack `AppClientId` output
  - [x] Authenticate test users via `admin-initiate-auth` in the DevContainer:
    - [x] `OAPIF_EDITOR_REFRESH_TOKEN` for `test-editor@oapif.test`
    - [x] `OAPIF_ADMIN_REFRESH_TOKEN` for `test-admin@oapif.test`
    - [x] `OAPIF_VIEWER_REFRESH_TOKEN` for `test-viewer@oapif.test`
  - [x] `docker run -d --name oapif-qgis-test` with:
    - [x] Xvfb startup in entrypoint (`Xvfb :99 -screen 0 1024x768x24 &`)
    - [x] Volume mounts: workspace `plugin/` and `tests/` into container
    - [x] Bind-mount `/tmp/.X11-unix` from DevContainer (for interactive QGIS sessions)
    - [x] Environment: `QT_QPA_PLATFORM=offscreen`, `DISPLAY=:99` (Xvfb default for tests), plus all `OAPIF_*` vars above
    - [x] No AWS credentials — all AWS interaction stays in the DevContainer
  - [x] Install test dependencies inside the container (`pip install pytest pytest-cov`)
  - [x] `--status` flag: show whether container is running and healthy
  - [x] Idempotent: skip if container already running, print status
- [x] Create `scripts/qgis-test.sh` test runner
  - [x] Verify `oapif-qgis-test` container is running (helpful error if not: "Run ./scripts/qgis-test-setup.sh first")
  - [x] `docker exec oapif-qgis-test python3 -m pytest ...` with tier markers
  - [x] Accept tier arguments (`unit`, `headless`, `widget`, or omit for all)
  - [x] Map screenshot output to host-accessible directory
  - [x] Exit with pytest's exit code for CI integration
- [x] Create `scripts/qgis-test-teardown.sh` (container cleanup)
  - [x] `docker stop oapif-qgis-test && docker rm oapif-qgis-test`
  - [x] Idempotent: no error if container doesn't exist
  - [x] Optionally clean up `plugin/tests/output/`
- [x] Create `plugin/tests/conftest.py`
  - [x] `QgsApplication` init/teardown fixture (session-scoped, GUI mode based on tier)
  - [x] Plugin path injection (`sys.path` for plugin imports inside QGIS container)
  - [x] Base URL fixture (reads `OAPIF_BASE_URL` env var — set at container startup)
  - [x] Token refresh helper: POST `grant_type=refresh_token` to `OAPIF_TOKEN_ENDPOINT` with `OAPIF_CLIENT_ID` and persona refresh token via `urllib` (no AWS SDK)
  - [x] Session-scoped token fixtures that call the refresh helper to get fresh ID tokens from `OAPIF_EDITOR_REFRESH_TOKEN`, `OAPIF_ADMIN_REFRESH_TOKEN`, `OAPIF_VIEWER_REFRESH_TOKEN`
- [x] Create pytest marker definitions and config for plugin test tiers
- [x] Add `.gitignore` entries for `plugin/tests/output/`
- [x] Smoke test: start `QgsApplication`, assert `QgsProviderRegistry` has `OAPIF` provider, exit
- [x] Create `scripts/qgis-interactive.sh` (interactive QGIS session)
  - [x] Verify `oapif-qgis-test` container is running
  - [x] Refresh an ID token from the editor refresh token (same `urllib` POST as conftest)
  - [x] `docker exec -e DISPLAY=$DISPLAY -e QT_QPA_PLATFORM=xcb` to launch QGIS with host X server
  - [x] Load plugin from `/plugin` volume mount via `--code /plugin` or QGIS startup config
  - [x] Pass auth token and base URL so plugin connects on launch
- [x] Add GitHub Actions CI job for QGIS plugin tests
  - [x] Run `qgis-test-setup.sh` (after `acceptance-setup.sh`)
  - [x] Run `qgis-test.sh` for all tiers
  - [x] Run `qgis-test-teardown.sh` in `always()` post-step

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
