"""QGIS plugin test fixtures — run inside the QGIS Docker container.

Provides:
  - QgsApplication init/teardown (session-scoped, GUI mode based on tier)
  - Plugin path injection (sys.path for plugin imports)
  - Base URL fixture (reads OAPIF_BASE_URL env var)
  - Token refresh helper: POSTs to Cognito /oauth2/token endpoint
    with refresh_token grant and OAPIF_CLIENT_ID (no AWS SDK needed)
  - Session-scoped token fixtures for editor, admin, viewer personas

Environment variables (set at container startup by qgis-test-setup.sh):
  OAPIF_BASE_URL              — API base URL
  OAPIF_TOKEN_ENDPOINT        — Cognito /oauth2/token URL
  OAPIF_CLIENT_ID             — Cognito app client ID
  OAPIF_EDITOR_REFRESH_TOKEN  — Refresh token for test-editor
  OAPIF_ADMIN_REFRESH_TOKEN   — Refresh token for test-admin
  OAPIF_VIEWER_REFRESH_TOKEN  — Refresh token for test-viewer
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Plugin path injection
# ---------------------------------------------------------------------------

# When running inside the QGIS container, plugin/ is mounted at /plugin.
# Add it to sys.path so `import plugin.*` works.
_plugin_dir = Path("/plugin")
if _plugin_dir.is_dir() and str(_plugin_dir) not in sys.path:
    sys.path.insert(0, str(_plugin_dir))


# ---------------------------------------------------------------------------
# QgsApplication management
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qgis_app(request: pytest.FixtureRequest) -> Any:
    """Initialize QgsApplication for the test session.

    GUI mode is determined by the test markers:
    - qgis_widget tests → QgsApplication([], True)  (GUI enabled)
    - qgis_headless tests → QgsApplication([], False) (no GUI)
    - qgis_unit tests → no QgsApplication needed (returns None)

    For mixed sessions, GUI mode is enabled if any widget test is collected.
    """
    # Determine if we need QGIS at all
    markers = set()
    for item in request.session.items:
        for marker in item.iter_markers():
            markers.add(marker.name)

    if markers <= {"qgis_unit"}:
        # Pure unit tests — no QgsApplication needed
        yield None
        return

    # Import QGIS only when needed (not available in DevContainer)
    from qgis.core import QgsApplication

    gui_enabled = "qgis_widget" in markers
    app = QgsApplication([], gui_enabled)
    app.initQgis()

    yield app

    app.exitQgis()


# ---------------------------------------------------------------------------
# Base URL
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def base_url() -> str:
    """API base URL from container environment."""
    url = os.environ.get("OAPIF_BASE_URL", "")
    if not url:
        pytest.skip("OAPIF_BASE_URL not set — run qgis-test-setup.sh first")
    return url.rstrip("/")


# ---------------------------------------------------------------------------
# Token refresh helper
# ---------------------------------------------------------------------------


def _refresh_id_token(
    token_endpoint: str,
    client_id: str,
    refresh_token: str,
) -> str:
    """Exchange a Cognito refresh token for a fresh ID token.

    Uses a plain HTTPS POST to the public Cognito /oauth2/token endpoint.
    No AWS SDK or credentials needed.
    """
    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        token_endpoint,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            id_token: str = body["id_token"]
            return id_token
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        msg = f"Token refresh failed ({exc.code}): {error_body}"
        raise RuntimeError(msg) from exc


def _get_token_config() -> tuple[str, str]:
    """Read token endpoint and client ID from environment."""
    endpoint = os.environ.get("OAPIF_TOKEN_ENDPOINT", "")
    client_id = os.environ.get("OAPIF_CLIENT_ID", "")
    if not endpoint or not client_id:
        pytest.skip("OAPIF_TOKEN_ENDPOINT / OAPIF_CLIENT_ID not set")
    return endpoint, client_id


# ---------------------------------------------------------------------------
# Session-scoped token fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def editor_token() -> str:
    """Fresh ID token for test-editor persona."""
    endpoint, client_id = _get_token_config()
    refresh = os.environ.get("OAPIF_EDITOR_REFRESH_TOKEN", "")
    if not refresh:
        pytest.skip("OAPIF_EDITOR_REFRESH_TOKEN not set")
    return _refresh_id_token(endpoint, client_id, refresh)


@pytest.fixture(scope="session")
def admin_token() -> str:
    """Fresh ID token for test-admin persona."""
    endpoint, client_id = _get_token_config()
    refresh = os.environ.get("OAPIF_ADMIN_REFRESH_TOKEN", "")
    if not refresh:
        pytest.skip("OAPIF_ADMIN_REFRESH_TOKEN not set")
    return _refresh_id_token(endpoint, client_id, refresh)


@pytest.fixture(scope="session")
def viewer_token() -> str:
    """Fresh ID token for test-viewer persona."""
    endpoint, client_id = _get_token_config()
    refresh = os.environ.get("OAPIF_VIEWER_REFRESH_TOKEN", "")
    if not refresh:
        pytest.skip("OAPIF_VIEWER_REFRESH_TOKEN not set")
    return _refresh_id_token(endpoint, client_id, refresh)
