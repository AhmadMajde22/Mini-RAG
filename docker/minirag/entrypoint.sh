#!/bin/bash
set -e

echo "Running database migration"
cd /app/models/db_schemas/minirag/
alembic upgrade head
cd /app

exec "$@"
