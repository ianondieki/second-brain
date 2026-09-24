#!/usr/bin/env bash
# Write throwaway environment files for the CI compose stack (e2e job). Every value is random per run and dies
# with the runner; nothing here is a real secret. Local developers copy the .env.example files instead.
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
    backend/.env.example > backend/.env
echo "wrote infra/.env and backend/.env with random throwaway values"
