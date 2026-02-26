#!/usr/bin/env bash
# --------------------------------------------------------------------------
# OGC CITE Conformance Test Runner
#
# Usage:
#   ./scripts/cite.sh                  # auto-detect API URL from CFN output
#   ./scripts/cite.sh <api-url>        # explicit API URL
#   ./scripts/cite.sh --cleanup        # remove container only
#
# Requires: docker, curl, xmllint, aws cli (for auto-detect)
# --------------------------------------------------------------------------
set -euo pipefail

CONTAINER_NAME="teamengine"
IMAGE="ogccite/ets-ogcapi-features10:latest"
HOST_PORT=8081
RESULTS_FILE="testng-results.xml"
TEAMENGINE_URL="http://localhost:${HOST_PORT}/teamengine"
MAX_WAIT=60   # seconds to wait for Tomcat startup

# ---- Colors (disabled if not a terminal) ---------------------------------
if [[ -t 1 ]]; then
  GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; NC=''
fi

info()  { echo -e "${GREEN}▶${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
fail()  { echo -e "${RED}✗${NC} $*" >&2; }

# ---- URL-encode helper (pure bash) --------------------------------------
urlencode() {
  local string="$1" char="" encoded=""
  for (( i=0; i<${#string}; i++ )); do
    char="${string:i:1}"
    case "$char" in
      [a-zA-Z0-9.~_-]) encoded+="$char" ;;
      *) encoded+=$(printf '%%%02X' "'$char") ;;
    esac
  done
  echo "$encoded"
}

# ---- XML attribute extractor (uses grep/sed) -----------------------------
# Usage: xml_attr <file> <attr>  — reads from the root <testng-results> tag
xml_attr() {
  grep -oP "${2}=\"[^\"]*\"" "$1" | head -1 | sed "s/${2}=\"//;s/\"//"
}

# ---- Cleanup helper ------------------------------------------------------
cleanup() {
  if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    info "Removing ${CONTAINER_NAME} container"
    docker rm -f "${CONTAINER_NAME}" >/dev/null
  fi
}

if [[ "${1:-}" == "--cleanup" ]]; then
  cleanup
  exit 0
fi

# ---- Resolve API URL -----------------------------------------------------
if [[ -n "${1:-}" ]]; then
  API_URL="${1%/}"  # strip trailing slash if present
else
  info "Auto-detecting API URL from CloudFormation outputs…"
  ENV="${OAPIF_ENVIRONMENT:-dev}"
  STACK="oapif-${ENV}-api"
  API_URL=$(aws cloudformation describe-stacks \
    --stack-name "${STACK}" \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
    --output text 2>/dev/null | sed 's:/$::')
  if [[ -z "${API_URL}" || "${API_URL}" == "None" ]]; then
    fail "Could not detect API URL from stack ${STACK}. Pass it explicitly:"
    echo "  ./scripts/cite.sh https://your-api-url" >&2
    exit 1
  fi
fi

info "Target API: ${API_URL}"

# ---- Quick smoke check on the API ---------------------------------------
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/conformance" 2>/dev/null || true)
if [[ "${HTTP_CODE}" != "200" ]]; then
  fail "API not reachable (GET /conformance → ${HTTP_CODE}). Deploy first?"
  exit 1
fi

# ---- Start TEAM Engine ---------------------------------------------------
cleanup 2>/dev/null || true

info "Starting TEAM Engine (${IMAGE})"
docker run -d --name "${CONTAINER_NAME}" -p "${HOST_PORT}:8080" "${IMAGE}" >/dev/null

info "Waiting for Tomcat to start (up to ${MAX_WAIT}s)…"
ELAPSED=0
while (( ELAPSED < MAX_WAIT )); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" -u ogctest:ogctest \
    "${TEAMENGINE_URL}/rest/suites" 2>/dev/null || true)
  if [[ "${CODE}" == "200" || "${CODE}" == "401" ]]; then
    break
  fi
  sleep 2
  ELAPSED=$(( ELAPSED + 2 ))
done

if (( ELAPSED >= MAX_WAIT )); then
  fail "TEAM Engine did not start within ${MAX_WAIT}s"
  docker logs "${CONTAINER_NAME}" | tail -20
  cleanup
  exit 1
fi
info "TEAM Engine ready (${ELAPSED}s)"

# ---- Run the test suite --------------------------------------------------
IUT=$(urlencode "${API_URL}/")

info "Running OGC API Features 1.0 conformance tests…"
info "  (this takes 1–3 minutes)"

HTTP_RESULT=$(curl -s -o "${RESULTS_FILE}" -w "%{http_code}" \
  -u ogctest:ogctest \
  -H "Accept: application/xml" \
  "${TEAMENGINE_URL}/rest/suites/ogcapi-features-1.0/run?iut=${IUT}&noofcollections=-1")

if [[ ! -s "${RESULTS_FILE}" ]]; then
  fail "No results file produced (HTTP ${HTTP_RESULT})"
  docker logs "${CONTAINER_NAME}" | tail -20
  cleanup
  exit 1
fi

# ---- Parse & display results (pure bash) ---------------------------------
PASSED=$(xml_attr "${RESULTS_FILE}" "passed")
FAILED=$(xml_attr "${RESULTS_FILE}" "failed")
SKIPPED=$(xml_attr "${RESULTS_FILE}" "skipped")
TOTAL=$(( PASSED + FAILED + SKIPPED ))

echo ""
echo "──────────────────────────────────────────────────"
echo "  Passed:  ${PASSED}"
echo "  Failed:  ${FAILED}"
echo "  Skipped: ${SKIPPED}  (CRS Part 2 — not claimed)"
echo "  Total:   ${TOTAL}"
echo "──────────────────────────────────────────────────"

RESULT=0
if (( FAILED > 0 )); then
  echo ""
  echo "  FAILURES:"
  # Extract failed test names from the XML
  grep -oP 'status="FAIL"[^>]*name="[^"]*"' "${RESULTS_FILE}" \
    | sed 's/.*name="//;s/"//' \
    | sort -u \
    | while read -r name; do
        echo "    ✗ ${name}"
      done
  RESULT=1
else
  echo ""
  echo "  ✓ All conformance tests passed"
fi

# ---- Cleanup -------------------------------------------------------------
echo ""
cleanup
rm -f "${RESULTS_FILE}"

if [[ ${RESULT} -ne 0 ]]; then
  fail "Conformance test failures detected — see above"
  exit 1
fi

info "Done"
