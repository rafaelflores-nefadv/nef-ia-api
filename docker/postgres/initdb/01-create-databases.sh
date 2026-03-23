#!/bin/sh
set -eu

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-postgres}"
DJANGO_DB_NAME="${DJANGO_DB_NAME:-nef_ia_django}"

if [ "${DJANGO_DB_NAME}" = "${POSTGRES_DB}" ]; then
  echo "Skipping Django database creation because it matches POSTGRES_DB (${POSTGRES_DB})."
  exit 0
fi

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "postgres" <<EOSQL
SELECT 'CREATE DATABASE "${DJANGO_DB_NAME}" OWNER "${POSTGRES_USER}"'
WHERE NOT EXISTS (
    SELECT 1
    FROM pg_database
    WHERE datname = '${DJANGO_DB_NAME}'
)\gexec
EOSQL
