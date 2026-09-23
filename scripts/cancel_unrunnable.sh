#!/usr/bin/env bash
# Cancel jobs no runner can ever take (see cancel_unrunnable.sql). Run on Veron as root.
set -euo pipefail
n=$(docker exec -i windy-git-db-1 sh -c 'psql -U "$POSTGRES_USER" -d gitea -At -v ON_ERROR_STOP=1' \
      < "$(dirname "$0")/cancel_unrunnable.sql" | grep -cE '^[0-9]+$' || true)
echo "[janitor] cancelled unrunnable jobs in ${n} run(s)"
