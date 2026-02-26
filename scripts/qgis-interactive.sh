#!/usr/bin/env bash
# Launch an interactive QGIS session from the persistent test container.
#
# Uses X11 forwarding to display the QGIS GUI on the host display.
# The plugin source is already volume-mounted at /plugin, so code changes
# are visible immediately after restarting QGIS.
#
# Prerequisites:
#   - Container running (./scripts/qgis-test-setup.sh)
#   - X11 display available (WSL2 X server → DevContainer → DinD container)
#   - /tmp/.X11-unix mounted in container (done by setup script)
#
# Usage:
#   ./scripts/qgis-interactive.sh

set -euo pipefail

CONTAINER_NAME="oapif-qgis-test"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo -e "\033[36m▶\033[0m $*"; }
ok()   { echo -e "\033[32m✓\033[0m $*"; }

# ── Verify container is running ──────────────────────────────────────

if ! docker inspect "$CONTAINER_NAME" &>/dev/null; then
    die "Container $CONTAINER_NAME does not exist. Run ./scripts/qgis-test-setup.sh first."
fi

STATE=$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME")
if [[ "$STATE" != "running" ]]; then
    die "Container $CONTAINER_NAME is $STATE, not running. Run ./scripts/qgis-test-setup.sh first."
fi

# ── Verify DISPLAY is set ───────────────────────────────────────────

if [[ -z "${DISPLAY:-}" ]]; then
    die "DISPLAY is not set. X11 forwarding is required for interactive QGIS sessions.
    
If using WSL2, ensure an X server (e.g. VcXsrv, X410) is running and
DISPLAY is set (typically :0 or :0.0)."
fi

info "Using DISPLAY=$DISPLAY"

# ── Refresh an ID token for the editor persona ──────────────────────

info "Refreshing editor ID token..."

# Read env vars from the running container
TOKEN_ENDPOINT=$(docker exec "$CONTAINER_NAME" printenv OAPIF_TOKEN_ENDPOINT 2>/dev/null || true)
CLIENT_ID=$(docker exec "$CONTAINER_NAME" printenv OAPIF_CLIENT_ID 2>/dev/null || true)
REFRESH_TOKEN=$(docker exec "$CONTAINER_NAME" printenv OAPIF_EDITOR_REFRESH_TOKEN 2>/dev/null || true)

if [[ -z "$TOKEN_ENDPOINT" || -z "$CLIENT_ID" || -z "$REFRESH_TOKEN" ]]; then
    die "Missing token config in container. Re-run ./scripts/qgis-test-setup.sh"
fi

# Exchange refresh token for fresh ID token via public Cognito endpoint
ID_TOKEN=$(curl -s -X POST "$TOKEN_ENDPOINT" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=refresh_token&client_id=${CLIENT_ID}&refresh_token=${REFRESH_TOKEN}" \
    | python3 -c "import sys, json; print(json.load(sys.stdin).get('id_token', ''))")

if [[ -z "$ID_TOKEN" ]]; then
    die "Failed to refresh ID token. Try re-running ./scripts/qgis-test-setup.sh"
fi

ok "Got fresh ID token"

# ── Launch QGIS ─────────────────────────────────────────────────────

BASE_URL=$(docker exec "$CONTAINER_NAME" printenv OAPIF_BASE_URL 2>/dev/null || true)

info "Launching QGIS with plugin from /plugin..."
info "Base URL: $BASE_URL"
info "Close QGIS to return to the shell."

docker exec -it \
    -e "DISPLAY=$DISPLAY" \
    -e "QT_QPA_PLATFORM=xcb" \
    -e "OAPIF_ID_TOKEN=$ID_TOKEN" \
    -e "OAPIF_BASE_URL=$BASE_URL" \
    "$CONTAINER_NAME" \
    qgis --code /plugin/scripts/startup.py
