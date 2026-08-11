#!/bin/bash
# Gitea gets its OWN role and database, not ours.
#
# I-1: Gitea is a component whose private state we never write to directly. That
# boundary is worth enforcing at the database, not just in prose — our plane
# holds schema `windgit` in `windygit`, and Gitea holds a database it alone can
# reach. A shared login would make "we never write Gitea's tables" a promise
# instead of a permission.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    CREATE ROLE gitea LOGIN PASSWORD '${GITEA_DB_PASSWORD:?GITEA_DB_PASSWORD must be set}';
    CREATE DATABASE gitea OWNER gitea;
    REVOKE ALL ON DATABASE gitea FROM PUBLIC;
SQL
