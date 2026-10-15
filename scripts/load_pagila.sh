#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

# Load the Pagila sample database into the source Postgres service.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pagila_ref="ce6e114236bb828e5ec0dc835f65f1bf1b9179f5"
cache="${root}/cache/pagila/${pagila_ref}"
schema_url="https://raw.githubusercontent.com/devrimgunduz/pagila/${pagila_ref}/pagila-schema.sql"
data_url="https://raw.githubusercontent.com/devrimgunduz/pagila/${pagila_ref}/pagila-data.sql"

mkdir -p "${cache}"
if [[ ! -s "${cache}/pagila-schema.sql" ]]; then
  curl --fail --silent --show-error --location --output "${cache}/pagila-schema.sql" "${schema_url}"
fi
if [[ ! -s "${cache}/pagila-data.sql" ]]; then
  curl --fail --silent --show-error --location --output "${cache}/pagila-data.sql" "${data_url}"
fi

docker compose --project-directory "${root}" up --detach --wait source-postgres

loaded="$(
  docker compose --project-directory "${root}" exec --no-TTY source-postgres \
    psql --username postgres --dbname pagila --tuples-only --no-align \
    --command "SELECT to_regclass('public.film')"
)"
if [[ "${loaded}" == "film" ]]; then
  echo "Pagila is already loaded."
  exit 0
fi

docker compose --project-directory "${root}" exec --no-TTY source-postgres \
  psql --username postgres --dbname pagila --set ON_ERROR_STOP=1 \
  < "${cache}/pagila-schema.sql"
docker compose --project-directory "${root}" exec --no-TTY source-postgres \
  psql --username postgres --dbname pagila --set ON_ERROR_STOP=1 \
  < "${cache}/pagila-data.sql"

echo "Pagila loaded."
