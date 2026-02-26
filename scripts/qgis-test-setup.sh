#!/usr/bin/env bash
# Set up a QGIS Docker container for plugin testing via Docker-in-Docker.
#
# This script runs inside the DevContainer and uses the DinD Docker daemon to:
#   1. Pull the QGIS LTR image
#   2. Resolve CFN stack outputs (base URL, token endpoint, client ID)
#   3. Authenticate test users and obtain refresh tokens
#   4. Start a persistent container with Xvfb, volume mounts, and env vars
#   5. Install test dependencies inside the container
#
# The container has NO AWS credentials — all AWS interaction happens here,
# in the DevContainer. Refresh tokens (valid 365 days) are passed as env vars.
# The plugin conftest exchanges them for fresh ID tokens via a public HTTPS
# POST to the Cognito /oauth2/token endpoint.
#
# Usage:
#   ./scripts/qgis-test-setup.sh            # set up container
#   ./scripts/qgis-test-setup.sh --status   # show container status
#
# Counterparts:
#   ./scripts/qgis-test.sh                  # run tests
#   ./scripts/qgis-test-teardown.sh         # stop and remove container

set -euo pipefail

CONTAINER_NAME="oapif-qgis-test"
QGIS_IMAGE="qgis/qgis:ltr"

PREFIX="${OAPIF_STACK_PREFIX:-oapif}"
ENV="${OAPIF_ENVIRONMENT:-dev}"
STACK_API="${PREFIX}-${ENV}-api"
STACK_AUTH="${PREFIX}-${ENV}-auth"

TEST_PASSWORD='Accept@nceTest2026!'

WORKSPACE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo -e "\033[36m▶\033[0m $*"; }
ok()   { echo -e "\033[32m✓\033[0m $*"; }
skip() { echo -e "\033[33m⊘\033[0m $* (already exists)"; }

# ── Status mode ──────────────────────────────────────────────────────

if [[ "${1:-}" == "--status" ]]; then
    if docker inspect "$CONTAINER_NAME" &>/dev/null; then
        STATE=$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME")
        echo "Container: $CONTAINER_NAME"
        echo "Status:    $STATE"
        if [[ "$STATE" == "running" ]]; then
            echo ""
            info "Environment variables:"
            docker exec "$CONTAINER_NAME" env | grep -E '^OAPIF_|^DISPLAY|^QT_QPA' | sort
            echo ""
            info "Xvfb process:"
            docker exec "$CONTAINER_NAME" pgrep -a Xvfb || echo "(not running)"
            echo ""
            info "pytest available:"
            docker exec "$CONTAINER_NAME" python3 -m pytest --version 2>/dev/null || echo "(not installed)"
        fi
    else
        echo "Container $CONTAINER_NAME does not exist."
        echo "Run: ./scripts/qgis-test-setup.sh"
    fi
    exit 0
fi

# ── Idempotency check ───────────────────────────────────────────────

if docker inspect "$CONTAINER_NAME" &>/dev/null; then
    STATE=$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME")
    if [[ "$STATE" == "running" ]]; then
        skip "Container $CONTAINER_NAME is already running"
        echo "Use --status to inspect, or ./scripts/qgis-test-teardown.sh to rebuild."
        exit 0
    else
        info "Container $CONTAINER_NAME exists but is $STATE — removing and recreating."
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1
    fi
fi

# ── Pull QGIS image ─────────────────────────────────────────────────

info "Pulling $QGIS_IMAGE..."
docker pull "$QGIS_IMAGE"
ok "Image ready"

# ── Resolve CFN stack outputs ───────────────────────────────────────

info "Reading CloudFormation stack outputs..."

OAPIF_BASE_URL=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_API" \
    --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" \
    --output text) || die "Could not read API stack outputs. Is $STACK_API deployed?"

USER_POOL_DOMAIN_URL=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_AUTH" \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolDomainUrl'].OutputValue" \
    --output text) || die "Could not read auth stack outputs. Is $STACK_AUTH deployed?"

OAPIF_CLIENT_ID=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_AUTH" \
    --query "Stacks[0].Outputs[?OutputKey=='AppClientId'].OutputValue" \
    --output text) || die "Could not read AppClientId."

USER_POOL_ID=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_AUTH" \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" \
    --output text) || die "Could not read UserPoolId."

OAPIF_TOKEN_ENDPOINT="${USER_POOL_DOMAIN_URL}/oauth2/token"

