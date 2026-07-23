#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ALEMBIC_BIN="${BACKEND_DIR}/.venv/bin/alembic"

if [[ ! -x "${ALEMBIC_BIN}" ]]; then
  echo "error: alembic executable not found at ${ALEMBIC_BIN}" >&2
  echo "hint: create the virtualenv and install backend dependencies first" >&2
  exit 1
fi

cd "${BACKEND_DIR}"

echo "Applying database migrations with Alembic..."
"${ALEMBIC_BIN}" -c alembic.ini upgrade head
echo "Database tables are up to date."
