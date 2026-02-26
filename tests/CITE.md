# OGC CITE Conformance Testing

Run the [OGC CITE TEAM Engine](https://cite.opengeospatial.org/teamengine/) against
a deployed instance to verify OGC API – Features Part 1 conformance.

## Prerequisites

- Docker available on `PATH`
- A deployed instance with at least one collection containing public features
  (the acceptance-setup script seeds three: `seed-cave-alpha`, `seed-cave-beta`,
  `seed-cave-gamma`)
- The collection must be **single-org** so unauthenticated requests auto-default
  to that org (CITE doesn't know about the `organization` parameter)

## 1. Start TEAM Engine

```bash
docker run -d --name teamengine -p 8081:8080 ogccite/ets-ogcapi-features10:latest
```

Wait ~15 seconds for Tomcat to start. Verify with:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/teamengine/rest/suites
# Should return 200
```

## 2. Run the Test Suite

Replace `$API_URL` with the API Gateway URL (no trailing slash):

```bash
API_URL="https://lp1v0amdsh.execute-api.us-west-2.amazonaws.com"

curl -s -u ogctest:ogctest \
  -H "Accept: application/xml" \
  "http://localhost:8081/teamengine/rest/suites/ogcapi-features-1.0/run?iut=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${API_URL}/', safe=''))")&noofcollections=-1" \
  -o testng-results.xml
```

Parameters:
- `iut` — URL-encoded root URL of the API (include trailing `/`)
- `noofcollections=-1` — test all collections (use `1` for faster runs)
- Credentials: `ogctest:ogctest` (built into the Docker image)

The test run takes 1–3 minutes depending on the number of features and network latency.

## 3. Parse Results

```bash
python3 -c "
import xml.etree.ElementTree as ET
from collections import Counter

tree = ET.parse('testng-results.xml')
root = tree.getroot()
attrs = root.attrib
print(f'Passed: {attrs[\"passed\"]} | Failed: {attrs[\"failed\"]} | Skipped: {attrs[\"skipped\"]}')

for test in root.iter('test-method'):
    if test.attrib.get('status') == 'FAIL':
        name = test.attrib.get('name', '?')
        desc = test.attrib.get('description', '')[:120]
        exc = test.find('.//exception/message')
        msg = exc.text.strip()[:200] if exc is not None and exc.text else ''
        print(f'  FAIL: {name}')
        print(f'    {desc}')
        if msg:
            print(f'    {msg}')
"
```

## 4. Cleanup

```bash
docker rm -f teamengine
```

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
