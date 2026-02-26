#!/usr/bin/env bash
# Tear down the QGIS plugin test container.
#
# Stops and removes the persistent QGIS Docker container started by
# qgis-test-setup.sh. Idempotent — no error if the container doesn't exist.
#
# Usage:
#   ./scripts/qgis-test-teardown.sh
#   ./scripts/qgis-test-teardown.sh --clean   # also remove test output files

set -euo pipefail

CONTAINER_NAME="oapif-qgis-test"
WORKSPACE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo -e "\033[36m▶\033[0m $*"; }
ok()   { echo -e "\033[32m✓\033[0m $*"; }
skip() { echo -e "\033[33m⊘\033[0m $* (not found)"; }

# ── Stop and remove container ────────────────────────────────────────

if docker inspect "$CONTAINER_NAME" &>/dev/null; then
    info "Stopping container $CONTAINER_NAME..."
    docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    ok "Container removed"
else
    skip "Container $CONTAINER_NAME"
fi

# ── Optionally clean up test output ──────────────────────────────────

if [[ "${1:-}" == "--clean" ]]; then
    OUTPUT_DIR="${WORKSPACE_DIR}/plugin/tests/output"
    if [[ -d "$OUTPUT_DIR" ]]; then
        info "Cleaning test output directory..."
        rm -rf "$OUTPUT_DIR"
        ok "Removed $OUTPUT_DIR"
    else
        skip "Output directory"
    fi
fi

echo ""
ok "Teardown complete."
