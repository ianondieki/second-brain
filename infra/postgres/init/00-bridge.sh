#!/usr/bin/env bash
# First-start init for the dev Postgres container (docker-entrypoint-initdb.d). Creates the roles, gives the
# owner and app roles a login with the passwords from infra/.env, and prepares the `bridge` database.
set -euo pipefail
: "${BRIDGE_OWNER_PASSWORD:?set in infra/.env}" "${BRIDGE_APP_PASSWORD:?set in infra/.env}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -f /bridge-sql/roles.sql
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$BRIDGE_OWNER_PASSWORD" -v app_pw="$BRIDGE_APP_PASSWORD" <<'SQL'
ALTER ROLE bridge_owner LOGIN PASSWORD :'owner_pw';
ALTER ROLE bridge_app LOGIN PASSWORD :'app_pw';
CREATE DATABASE bridge OWNER bridge_owner;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname bridge -f /bridge-sql/prepare_db.sql
