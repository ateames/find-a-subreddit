# ai_reddit_prototype/scripts/entrypoint-ingest.sh
#!/usr/bin/env bash
set -euo pipefail

echo "[ingest] Waiting for Postgres to be ready at db:5432..."
for i in {1..60}; do
  if pg_isready -h db -p 5432 -U postgres -d reddit_vibes > /dev/null 2>&1; then
    echo "[ingest] Postgres is ready."
    break
  fi
  sleep 1
done

# Show the effective DATABASE_URL for clarity
echo "[ingest] DATABASE_URL = ${DATABASE_URL:-<unset>}"
echo "[ingest] TOP_N = ${TOP_N:-default}"

# Run the Python script
exec python3 scripts/ingest_reddit_to_postgres.py
