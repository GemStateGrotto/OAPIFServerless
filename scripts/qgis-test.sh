#!/usr/bin/env bash
# Run QGIS plugin tests inside the persistent QGIS Docker container.
#
# Executes pytest via `docker exec` against the already-running container
# started by `qgis-test-setup.sh`. The container stays running between
# test runs for fast iteration.
#
# Usage:
#   ./scripts/qgis-test.sh                  # all tiers
#   ./scripts/qgis-test.sh unit             # unit only (no QGIS needed)
#   ./scripts/qgis-test.sh headless         # headless PyQGIS
#   ./scripts/qgis-test.sh widget           # GUI widget tests (Xvfb)
#   ./scripts/qgis-test.sh headless widget  # combine tiers
#
# Exit code matches pytest's exit code for CI integration.

set -euo pipefail

CONTAINER_NAME="oapif-qgis-test"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo -e "\033[36m▶\033[0m $*"; }

# ── Verify container is running ──────────────────────────────────────

if ! docker inspect "$CONTAINER_NAME" &>/dev/null; then
    die "Container $CONTAINER_NAME does not exist. Run ./scripts/qgis-test-setup.sh first."
fi

STATE=$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME")
if [[ "$STATE" != "running" ]]; then
    die "Container $CONTAINER_NAME is $STATE, not running. Run ./scripts/qgis-test-setup.sh first."
fi

# ── Build marker expression from tier arguments ─────────────────────

MARKER_EXPR=""
for arg in "$@"; do
    case "$arg" in
        unit)
            if [[ -n "$MARKER_EXPR" ]]; then
                MARKER_EXPR="$MARKER_EXPR or qgis_unit"
            else
                MARKER_EXPR="qgis_unit"
            fi
            ;;
        headless)
            if [[ -n "$MARKER_EXPR" ]]; then
                MARKER_EXPR="$MARKER_EXPR or qgis_headless"
            else
                MARKER_EXPR="qgis_headless"
            fi
            ;;
        widget)
            if [[ -n "$MARKER_EXPR" ]]; then
                MARKER_EXPR="$MARKER_EXPR or qgis_widget"
            else
                MARKER_EXPR="qgis_widget"
            fi
            ;;
        *)
            die "Unknown tier: $arg. Use: unit, headless, widget"
            ;;
    esac
done

# ── Build pytest command ─────────────────────────────────────────────

PYTEST_ARGS=(
    python3 -m pytest
    /plugin/tests
    -v
    --tb=short
)

if [[ -n "$MARKER_EXPR" ]]; then
    PYTEST_ARGS+=(-m "$MARKER_EXPR")
    info "Running tiers: $MARKER_EXPR"
else
    info "Running all test tiers"
fi

# ── Execute tests ────────────────────────────────────────────────────

docker exec "$CONTAINER_NAME" "${PYTEST_ARGS[@]}"
