#!/usr/bin/env bash
# Quality gate — single source of truth for CI and local pre-commit.
#
# Usage:
#   ./scripts/check.sh                 # run ALL checks
#   ./scripts/check.sh lint            # ruff lint + format only
#   ./scripts/check.sh types           # mypy only
#   ./scripts/check.sh unit            # unit tests only
#   ./scripts/check.sh integration     # integration tests only
#   ./scripts/check.sh synth           # CDK synth only
#   ./scripts/check.sh lint types      # combine any checks
#   ./scripts/check.sh --fix           # auto-fix lint/format, then run selected checks
#   ./scripts/check.sh --fix lint      # auto-fix lint/format only
#
# Exit code 0 = all checks pass; non-zero = number of failed checks.

set -euo pipefail

# ── Parse arguments ──────────────────────────────────────────────────

FIX=false
declare -A CHECKS=()

for arg in "$@"; do
    case "$arg" in
        --fix)        FIX=true ;;
        --help|-h)    head -14 "$0" | tail -12; exit 0 ;;
        lint|types|unit|integration|synth)
                      CHECKS["$arg"]=1 ;;
        *)            echo "Unknown argument: $arg (try --help)"; exit 1 ;;
    esac
done

# No checks specified → run everything.
if [[ ${#CHECKS[@]} -eq 0 ]]; then
    for c in lint types unit integration synth; do
        CHECKS["$c"]=1
    done
fi

# ── Colours (disabled when stdout is not a terminal) ─────────────────

if [[ -t 1 ]]; then
    RED='\033[0;31m'  GREEN='\033[0;32m'  YELLOW='\033[0;33m'
    BOLD='\033[1m'    RESET='\033[0m'
else
    RED=''  GREEN=''  YELLOW=''  BOLD=''  RESET=''
fi

# ── Helpers ──────────────────────────────────────────────────────────

passed=0
failed=0
skipped=0
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

skip_check() {
    printf "${BOLD}▶ %s${RESET}\n" "$1"
    printf "${YELLOW}  ⏭ skipped (%s)${RESET}\n\n" "$2"
    (( ++skipped ))
}

want() { [[ -v CHECKS["$1"] ]]; }

# ── Lint & format ────────────────────────────────────────────────────

if want lint; then
    if $FIX; then
        run_check "ruff fix"    ruff check --fix .
        run_check "ruff format" ruff format .
    else
        run_check "ruff lint"   ruff check .
        run_check "ruff format" ruff format --check .
    fi
fi

# ── Type checking ────────────────────────────────────────────────────

if want types; then
    run_check "mypy" mypy src/ deploy/
fi

# ── Unit tests ───────────────────────────────────────────────────────

if want unit; then
    run_check "unit tests" \
        pytest tests/unit -m unit \
            --cov=src/oapif --cov-report=term-missing --cov-fail-under=80 -q
fi

# ── Integration tests ───────────────────────────────────────────────

if want integration; then
    endpoint="${DYNAMODB_LOCAL_ENDPOINT:-http://dynamodb-local:8000}"
    # DynamoDB Local returns HTTP 400 on bare GET (expects signed AWS requests),
    # so we just check that a TCP connection succeeds.
    if curl -s --connect-timeout 2 -o /dev/null "$endpoint" 2>/dev/null; then
        run_check "integration tests" \
            pytest tests/integration -m integration \
                --cov=src/oapif --cov-report=term-missing --cov-fail-under=80 -q
    else
        skip_check "integration tests" "DynamoDB Local not reachable at $endpoint"
    fi
fi

# ── CDK synth ────────────────────────────────────────────────────────

if want synth; then
    if command -v cdk &>/dev/null; then
        run_check "cdk synth" \
            cdk synth --app "python deploy/app.py" --no-staging -q
    else
        skip_check "cdk synth" "cdk CLI not found"
    fi
fi

# ── Summary ──────────────────────────────────────────────────────────

elapsed=$(( SECONDS - start_time ))
echo "──────────────────────────────"
summary="${BOLD}Results:${RESET} "
parts=()
(( passed  )) && parts+=("${GREEN}${passed} passed${RESET}")
(( failed  )) && parts+=("${RED}${failed} failed${RESET}")
(( skipped )) && parts+=("${YELLOW}${skipped} skipped${RESET}")
summary+="$(IFS=', '; echo "${parts[*]}")"
summary+="  (${elapsed}s)"
printf "%b\n" "$summary"

exit $failed
