#!/usr/bin/env bash
# Set up acceptance test fixtures on a deployed AWS environment.
#
# Creates:
#   - Cognito groups:  org:TestOrgB, TestOrgB:members, TestOrgB:restricted
#   - Cognito users:   test-editor@oapif.test  (org:TestOrgA + editor + TestOrgA:members)
#                       test-admin@oapif.test   (org:TestOrgA + admin  + TestOrgA:members + TestOrgA:restricted)
#                       test-viewer@oapif.test  (org:TestOrgA + viewer)
#                       test-other-org@oapif.test (org:TestOrgB + editor + TestOrgB:members)
#   - DynamoDB config: "acceptance-test" test collection in the config table
#
# All values are derived from CloudFormation stack outputs — no manual env
# var configuration beyond OAPIF_ENVIRONMENT (default: dev) and standard
# AWS credentials.
#
# Usage:
#   ./scripts/acceptance-setup.sh          # set up test fixtures
#   ./scripts/acceptance-setup.sh --status # show current state
#
# The counterpart teardown script is ./scripts/acceptance-teardown.sh.

set -euo pipefail

PREFIX="${OAPIF_STACK_PREFIX:-oapif}"
ENV="${OAPIF_ENVIRONMENT:-dev}"
STACK_AUTH="${PREFIX}-${ENV}-auth"
STACK_DATA="${PREFIX}-${ENV}-data"

# Temporary password for user creation (immediately set to permanent)
TEMP_PASSWORD='T3mp!Pass_Initial99'
TEST_PASSWORD='Accept@nceTest2026!'

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo -e "\033[36m▶\033[0m $*"; }
ok()   { echo -e "\033[32m✓\033[0m $*"; }
skip() { echo -e "\033[33m⊘\033[0m $* (already exists)"; }

# ── Resolve stack outputs ────────────────────────────────────────────

info "Reading stack outputs..."

USER_POOL_ID=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_AUTH" \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" \
    --output text) || die "Could not read auth stack outputs. Is $STACK_AUTH deployed?"

CONFIG_TABLE=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_DATA" \
    --query "Stacks[0].Outputs[?OutputKey=='ConfigTableName'].OutputValue" \
    --output text) || die "Could not read data stack outputs. Is $STACK_DATA deployed?"

info "User Pool: $USER_POOL_ID"
info "Config Table: $CONFIG_TABLE"

# ── Status mode ──────────────────────────────────────────────────────

if [[ "${1:-}" == "--status" ]]; then
    echo ""
    info "Groups:"
    aws cognito-idp list-groups --user-pool-id "$USER_POOL_ID" \
        --query "Groups[].GroupName" --output table

    echo ""
    info "Users:"
    aws cognito-idp list-users --user-pool-id "$USER_POOL_ID" \
        --query "Users[].{Username: Username, Status: UserStatus, Email: Attributes[?Name=='email'].Value | [0]}" \
        --output table

    echo ""
    info "Test collection in config table:"
    aws dynamodb get-item --table-name "$CONFIG_TABLE" \
        --key '{"PK": {"S": "COLLECTION#acceptance-test"}, "SK": {"S": "CONFIG"}}' \
        --query "Item.collection_id.S" --output text 2>/dev/null || echo "(not found)"

    exit 0
fi

# ── Helper: create group if not exists ───────────────────────────────

create_group() {
    local group_name="$1"
    local description="$2"

    if aws cognito-idp get-group --user-pool-id "$USER_POOL_ID" \
        --group-name "$group_name" &>/dev/null; then
        skip "Group $group_name"
    else
        aws cognito-idp create-group --user-pool-id "$USER_POOL_ID" \
            --group-name "$group_name" --description "$description" >/dev/null
        ok "Created group $group_name"
    fi
}

# ── Helper: create user and assign to groups ─────────────────────────

create_user() {
    local username="$1"
    local email="$2"
    shift 2
    local groups=("$@")

    if aws cognito-idp admin-get-user --user-pool-id "$USER_POOL_ID" \
        --username "$username" &>/dev/null; then
        skip "User $username"
    else
        aws cognito-idp admin-create-user --user-pool-id "$USER_POOL_ID" \
            --username "$username" \
            --user-attributes Name=email,Value="$email" Name=email_verified,Value=true \
            --temporary-password "$TEMP_PASSWORD" \
            --message-action SUPPRESS >/dev/null

        # Set permanent password
        aws cognito-idp admin-set-user-password --user-pool-id "$USER_POOL_ID" \
            --username "$username" \
            --password "$TEST_PASSWORD" \
            --permanent >/dev/null

        ok "Created user $username ($email)"
    fi

    # Ensure group memberships (idempotent)
    for group in "${groups[@]}"; do
        aws cognito-idp admin-add-user-to-group --user-pool-id "$USER_POOL_ID" \
            --username "$username" --group-name "$group" 2>/dev/null || true
    done
    ok "  → groups: ${groups[*]}"
}

