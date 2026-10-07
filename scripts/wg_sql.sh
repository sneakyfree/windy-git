#!/usr/bin/env bash
# SQL on stdin -> the gitea database (what ~/bin/wg-q is for a human). Used by rerun_ci.sh when run as root.
exec docker exec -i windy-git-db-1 sh -c 'psql -U "$POSTGRES_USER" -d gitea -At -v ON_ERROR_STOP=1'
