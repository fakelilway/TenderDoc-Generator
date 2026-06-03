#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Starting Docker services"
docker compose -f "$REPO_ROOT/docker-compose.yml" up -d

echo "Waiting for PostgreSQL"
until docker exec tender-postgres pg_isready -U tenderuser -d tenderdb >/dev/null 2>&1; do
  sleep 1
done

echo "Applying database schema"
docker exec -i tender-postgres psql -U tenderuser -d tenderdb < "$REPO_ROOT/backend/init_db.sql"

echo "Checking Redis"
until docker exec tender-redis redis-cli ping >/dev/null 2>&1; do
  sleep 1
done

echo "Checking MinIO"
until curl -fsS http://localhost:9000/minio/health/live >/dev/null 2>&1; do
  sleep 1
done

echo "Local infrastructure is ready"