# ── Create groups ────────────────────────────────────────────────────

echo ""
info "Creating Cognito groups..."

# Second org for cross-org isolation testing
create_group "org:TestOrgB"          "Test organization B (acceptance tests)"
create_group "TestOrgB:members"      "TestOrgB members visibility (acceptance tests)"
create_group "TestOrgB:restricted"   "TestOrgB restricted visibility (acceptance tests)"

# Existing groups (org:TestOrgA, TestOrgA:members,
# TestOrgA:restricted, admin, editor, viewer) are created by the
# auth stack CDK deploy — we don't recreate them here.

# ── Create users ─────────────────────────────────────────────────────

echo ""
info "Creating Cognito test users..."

create_user "test-editor@oapif.test" "test-editor@oapif.test" \
    "org:TestOrgA" "editor" "TestOrgA:members"

create_user "test-admin@oapif.test" "test-admin@oapif.test" \
    "org:TestOrgA" "admin" "TestOrgA:members" "TestOrgA:restricted"

create_user "test-viewer@oapif.test" "test-viewer@oapif.test" \
    "org:TestOrgA" "viewer"

create_user "test-other-org@oapif.test" "test-other-org@oapif.test" \
    "org:TestOrgB" "editor" "TestOrgB:members"

# ── Seed test collection ─────────────────────────────────────────────

echo ""
info "Seeding acceptance test collection..."

EXISTING=$(aws dynamodb get-item --table-name "$CONFIG_TABLE" \
    --key '{"PK": {"S": "COLLECTION#acceptance-test"}, "SK": {"S": "CONFIG"}}' \
    --query "Item.collection_id.S" --output text 2>/dev/null || echo "None")

if [[ "$EXISTING" == "acceptance-test" ]]; then
    skip "Collection acceptance-test"
else
    aws dynamodb put-item --table-name "$CONFIG_TABLE" --item '{
        "PK":                   {"S": "COLLECTION#acceptance-test"},
        "SK":                   {"S": "CONFIG"},
        "collection_id":        {"S": "acceptance-test"},
        "title":                {"S": "Acceptance Test Collection"},
        "description":          {"S": "Collection used by the acceptance test suite"},
        "item_type":            {"S": "feature"},
        "geometry_type":        {"S": "Point"},
        "crs":                  {"L": [{"S": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}]},
        "storage_crs":          {"S": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
        "visibility_values":    {"L": [{"S": "public"}, {"S": "members"}, {"S": "restricted"}]},
        "required_properties":  {"L": [{"S": "name"}]},
        "properties_schema": {"M": {
            "name":        {"M": {"type": {"S": "string"}, "description": {"S": "Feature name"}}},
            "depth_m":     {"M": {"type": {"S": "number"}, "description": {"S": "Depth in meters"}, "minimum": {"N": "0"}}},
            "survey_date": {"M": {"type": {"S": "string"}, "description": {"S": "Date of survey"}, "format": {"S": "date"}}},
            "status":      {"M": {"type": {"S": "string"}, "description": {"S": "Feature status"}, "enum": {"L": [{"S": "active"}, {"S": "closed"}, {"S": "unknown"}]}}}
        }},
        "organizations": {"M": {
            "TestOrgA": {"M": {
                "cognito_group": {"S": "org:TestOrgA"},
                "access_groups": {"M": {
                    "members":    {"S": "TestOrgA:members"},
                    "restricted": {"S": "TestOrgA:restricted"}
                }}
            }},
            "TestOrgB": {"M": {
                "cognito_group": {"S": "org:TestOrgB"},
                "access_groups": {"M": {
                    "members":    {"S": "TestOrgB:members"},
                    "restricted": {"S": "TestOrgB:restricted"}
                }}
            }}
        }},
        "extent": {"M": {
            "spatial": {"M": {
                "bbox": {"L": [{"L": [{"N": "-117"}, {"N": "42"}, {"N": "-111"}, {"N": "49"}]}]},
                "crs":  {"S": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}
            }},
            "temporal": {"M": {
                "interval": {"L": [{"L": [{"S": "2020-01-01T00:00:00Z"}, {"NULL": true}]}]}
            }}
        }},
        "links": {"L": []}
    }'
    ok "Created collection acceptance-test"
fi

# ── Summary ──────────────────────────────────────────────────────────

echo ""
info "Acceptance test fixtures ready."
info "Run tests with:  pytest -m acceptance"
info "Tear down with:  ./scripts/acceptance-teardown.sh"
