#!/usr/bin/env bash
# Post-create setup for the DevContainer.
# Called by devcontainer.json postCreateCommand.
set -euo pipefail

# Install Python project (editable) and CDK CLI
pip install -e '.[cdk,dev]'
npm install -g aws-cdk

# Install git pre-commit hook
cp scripts/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

# Ensure mounted secrets are exported in every new terminal.
# Uses tr -d '\r' to handle Windows-style line endings in the secrets file.
SECRETS="$HOME/.secrets/oapifserverless"
if ! grep -q "$SECRETS" ~/.bashrc 2>/dev/null; then
    cat >> ~/.bashrc <<BASHRC

# Export secrets from mounted file (if present)
if [ -f "$SECRETS" ]; then
    set -a
    source <(tr -d '\\r' < "$SECRETS" | grep -v '^\\s*#' | grep -v '^\\s*$')
    set +a
fi
BASHRC
fi
