# OAPIFServerless

An AWS Serverless implementation of [OGC API - Features](https://ogcapi.ogc.org/features/) backed by DynamoDB and Lambda, with Cognito-based authentication, a QGIS plugin for desktop integration, and a complete IaC deployment system.

## Overview

OAPIFServerless provides a low-cost, usage-based geospatial feature server that implements the OGC API - Features standard (Parts 1 and 4) on AWS serverless infrastructure. It is designed for organizations that need a standards-compliant spatial data API without the overhead of running dedicated servers.

### Key Capabilities

- **OGC API - Features Part 1 (Core):** Read-access to geospatial feature collections via REST, with GeoJSON encoding, `bbox`/`datetime`/property filtering, and cursor-based paging
- **OGC API - Features Part 4 (CRUD):** Create, Replace, Update, and Delete operations for authorized users, with JSON Merge Patch support
- **Optimistic Concurrency:** ETag-based optimistic locking on writes to prevent lost updates in multi-user environments
- **Change Tracking:** An append-only change log table in DynamoDB records all mutations for auditability (no automated rollback; admins can manually restore features via direct DynamoDB access)
- **Organization Tenancy:** Each feature belongs to an `organization` (e.g., `TestOrgA`), auto-populated on creation from the caller's Cognito group. Organization acts as a hard tenant boundary — no query ever returns features from multiple organizations
- **Row-Level Access Control:** Within an organization, features can be further restricted by `visibility` (`public`, `members`, `restricted`) mapped to Cognito groups, allowing sensitive locations to be hidden from unauthorized users
- **Field-Level Authorization:** Server-enforced controls that allow some groups to edit feature geometry/attributes while others can only manage group membership metadata
- **Dynamic Schema Publishing:** Each configured collection publishes its schema at `/collections/{collectionId}/schema`, enabling clients to discover field names, types, and constraints at runtime
- **QGIS Plugin:** A companion QGIS plugin that authenticates via OIDC/Cognito, supports downloading and uploading QGIS project files to S3, and connects to OAPIFServerless feature layers
- **Complete Deployment System:** Infrastructure-as-Code (AWS CDK, Python) that anyone can deploy to their own AWS account

### Version Roadmap

| Version | Spatial Query Strategy |
|---------|----------------------|
| **v1**  | Return all rows with server-side cursor paging (no spatial index) |
| **v2**  | GeoHash or Z-order curve index on DynamoDB for efficient bounding-box retrieval |

## Architecture

```
┌─────────────┐       ┌──────────────────┐       ┌───────────────┐
│   QGIS      │──────▶│  API Gateway    │──────▶│  Lambda       │
│   Plugin    │  OIDC │  + Cognito Auth  │       │  (Python)     │
└─────────────┘       └──────────────────┘       └───────┬───────┘
                                                         │
                      ┌──────────────────┐               │
                      │  S3              │◀──────────────┤
                      │  (QGIS Projects) │               │
                      └──────────────────┘       ┌───────▼───────┐
                                                 │  DynamoDB     │
                      ┌──────────────────┐       │  ┌───────────┐│
                      │  Cognito         │       │  │ Features  ││
                      │  User Pool       │       │  │ Changes   ││
                      │  ┌────────────┐  │       │  │ Config    ││
                      │  │ Groups     │  │       │  └───────────┘│
                      │  │ (org,      │  │       └───────────────┘
                      │  │ visibility)│  │
                      │  └────────────┘  │
                      └──────────────────┘
```

### AWS Services Used

| Service | Purpose |
|---------|---------|
| **API Gateway** (HTTP API) | REST endpoint with JWT authorizer |
| **Lambda** (Python) | Request handling, OAPIF logic, authorization enforcement |
| **DynamoDB** | Feature storage, change tracking, collection configuration |
| **Cognito** | User pool, OIDC provider, group-based access control |
| **S3** | QGIS project file storage |
| **CloudFormation / CDK** | Infrastructure-as-Code deployment (CDK Python) |

## OGC API - Features Compliance

### Part 1: Core (Read)

The API implements the following OAPIF Part 1 conformance classes:

| Conformance Class | URI |
|---|---|
| Core | `http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core` |
| GeoJSON | `http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson` |
| OpenAPI 3.0 | `http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30` |

**Endpoints:**

| Resource | Path | Method |
|----------|------|--------|
| Landing Page | `/` | GET |
| Conformance | `/conformance` | GET |
| Collections | `/collections` | GET |
| Collection | `/collections/{collectionId}` | GET |
| Features | `/collections/{collectionId}/items` | GET |
| Feature | `/collections/{collectionId}/items/{featureId}` | GET |
| Schema | `/collections/{collectionId}/schema` | GET |

**Query Parameters:** `limit`, `offset` (cursor), `bbox`, `datetime`, `organization`, plus per-collection property filters.

Read operations support both authenticated and unauthenticated access:

| Mode | `organization` param | Visibility | Notes |
|------|---------------------|------------|-------|
| **Authenticated** | Optional (validated against JWT if provided) | Based on caller's Cognito group memberships | Org derived from JWT |
| **Unauthenticated** | **Required** | `public` only | Must specify a valid org |

In both modes, the organization is a hard tenant boundary — a single request never returns features from multiple organizations. Authenticated users who omit the `organization` parameter have it inferred from their JWT. Features outside a caller's visibility are silently excluded from collection queries as if they do not exist. A `GET` by `{featureId}` for a feature the caller is not entitled to returns `404 Not Found` (never `403`), preventing information leakage about the existence of restricted features.

### Part 4: Create, Replace, Update, Delete

| Operation | Method | Path | Notes |
|-----------|--------|------|-------|
| Create | POST | `/collections/{collectionId}/items` | Server-assigned ID |
| Replace | PUT | `/collections/{collectionId}/items/{featureId}` | Full replacement |
| Update | PATCH | `/collections/{collectionId}/items/{featureId}` | JSON Merge Patch (`application/merge-patch+json`) |
| Delete | DELETE | `/collections/{collectionId}/items/{featureId}` | Soft-delete recorded in change log |

All write operations require a valid Cognito JWT and appropriate group membership. Optimistic concurrency is enforced via `ETag` / `If-Match` headers.

## DynamoDB Data Model

### Feature Table

Each configured collection maps to a DynamoDB table (or a shared table with collection-prefixed keys):

| Attribute | Type | Role |
|-----------|------|------|
| `PK` | String | `{collectionId}#{featureId}` |
| `SK` | String | `FEATURE` (or sort key for future use) |
| `geometry` | String (GeoJSON) | Feature geometry |
| `properties` | Map | Feature properties |
| `etag` | String | Version hash for optimistic concurrency |
| `organization` | String | Hard tenant boundary, auto-populated on creation from caller's Cognito org group (e.g., `TestOrgA`). Immutable after creation. |
| `visibility` | String (enum) | Row-level access within org: `public`, `members`, `restricted` |
| `updated_at` | String (ISO 8601) | Last modification timestamp |
| `updated_by` | String | Cognito `sub` of last editor |

### Change Tracking Table

| Attribute | Type | Role |
|-----------|------|------|
| `PK` | String | `{collectionId}#{featureId}` |
| `SK` | String | `CHANGE#{timestamp}#{uuid}` |
| `operation` | String | `CREATE`, `REPLACE`, `UPDATE`, `DELETE` |
| `before` | Map | Snapshot of feature before mutation (null for CREATE) |
| `after` | Map | Snapshot of feature after mutation (null for DELETE) |
| `changed_by` | String | Cognito `sub` |
| `etag_before` | String | ETag before this change |
| `etag_after` | String | ETag after this change |

> **Note:** There is no automated rollback. Admins can manually restore corrupted features by inspecting the change log and writing directly to DynamoDB.

### V2: Spatial Indexing

Version 2 will add a GeoHash (or Z-order/Hilbert curve) attribute to each feature, stored as a GSI sort key, enabling efficient bounding-box queries without scanning the entire table. The approach will be chosen to balance precision, query fan-out, and DynamoDB GSI constraints.

## Access Control

### Authentication

The API supports both authenticated and unauthenticated access on read (GET) endpoints:

- **Authenticated:** A valid JWT from the Cognito User Pool, obtained via OIDC authorization code flow (used by the QGIS plugin) or client credentials flow (for machine-to-machine access). The caller's organization and visibility level are derived from their Cognito group memberships.
- **Unauthenticated:** Public access is allowed on all GET endpoints. The caller must provide an `organization` query parameter and will only see features with `visibility = public`.

All write endpoints (POST, PUT, PATCH, DELETE) always require authentication.

### Organization Tenancy

Every feature belongs to exactly one `organization`. This value is **auto-populated on creation** from the caller's Cognito organization group (each user belongs to exactly one org group). Organization is a **hard tenant boundary**: all queries are scoped to the caller's organization, and no API response ever mixes features from different organizations. The `organization` field is immutable after creation and cannot be changed via PUT or PATCH.

**Example:** A user in the `TestOrgA` org group creates a feature → the feature's `organization` is set to `TestOrgA`. Users in other org groups will never see this feature.

### Row-Level Feature Visibility

Within an organization, features carry a `visibility` metadata field that provides finer-grained access control. The Lambda authorizer constructs a filter predicate from the caller's Cognito group memberships before querying DynamoDB.

**Visibility enum values:**

| Value | Who can see |
|-------|------------|
| `public` | Anyone (including unauthenticated users who specify the organization) |
| `members` | Authenticated users in a group with `members`-level access or higher |
| `restricted` | Only authenticated users in a group with explicit `restricted`-level access |

Visibility is hierarchical: a user with `restricted` access sees all three levels; a user with `members` access sees `public` and `members`; a user with only base org membership sees `public` only. The exact group-to-visibility mapping is documented in the deployment configuration schema.

### Field-Level Authorization

Write operations enforce server-side field-level permissions:

| Capability | Required Group Role |
|------------|-------------------|
| Edit geometry and feature attributes | `editor` (or collection-specific editor group) |
| Edit `visibility` and group membership metadata | `admin` (or collection-specific admin group) |

The server rejects PATCH/PUT requests that attempt to modify fields outside the caller's allowed set, returning `403 Forbidden` with a description of the violation.

## QGIS Plugin

The companion QGIS plugin (`oapif-qgis-plugin/`) provides:

1. **OIDC Authentication** — Launches browser-based Cognito login; stores and refreshes tokens
2. **Feature Layer Access** — Connects to OAPIFServerless collections as native QGIS vector layers via the OGC API - Features interface
3. **Project File Sync** — Download a shared QGIS project (`.qgz`) from S3; upload changes back (with appropriate permissions)

## Deployment

The project uses AWS CDK (Python) with a two-stack architecture that separates stateful data resources from stateless compute resources:

| Stack | Resources | Destroy-safe? |
|-------|-----------|---------------|
| `oapif-{env}-data` | DynamoDB tables, S3 bucket | **Dev:** yes. **Staging/Prod:** no — `RETAIN` policy + termination protection |
| `oapif-{env}-api` | Lambda, API Gateway | Always safe to destroy and redeploy |

This separation means you can iterate on Lambda code and API routes without risking your data. In production, DynamoDB tables and the S3 bucket are protected by `RemovalPolicy.RETAIN` and stack termination protection.

### Prerequisites

- AWS CLI configured with appropriate credentials
- Node.js 22+ (for CDK CLI)
- Python 3.14+ (provided by the DevContainer)

### Quick Start

A deployment helper script wraps all CDK commands:

```bash
# First-time setup (once per AWS account/region)
./scripts/deploy.sh bootstrap

# Deploy all stacks
./scripts/deploy.sh deploy

# Deploy only the API stack (fast iteration on Lambda code, ~15-30s)
./scripts/deploy.sh deploy api

# Preview changes before deploying
./scripts/deploy.sh diff

# Show stack outputs (API URL, table names, etc.)
./scripts/deploy.sh outputs

# Show deployment status
./scripts/deploy.sh status
```

See `./scripts/deploy.sh help` for all commands.

### Configuration

Deployment parameters are configured via environment variables (`OAPIF_*` prefix) or CDK context (`--context key=value`). Defaults are defined in `deploy/config.py`. See `.env.example` for the full list.

AWS account and region are read from the standard `AWS_ACCOUNT_ID` and `AWS_REGION` environment variables.

### Custom Domain

To serve the API from a custom domain (e.g., `api.example.com`), set two additional environment variables:

```bash
OAPIF_CUSTOM_DOMAIN_NAME=api.example.com
OAPIF_CUSTOM_DOMAIN_CERTIFICATE_ARN=arn:aws:acm:us-west-2:123456789012:certificate/abc-123
```

The ACM certificate must be provisioned in the same region as the API Gateway. After deployment, create a CNAME or ALIAS DNS record pointing your domain to the `CustomDomainTarget` output. When these variables are unset, the default API Gateway URL is used.

### Production Deploys

CDK deploys are incremental — only changed resources are updated. A typical Lambda code fix deploys in ~15-30 seconds. DynamoDB tables and S3 buckets are never modified or deleted during API stack updates.

```bash
# Deploy a fix to production (only touches Lambda + API Gateway)
OAPIF_ENVIRONMENT=prod ./scripts/deploy.sh deploy api
```

### What Gets Created

- DynamoDB tables: features, change tracking, collection configuration
- S3 bucket for QGIS project files
- Lambda function for OAPIF endpoints
- API Gateway HTTP API
- Cognito User Pool with OIDC configuration (Phase 4)
- IAM roles with least-privilege policies

## Prior Art and Inspiration

- **[pygeoapi](https://github.com/geopython/pygeoapi)** — Python OGC API implementation with a pluggable provider architecture (PostgreSQL, Elasticsearch, MongoDB, etc.). OAPIFServerless draws inspiration from pygeoapi's provider pattern but targets DynamoDB specifically. No existing OAPIF implementation uses DynamoDB as a backend.
- **[OGC API - Features Part 1: Core](https://docs.ogc.org/is/17-069r4/17-069r4.html)** (OGC 17-069r4) — The authoritative spec for read-only feature access.
- **[OGC API - Features Part 4: CRUD](https://docs.ogc.org/DRAFTS/20-002r1.html)** (OGC 20-002r1, draft) — Spec for transactional operations with optimistic locking.
- **[OGC API - Features Part 5: Schemas](https://docs.ogc.org/DRAFTS/23-058.html)** (OGC 23-058, draft) — Spec for returnables/receivables schema publishing.

## License

See [LICENSE](LICENSE) for details.
