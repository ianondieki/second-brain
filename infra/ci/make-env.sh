#!/usr/bin/env bash
# Write throwaway environment files for the CI compose stack (e2e job). Every value is random per run and dies
# with the runner; nothing here is a real secret. Local developers copy the .env.example files instead. Both feature
# flags are on, so the Tier-2, inbox and tracker end-to-end specs run against the stack (make demo does the same).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

rand_hex() { openssl rand -hex "$1"; }

cat > infra/.env <<ENV
POSTGRES_SUPERUSER_PASSWORD=$(rand_hex 16)
BRIDGE_OWNER_PASSWORD=$(rand_hex 16)
BRIDGE_APP_PASSWORD=$(rand_hex 16)
ENV

secret_key="$(rand_hex 32)"
data_key="$(openssl rand -base64 32)"
sed -e "s|^APP_ENV=.*|APP_ENV=test|" \
    -e "s|^SECRET_KEY=.*|SECRET_KEY=${secret_key}|" \
    -e "s|^DATA_ENCRYPTION_KEY=.*|DATA_ENCRYPTION_KEY=${data_key}|" \
    -e "s|^RECOVERY_CODE_PEPPER=.*|RECOVERY_CODE_PEPPER=$(rand_hex 32)|" \
    -e "s|^TIER2_LOCAL_KEK=.*|TIER2_LOCAL_KEK=$(openssl rand -base64 32)|" \
    -e "s|^PROVENANCE_SIGNING_KEY=.*|PROVENANCE_SIGNING_KEY=$(openssl rand -base64 32)|" \
    -e "s|^FEATURE_TIER2_ENABLED=.*|FEATURE_TIER2_ENABLED=true|" \
    -e "s|^FEATURE_DEALS_ENABLED=.*|FEATURE_DEALS_ENABLED=true|" \
    backend/.env.example > backend/.env
echo "wrote infra/.env and backend/.env with random throwaway values"
