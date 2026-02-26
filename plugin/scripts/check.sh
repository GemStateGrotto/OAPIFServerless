#!/usr/bin/env bash
# Plugin quality gate — runs inside the QGIS Docker container.
#
# Runs ruff (lint + format) and mypy on /plugin, targeting the
# container's Python 3.12 environment with QGIS bindings available.
#
# Usage (from DevContainer):
#   docker exec oapif-qgis-test /plugin/scripts/check.sh
#   docker exec oapif-qgis-test /plugin/scripts/check.sh --fix
#   docker exec oapif-qgis-test /plugin/scripts/check.sh lint
#   docker exec oapif-qgis-test /plugin/scripts/check.sh types
#   docker exec oapif-qgis-test /plugin/scripts/check.sh --fix lint
#
# Or via the DevContainer wrapper:
#   ./scripts/check-plugin.sh [args...]

set -euo pipefail

PLUGIN_DIR="/plugin"

# ── Parse arguments ──────────────────────────────────────────────────

FIX=false
declare -A CHECKS=()

for arg in "$@"; do
    case "$arg" in
        --fix)        FIX=true ;;
        --help|-h)    head -16 "$0" | tail -14; exit 0 ;;
        lint|types)   CHECKS["$arg"]=1 ;;
        *)            echo "Unknown argument: $arg (try --help)"; exit 1 ;;
    esac
done

# No checks specified → run everything.
if [[ ${#CHECKS[@]} -eq 0 ]]; then
    for c in lint types; do
        CHECKS["$c"]=1
    done
fi

# ── Colours (disabled when stdout is not a terminal) ─────────────────

if [[ -t 1 ]]; then
    RED='\033[0;31m'  GREEN='\033[0;32m'
    BOLD='\033[1m'    RESET='\033[0m'
else
    RED=''  GREEN=''  BOLD=''  RESET=''
fi

# ── Helpers ──────────────────────────────────────────────────────────

passed=0
failed=0
start_time=$SECONDS

run_check() {
    local label="$1"; shift
    local t=$SECONDS
    printf "${BOLD}▶ %s${RESET}\n" "$label"
    if "$@"; then
        printf "${GREEN}  ✓ %s passed${RESET}  (%ds)\n\n" "$label" $(( SECONDS - t ))
        (( ++passed ))
    else
        printf "${RED}  ✗ %s failed${RESET}  (%ds)\n\n" "$label" $(( SECONDS - t ))
        (( ++failed ))
    fi
}

want() { [[ -v CHECKS["$1"] ]]; }

# ── Lint & format ────────────────────────────────────────────────────

if want lint; then
    if $FIX; then
        run_check "ruff fix (plugin)"    ruff check --fix "$PLUGIN_DIR"
        run_check "ruff format (plugin)" ruff format "$PLUGIN_DIR"
    else
        run_check "ruff lint (plugin)"   ruff check "$PLUGIN_DIR"
        run_check "ruff format (plugin)" ruff format --check "$PLUGIN_DIR"
    fi
fi

# ── Type checking ────────────────────────────────────────────────────

if want types; then
    run_check "mypy (plugin)" mypy --config-file "$PLUGIN_DIR/mypy.ini" "$PLUGIN_DIR"
fi

# ── Summary ──────────────────────────────────────────────────────────

elapsed=$(( SECONDS - start_time ))
echo "──────────────────────────────"
summary="${BOLD}Results:${RESET} "
parts=()
(( passed )) && parts+=("${GREEN}${passed} passed${RESET}")
(( failed )) && parts+=("${RED}${failed} failed${RESET}")
summary+="$(IFS=', '; echo "${parts[*]}")"
summary+="  (${elapsed}s)"
printf "%b\n" "$summary"

# ── Timestamp flag (full suite only) ─────────────────────────────────

ALL_REQUESTED=true
for c in lint types; do
    [[ -v CHECKS["$c"] ]] || { ALL_REQUESTED=false; break; }
done

if $ALL_REQUESTED && (( failed == 0 )); then
    date +%s > "$PLUGIN_DIR/.checks_passed_plugin"
fi

exit $failed
