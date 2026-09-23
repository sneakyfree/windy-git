#!/usr/bin/env bash
# Cancel jobs no runner can ever take (see cancel_unrunnable.sql). Run on Veron as root.
set -euo pipefail
SPOOL="${JANITOR_SPOOL:-/var/lib/windy-git/janitor-cancelled.jsonl}"
mkdir -p "$(dirname "$SPOOL")"
out=$(docker exec -i windy-git-db-1 sh -c 'psql -U "$POSTGRES_USER" -d gitea -At -v ON_ERROR_STOP=1' \
        < "$(dirname "$0")/cancel_unrunnable.sql")
printf '%s\n' "$out" | grep '^{' >> "$SPOOL" || true
n=$(printf '%s\n' "$out" | grep -c '^{' || true)
echo "[janitor] cancelled ${n} unrunnable job(s)"
