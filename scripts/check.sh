#!/usr/bin/env bash
# Pre-commit quality gate — run before every commit.
#
# Usage:
#   ./scripts/check.sh        # lint, format, type-check
#   ./scripts/check.sh --fix  # auto-fix what ruff can, then verify
#
# Exit code 0 = all checks pass; non-zero = issues remain.

set -euo pipefail

FIX=false
if [[ "${1:-}" == "--fix" ]]; then
    FIX=true
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
BOLD='\033[1m'
RESET='\033[0m'

passed=0
failed=0

run_check() {
    local label="$1"
    shift
    printf "${BOLD}▶ %s${RESET}\n" "$label"
    if "$@"; then
        printf "${GREEN}  ✓ %s passed${RESET}\n\n" "$label"
        passed=$((passed + 1))
    else
        printf "${RED}  ✗ %s failed${RESET}\n\n" "$label"
        failed=$((failed + 1))
    fi
}

# --- Ruff lint ---
if $FIX; then
    run_check "ruff fix"    ruff check --fix .
    run_check "ruff format" ruff format .
else
    run_check "ruff lint"   ruff check .
    run_check "ruff format" ruff format --check .
fi

# --- mypy ---
run_check "mypy" mypy src/ deploy/

# --- Tests with coverage ---
run_check "unit tests"        pytest tests/unit -m unit --cov=src/oapif --cov-report=term-missing --cov-fail-under=80 -q
run_check "integration tests"  pytest tests/integration -m integration --cov=src/oapif --cov-report=term-missing --cov-fail-under=80 -q

# --- Summary ---
echo "──────────────────────────────"
printf "${BOLD}Results: ${GREEN}%d passed${RESET}" "$passed"
if [[ $failed -gt 0 ]]; then
    printf ", ${RED}%d failed${RESET}" "$failed"
fi
echo ""

exit $failed
