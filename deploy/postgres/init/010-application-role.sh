#!/bin/sh
set -eu

: "${POSTGRES_MIGRATOR_PASSWORD:?POSTGRES_MIGRATOR_PASSWORD is required}"
: "${POSTGRES_RUNTIME_PASSWORD:?POSTGRES_RUNTIME_PASSWORD is required}"

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=migrator_password="$POSTGRES_MIGRATOR_PASSWORD" \
  --set=runtime_password="$POSTGRES_RUNTIME_PASSWORD" \
  --set=database_name="$POSTGRES_DB" <<-'EOSQL'
CREATE ROLE ctrl_v2_owner
  NOLOGIN
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  NOINHERIT
  NOBYPASSRLS;

CREATE ROLE ctrl_v2_migrator
  LOGIN
  PASSWORD :'migrator_password'
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  NOINHERIT
  NOBYPASSRLS;

CREATE ROLE ctrl_v2_runtime
  LOGIN
  PASSWORD :'runtime_password'
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  NOINHERIT
  NOBYPASSRLS;

GRANT ctrl_v2_owner TO ctrl_v2_migrator;

ALTER DATABASE :"database_name" OWNER TO ctrl_v2_owner;
REVOKE ALL PRIVILEGES ON DATABASE :"database_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database_name" TO ctrl_v2_migrator, ctrl_v2_runtime;

ALTER SCHEMA public OWNER TO ctrl_v2_owner;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM ctrl_v2_migrator, ctrl_v2_runtime;
GRANT USAGE ON SCHEMA public TO ctrl_v2_runtime;

ALTER ROLE ctrl_v2_owner IN DATABASE :"database_name"
  SET search_path TO pg_catalog, public;
ALTER ROLE ctrl_v2_migrator IN DATABASE :"database_name"
  SET search_path TO pg_catalog, public;
ALTER ROLE ctrl_v2_runtime IN DATABASE :"database_name"
  SET search_path TO pg_catalog, public;
EOSQL
