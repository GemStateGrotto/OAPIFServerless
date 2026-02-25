#!/usr/bin/env bash
# Tear down acceptance test fixtures from a deployed AWS environment.
#
# Removes:
#   - Cognito users:  test-editor, test-admin, test-viewer, test-other-org
#   - Cognito groups: org:TestOrgB, TestOrgB:members, TestOrgB:restricted
#   - DynamoDB config: "acceptance-caves" collection config item
#   - DynamoDB features: all features in the "acceptance-caves" collection
#
# Groups created by the auth stack CDK (org:GemStateGrotto, admin, editor,
# viewer, etc.) are NOT removed — those are managed by the stack lifecycle.
#
# Usage:
#   ./scripts/acceptance-teardown.sh

set -euo pipefail

PREFIX="${OAPIF_STACK_PREFIX:-oapif}"
ENV="${OAPIF_ENVIRONMENT:-dev}"
STACK_AUTH="${PREFIX}-${ENV}-auth"
STACK_DATA="${PREFIX}-${ENV}-data"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo -e "\033[36m▶\033[0m $*"; }
ok()   { echo -e "\033[32m✓\033[0m $*"; }
skip() { echo -e "\033[33m⊘\033[0m $* (not found)"; }

# ── Resolve stack outputs ────────────────────────────────────────────

info "Reading stack outputs..."

USER_POOL_ID=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_AUTH" \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" \
    --output text) || die "Could not read auth stack outputs."

CONFIG_TABLE=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_DATA" \
    --query "Stacks[0].Outputs[?OutputKey=='ConfigTableName'].OutputValue" \
    --output text) || die "Could not read data stack outputs."

FEATURES_TABLE=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_DATA" \
    --query "Stacks[0].Outputs[?OutputKey=='FeaturesTableName'].OutputValue" \
    --output text) || die "Could not read features table name."

info "User Pool: $USER_POOL_ID"
info "Config Table: $CONFIG_TABLE"
info "Features Table: $FEATURES_TABLE"

# ── Delete test users ────────────────────────────────────────────────

echo ""
info "Deleting Cognito test users..."

for username in test-editor@oapif.test test-admin@oapif.test test-viewer@oapif.test test-other-org@oapif.test; do
    if aws cognito-idp admin-get-user --user-pool-id "$USER_POOL_ID" \
        --username "$username" &>/dev/null; then
        aws cognito-idp admin-delete-user --user-pool-id "$USER_POOL_ID" \
            --username "$username"
        ok "Deleted user $username"
    else
        skip "User $username"
    fi
done

# ── Delete test-only groups ──────────────────────────────────────────

echo ""
info "Deleting test-only Cognito groups..."

for group in "org:TestOrgB" "TestOrgB:members" "TestOrgB:restricted"; do
    if aws cognito-idp get-group --user-pool-id "$USER_POOL_ID" \
        --group-name "$group" &>/dev/null; then
        aws cognito-idp delete-group --user-pool-id "$USER_POOL_ID" \
            --group-name "$group"
        ok "Deleted group $group"
    else
        skip "Group $group"
    fi
done

# ── Delete acceptance-caves features ─────────────────────────────────

echo ""
info "Deleting acceptance-caves features..."

FEATURE_COUNT=0
while true; do
    ITEMS=$(aws dynamodb query --table-name "$FEATURES_TABLE" \
        --key-condition-expression "PK = :pk" \
        --expression-attribute-values '{":pk": {"S": "COLLECTION#acceptance-caves"}}' \
        --projection-expression "PK, SK" \
        --limit 25 \
        --output json 2>/dev/null)

    COUNT=$(echo "$ITEMS" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('Items', [])))")
    if [[ "$COUNT" == "0" ]]; then
        break
    fi

    # Build batch-write delete requests
    DELETE_REQUESTS=$(echo "$ITEMS" | python3 -c "
import sys, json
items = json.load(sys.stdin)['Items']
requests = [{'DeleteRequest': {'Key': {'PK': item['PK'], 'SK': item['SK']}}} for item in items]
print(json.dumps({'$FEATURES_TABLE': requests}))
")

    aws dynamodb batch-write-item --request-items "$DELETE_REQUESTS" >/dev/null
    FEATURE_COUNT=$((FEATURE_COUNT + COUNT))
done

if [[ "$FEATURE_COUNT" -gt 0 ]]; then
    ok "Deleted $FEATURE_COUNT feature items"
else
    skip "No acceptance-caves features found"
fi

# ── Delete collection config ────────────────────────────────────────

echo ""
info "Deleting acceptance-caves collection config..."

EXISTING=$(aws dynamodb get-item --table-name "$CONFIG_TABLE" \
    --key '{"PK": {"S": "COLLECTION#acceptance-caves"}, "SK": {"S": "CONFIG"}}' \
    --query "Item.collection_id.S" --output text 2>/dev/null || echo "None")

if [[ "$EXISTING" == "acceptance-caves" ]]; then
    aws dynamodb delete-item --table-name "$CONFIG_TABLE" \
        --key '{"PK": {"S": "COLLECTION#acceptance-caves"}, "SK": {"S": "CONFIG"}}'
    ok "Deleted collection config acceptance-caves"
else
    skip "Collection acceptance-caves config"
fi

# ── Summary ──────────────────────────────────────────────────────────

echo ""
info "Acceptance test fixtures removed."
