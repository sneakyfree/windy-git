#!/usr/bin/env bash
# Sync token hygiene, by count (10-10, after #18). Run ON Veron as root; the nightly
# sweep on Windy 0 runs it over ssh. Prints counts only, never a value. Exit 1 if:
#   - any file under the sync work dir holds a sync token (raw or its Basic-auth base64),
#   - any bare repo's remote URL carries credentials,
#   - any process's argv holds one (a sync running right now would show here),
#   - the work dir is not root:root 0750, or any repo config is group/world readable.
set -uo pipefail
umask 077
WORK="${SYNC_WORK:-/srv/windygit/sync}"
ENV_FILE="${SYNC_ENV_FILE:-/etc/windygit/sync.env}"
EXPECT_OWNER="${EXPECT_OWNER:-root:root}"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
( set -a; . "$ENV_FILE"; set +a
  [[ -n "${GITHUB_TOKEN:-}" && -n "${GITEA_SYNC_TOKEN:-}" ]] || exit 3
  { printf '%s\n' "$GITHUB_TOKEN" "$GITEA_SYNC_TOKEN"
    printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 -w0; echo
    printf '%s:%s' "${WINDYGIT_OWNER:-windyadmin}" "$GITEA_SYNC_TOKEN" | base64 -w0; echo; } > "$T/pats"
) || { echo "sync token hygiene: ERROR (tokens not readable from $ENV_FILE)"; exit 1; }
files=$(grep -rlaf "$T/pats" "$WORK" 2>/dev/null | wc -l)
creds=0
for b in "$WORK"/*.git; do
  [[ -d $b ]] || continue
  [[ "$(git --git-dir="$b" remote get-url origin 2>/dev/null)" == *@* ]] && creds=$((creds+1))
done
argv=0
for f in /proc/[0-9]*/cmdline; do grep -qaf "$T/pats" "$f" 2>/dev/null && argv=$((argv+1)); done
owner=$(stat -c '%U:%G' "$WORK"); mode=$(stat -c '%a' "$WORK")
loose=$(find "$WORK" -maxdepth 2 -path '*.git/config' -perm /044 | wc -l)
echo "sync token hygiene: files=$files remote-creds=$creds argv=$argv dir=$owner/$mode loose-configs=$loose"
[[ $files == 0 && $creds == 0 && $argv == 0 && $owner == "$EXPECT_OWNER" && $mode == 750 && $loose == 0 ]]
