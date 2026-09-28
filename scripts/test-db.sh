#!/usr/bin/env bash
# Throwaway Postgres for the backend test suite.
#
# Separate from the compose stack on purpose: tests TRUNCATE between cases and run the
# migration from base on every session, and neither is something you want pointed at the
# database holding your demo data.
#
#   scripts/test-db.sh up      start it (idempotent)
#   scripts/test-db.sh down    stop and remove it, volume included
#   scripts/test-db.sh logs
set -euo pipefail

NAME=civicpulse-test-db
PORT="${TEST_POSTGRES_PORT:-55432}"
IMAGE=postgres:16.4-alpine   # pinned: an untagged image is an -8 deduction (§5.3)

case "${1:-up}" in
  up)
    if [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = "true" ]; then
      echo "$NAME already running on port $PORT"
      exit 0
    fi
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    # No volume: this data is disposable by design.
    docker run -d --name "$NAME" \
      -e POSTGRES_USER=civicpulse \
      -e POSTGRES_PASSWORD=civicpulse \
      -e POSTGRES_DB=civicpulse_test \
      -p "${PORT}:5432" \
      --health-cmd='pg_isready -U civicpulse -d civicpulse_test' \
      --health-interval=2s --health-timeout=3s --health-retries=15 \
      "$IMAGE" >/dev/null

    printf 'waiting for %s' "$NAME"
    for _ in $(seq 1 45); do
      if [ "$(docker inspect -f '{{.State.Health.Status}}' "$NAME" 2>/dev/null)" = "healthy" ]; then
        echo " ready on port $PORT"
        exit 0
      fi
      printf '.'
      sleep 1
    done
    echo " timed out" >&2
    docker logs --tail 30 "$NAME" >&2
    exit 1
    ;;
  down)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    echo "$NAME removed"
    ;;
  logs)
    docker logs --tail 50 -f "$NAME"
    ;;
  *)
    echo "usage: $0 {up|down|logs}" >&2
    exit 2
    ;;
esac
