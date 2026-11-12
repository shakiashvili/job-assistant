#!/usr/bin/env bash
set -euo pipefail

echo "Running Alembic database migrations..."
alembic upgrade head

echo "Starting Uvicorn server..."
exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
