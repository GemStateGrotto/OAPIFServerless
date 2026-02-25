#!/usr/bin/env bash
# Deployment helper — bootstrap, deploy, destroy, and inspect CDK stacks.
#
# Usage:
#   ./scripts/deploy.sh bootstrap      — Bootstrap CDK in the target account/region
#   ./scripts/deploy.sh synth          — Synthesize CloudFormation templates
#   ./scripts/deploy.sh diff           — Preview changes before deploying
#   ./scripts/deploy.sh deploy         — Deploy all stacks (data → auth → api)
#   ./scripts/deploy.sh deploy api     — Deploy only the API stack (fast)
#   ./scripts/deploy.sh deploy data    — Deploy only the data stack
#   ./scripts/deploy.sh deploy auth    — Deploy only the auth stack
#   ./scripts/deploy.sh destroy        — Destroy all dev stacks (refuses non-dev)
#   ./scripts/deploy.sh destroy api    — Destroy only the API stack
#   ./scripts/deploy.sh outputs        — Show stack outputs
#   ./scripts/deploy.sh status         — Show deployment status of all stacks
#
# Environment variables are read from deploy/config.py defaults and
# OAPIF_* env vars. See .env.example for the full list.

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────

CDK_APP="python deploy/app.py"
PREFIX="${OAPIF_STACK_PREFIX:-oapif}"
ENV="${OAPIF_ENVIRONMENT:-dev}"
STACK_DATA="${PREFIX}-${ENV}-data"
STACK_AUTH="${PREFIX}-${ENV}-auth"
STACK_API="${PREFIX}-${ENV}-api"

# ── Helpers ──────────────────────────────────────────────────────────

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo -e "\033[36m▶\033[0m $*"; }

resolve_stacks() {
    # Given a layer name (data|auth|api), return the stack id.
    # With no argument, returns nothing (meaning "all").
    case "${1:-}" in
        "")    echo "" ;;   # all
        data)  echo "$STACK_DATA" ;;
        auth)  echo "$STACK_AUTH" ;;
        api)   echo "$STACK_API" ;;
        *)     die "Unknown stack layer: $1 (expected: data, auth, api)" ;;
    esac
}

show_stack_outputs() {
    local stack_name="$1"
    echo "=== $stack_name ==="
    aws cloudformation describe-stacks \
        --stack-name "$stack_name" \
        --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
        --output table 2>/dev/null || echo "  (not deployed)"
    echo ""
}

show_stack_status() {
    local stack_name="$1"
    local status
    status=$(aws cloudformation describe-stacks \
        --stack-name "$stack_name" \
        --query 'Stacks[0].StackStatus' \
        --output text 2>/dev/null) || status="NOT_DEPLOYED"
    printf "  %-30s %s\n" "$stack_name" "$status"
}

# ── Commands ─────────────────────────────────────────────────────────

cmd_bootstrap() {
    info "Bootstrapping CDK in account $(aws sts get-caller-identity --query Account --output text) / ${AWS_REGION:-us-west-2}"
    npx cdk bootstrap --app "$CDK_APP"
}

cmd_synth() {
    info "Synthesizing CloudFormation templates"
    npx cdk synth --app "$CDK_APP" --quiet
}

cmd_diff() {
    local stack
    stack=$(resolve_stacks "${1:-}")
    if [[ -z "$stack" ]]; then
        info "Showing diff for all stacks"
        npx cdk diff --app "$CDK_APP"
    else
        info "Showing diff for $stack"
        npx cdk diff --app "$CDK_APP" "$stack"
    fi
}

cmd_deploy() {
    local stack
    stack=$(resolve_stacks "${1:-}")
    if [[ -z "$stack" ]]; then
        info "Deploying all stacks (${ENV} environment)"
        npx cdk deploy --app "$CDK_APP" --all --require-approval broadening
    else
        info "Deploying $stack"
        npx cdk deploy --app "$CDK_APP" "$stack" --require-approval broadening
    fi
}

cmd_destroy() {
    local stack
    stack=$(resolve_stacks "${1:-}")
    if [[ -z "$stack" ]]; then
        # Destroying all stacks — only allowed in dev
        if [[ "$ENV" != "dev" ]]; then
            die "'destroy' without a target is only allowed in dev (current: $ENV)"
        fi
        info "Destroying all stacks (${ENV} environment)"
        npx cdk destroy --app "$CDK_APP" --all --force
    else
        info "Destroying $stack"
        npx cdk destroy --app "$CDK_APP" "$stack" --force
    fi
}

cmd_outputs() {
    show_stack_outputs "$STACK_DATA"
    show_stack_outputs "$STACK_AUTH"
    show_stack_outputs "$STACK_API"
}

cmd_status() {
    info "Stack status (${ENV} environment)"
    show_stack_status "$STACK_DATA"
    show_stack_status "$STACK_AUTH"
    show_stack_status "$STACK_API"
}

cmd_help() {
    head -18 "$0" | tail -16
}

# ── Entrypoint ───────────────────────────────────────────────────────

cd "$(dirname "$0")/.."

case "${1:-}" in
    bootstrap)  cmd_bootstrap ;;
    synth)      cmd_synth ;;
    diff)       cmd_diff "${2:-}" ;;
    deploy)     cmd_deploy "${2:-}" ;;
    destroy)    cmd_destroy "${2:-}" ;;
    outputs)    cmd_outputs ;;
    status)     cmd_status ;;
    help|--help|-h) cmd_help ;;
    "")         cmd_help ;;
    *)          die "Unknown command: $1 (try --help)" ;;
esac
