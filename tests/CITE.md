# OGC CITE Conformance Testing

Run the [OGC CITE TEAM Engine](https://cite.opengeospatial.org/teamengine/) against
a deployed instance to verify OGC API – Features Part 1 conformance.

## Quick Start

```bash
./scripts/cite.sh                        # auto-detect API URL from CFN
./scripts/cite.sh https://your-api-url   # explicit URL
./scripts/cite.sh --cleanup              # remove container only
```

The script handles container lifecycle, waits for startup, runs the suite,
parses results, and cleans up. Exit code 0 = all tests passed.

## Prerequisites

- Docker available on `PATH`
- A deployed instance with at least one collection containing public features
  (the acceptance-setup script seeds the `acceptance-test` collection)
- The collection must be **single-org** so unauthenticated requests auto-default
  to that org (CITE doesn't know about the `organization` parameter)
- For auto-detect mode: AWS CLI configured with access to the deployment account

## What the Script Does

1. Resolves the API URL (from the arg or CloudFormation outputs)
2. Smoke-checks `GET /conformance` to ensure the API is reachable
3. Starts `ogccite/ets-ogcapi-features10:latest` on port 8081
4. Waits up to 60 s for Tomcat startup
5. Runs the `ogcapi-features-1.0` test suite (`noofcollections=-1`)
6. Parses `testng-results.xml` and prints a summary
7. Removes the container and results file

Total runtime: ~2–4 minutes (mostly network latency between TEAM Engine
and the API).

## Manual Steps (if needed)

<details>
<summary>Expand for step-by-step commands</summary>

### Start TEAM Engine

```bash
docker run -d --name teamengine -p 8081:8080 ogccite/ets-ogcapi-features10:latest
# Wait ~15 s, then verify:
curl -s -o /dev/null -w "%{http_code}" -u ogctest:ogctest \
  http://localhost:8081/teamengine/rest/suites
# Should return 200 or 401
```

### Run the Test Suite

```bash
API_URL="https://lp1v0amdsh.execute-api.us-west-2.amazonaws.com"

# URL-encode the IUT parameter (curl --data-urlencode doesn't work for query params in GET)
IUT=$(printf '%s' "${API_URL}/" | sed 's/:/%3A/g; s/\//%2F/g')

curl -s -u ogctest:ogctest \
  -H "Accept: application/xml" \
  "http://localhost:8081/teamengine/rest/suites/ogcapi-features-1.0/run?iut=${IUT}&noofcollections=-1" \
  -o testng-results.xml
```

### Parse Results

```bash
PASSED=$(grep -oP 'passed="[^"]*"' testng-results.xml | head -1 | sed 's/passed="//;s/"//')
FAILED=$(grep -oP 'failed="[^"]*"' testng-results.xml | head -1 | sed 's/failed="//;s/"//')
SKIPPED=$(grep -oP 'skipped="[^"]*"' testng-results.xml | head -1 | sed 's/skipped="//;s/"//')
echo "Passed: ${PASSED} | Failed: ${FAILED} | Skipped: ${SKIPPED}"

# Show any failures:
grep -oP 'status="FAIL"[^>]*name="[^"]*"' testng-results.xml \
  | sed 's/.*name="//;s/"//' | sort -u | while read -r n; do echo "  FAIL: $n"; done
```

### Cleanup

```bash
docker rm -f teamengine
```

</details>

## Expected Results

As of Feb 2026 the server passes all Part 1 Core tests:

| Status  | Count | Notes |
|---------|-------|-------|
| Passed  | 89    | Core + OAS30 + GeoJSON |
| Failed  | 0     | — |
| Skipped | 36    | CRS Part 2 (not claimed) |

## Conformance Classes Tested

CITE exercises the conformance classes declared in `/conformance`:

- `core` — landing page, collections, items, features, query params, error handling
- `oas30` — valid OpenAPI 3.0 definition at `/api`
- `geojson` — GeoJSON feature encoding

CRS Part 2 tests are automatically skipped because the server does not declare
that conformance class.

## Key Requirements Validated

| Requirement | What It Checks |
|-------------|---------------|
| `/req/core/query-param-unknown` | Unknown query parameters → 400 |
| `/req/core/query-param-invalid` | Invalid parameter values (bad `limit`, `bbox`) → 400 |
| `/req/core/f-op` | GET single feature by ID |
| `/req/core/fc-op` | GET feature collection |
| `/req/core/fc-links` | Self, next, collection links in responses |
| `/req/core/fc-timeStamp` | `timeStamp` present in feature collection |
| `/req/core/fc-numberReturned` | `numberReturned` present and correct |

## Troubleshooting

**"No feature Ids found"** — The collection is empty. Run `acceptance-setup.sh`
to seed public features, or POST features via the API.

**Unknown param returns 200 instead of 400** — The Lambda may be running stale
code. Redeploy with `./scripts/deploy.sh deploy api`.

**Connection refused on port 8081** — TEAM Engine container isn't running.
Check `docker ps` and restart if needed.

**DNS resolution fails for custom domain** — Use the direct API Gateway URL
from `./scripts/deploy.sh status` instead of the custom domain.
