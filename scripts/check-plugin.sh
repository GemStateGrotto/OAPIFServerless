#!/usr/bin/env bash
# Plugin quality gate wrapper — runs check.sh inside the QGIS container.
#
# This is a thin wrapper that delegates to plugin/scripts/check.sh
# via docker exec in the oapif-qgis-test container.
#
# Usage:
#   ./scripts/check-plugin.sh          # run all plugin checks
#   ./scripts/check-plugin.sh --fix    # auto-fix lint/format, then check
#   ./scripts/check-plugin.sh lint     # ruff only
#   ./scripts/check-plugin.sh types    # mypy only
#   ./scripts/check-plugin.sh --fix lint  # auto-fix lint only
#
# On success, writes .checks_passed_plugin timestamp. The pre-commit
# hook accepts this when only plugin/ files are staged.
#
# Requires: ./scripts/qgis-test-setup.sh (starts the container)

set -euo pipefail

CONTAINER_NAME="oapif-qgis-test"

# ── Verify container is running ──────────────────────────────────────

if ! docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null | grep -q running; then
    echo "ERROR: Container $CONTAINER_NAME is not running."
    echo "Run ./scripts/qgis-test-setup.sh first."
    exit 1
fi

# ── Run checks inside the container ─────────────────────────────────

docker exec "$CONTAINER_NAME" /plugin/scripts/check.sh "$@"
rc=$?

# ── Copy timestamp to host if successful ─────────────────────────────

STAMP="/plugin/.checks_passed_plugin"
if [[ $rc -eq 0 ]] && docker exec "$CONTAINER_NAME" test -f "$STAMP" 2>/dev/null; then
    ROOT="$(git rev-parse --show-toplevel)"
    docker exec "$CONTAINER_NAME" cat "$STAMP" > "$ROOT/.checks_passed_plugin"
fi

exit $rc
