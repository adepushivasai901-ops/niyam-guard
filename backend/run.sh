#!/bin/bash
# Convenience script: seed the database (if needed) and start the API server.
set -e
cd "$(dirname "$0")"

if [ ! -f "niyamguard.db" ]; then
  echo "No database found - seeding sample data..."
  python -m app.seed_data
fi

echo "Starting NiyamGuard AI backend on http://localhost:8000  (docs at /docs)"
uvicorn app.main:app --reload --port 8000