# Remove trailing slash from base URL
OAPIF_BASE_URL="${OAPIF_BASE_URL%/}"

info "Base URL:        $OAPIF_BASE_URL"
info "Token endpoint:  $OAPIF_TOKEN_ENDPOINT"
info "Client ID:       $OAPIF_CLIENT_ID"
info "User Pool:       $USER_POOL_ID"

# ── Authenticate test users → refresh tokens ────────────────────────

info "Authenticating test users..."

get_refresh_token() {
    local username="$1"
    local result
    result=$(aws cognito-idp admin-initiate-auth \
        --user-pool-id "$USER_POOL_ID" \
        --client-id "$OAPIF_CLIENT_ID" \
        --auth-flow ADMIN_USER_PASSWORD_AUTH \
        --auth-parameters "USERNAME=$username,PASSWORD=$TEST_PASSWORD" \
        --query "AuthenticationResult.RefreshToken" \
        --output text) || die "Failed to authenticate $username"
    echo "$result"
}

OAPIF_EDITOR_REFRESH_TOKEN=$(get_refresh_token "test-editor@oapif.test")
ok "Got refresh token for test-editor"

OAPIF_ADMIN_REFRESH_TOKEN=$(get_refresh_token "test-admin@oapif.test")
ok "Got refresh token for test-admin"

OAPIF_VIEWER_REFRESH_TOKEN=$(get_refresh_token "test-viewer@oapif.test")
ok "Got refresh token for test-viewer"

# ── Start container ──────────────────────────────────────────────────

info "Starting container $CONTAINER_NAME..."

# Build the docker run command with env vars and volume mounts.
# Xvfb is started via the entrypoint wrapper to provide a virtual display
# for GUI widget tests (Tier 3). Headless tests use QT_QPA_PLATFORM=offscreen.
docker run -d \
    --name "$CONTAINER_NAME" \
    -e "QT_QPA_PLATFORM=offscreen" \
    -e "DISPLAY=:99" \
    -e "OAPIF_BASE_URL=$OAPIF_BASE_URL" \
    -e "OAPIF_TOKEN_ENDPOINT=$OAPIF_TOKEN_ENDPOINT" \
    -e "OAPIF_CLIENT_ID=$OAPIF_CLIENT_ID" \
    -e "OAPIF_EDITOR_REFRESH_TOKEN=$OAPIF_EDITOR_REFRESH_TOKEN" \
    -e "OAPIF_ADMIN_REFRESH_TOKEN=$OAPIF_ADMIN_REFRESH_TOKEN" \
    -e "OAPIF_VIEWER_REFRESH_TOKEN=$OAPIF_VIEWER_REFRESH_TOKEN" \
    -v "${WORKSPACE_DIR}/plugin:/plugin:rw" \
    -v "/tmp/.X11-unix:/tmp/.X11-unix:rw" \
    "$QGIS_IMAGE" \
    bash -c "Xvfb :99 -screen 0 1024x768x24 &>/dev/null & sleep infinity"

ok "Container started"

# ── Install test dependencies ────────────────────────────────────────

info "Installing test dependencies in container..."
docker exec "$CONTAINER_NAME" pip3 install --break-system-packages \
    pytest pytest-cov ruff mypy 2>&1 | tail -1
ok "Test dependencies installed"

# ── Verify container health ──────────────────────────────────────────

info "Verifying container..."

# Check Xvfb is running
sleep 1
if docker exec "$CONTAINER_NAME" pgrep Xvfb >/dev/null 2>&1; then
    ok "Xvfb is running on :99"
else
    echo "  WARNING: Xvfb may not have started. Widget tests (Tier 3) may fail."
fi

# Check pytest is available
if docker exec "$CONTAINER_NAME" python3 -m pytest --version >/dev/null 2>&1; then
    ok "pytest is available"
else
    die "pytest installation failed"
fi

# Check QGIS Python bindings are available
if docker exec "$CONTAINER_NAME" python3 -c "from qgis.core import Qgis; print('QGIS', Qgis.QGIS_VERSION)" 2>/dev/null; then
    ok "QGIS Python bindings are available"
else
    die "QGIS Python bindings not found in container"
fi

# ── Summary ──────────────────────────────────────────────────────────

echo ""
ok "QGIS test container is ready."
info "Run tests with:     ./scripts/qgis-test.sh"
info "Check status:       ./scripts/qgis-test-setup.sh --status"
info "Tear down:          ./scripts/qgis-test-teardown.sh"
