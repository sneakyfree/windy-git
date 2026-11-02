#!/usr/bin/env bash
# ON NULL 0, as root (via sudo -n from register.sh): read ONE registration token from stdin and
# store it as RUNNER_<n>_TOKEN in this directory's .env (0600, owned by windygit-ci). Never prints
# it, never takes it in argv. Usage: printf %s TOKEN | sudo -n store-token.sh <1|2>
set -euo pipefail
n=${1:-}
[[ "$n" =~ ^[12]$ ]] || { echo "runner must be 1 or 2" >&2; exit 2; }
umask 077
t=$(head -c 4096)
t=${t%$'\n'}
[ "${#t}" -ge 20 ] && [[ "$t" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "refused: no plausible token on stdin" >&2; exit 3; }
cd "$(dirname "$0")"
OWNER="${OFFSITE_OWNER:-windygit-ci}"
touch .env
chmod 600 .env
chown "$OWNER:$OWNER" .env
tmp=$(mktemp .env.XXXXXX)
grep -v "^RUNNER_${n}_TOKEN=" .env > "$tmp" || true
printf 'RUNNER_%s_TOKEN=%s\n' "$n" "$t" >> "$tmp"
chmod 600 "$tmp"; chown "$OWNER:$OWNER" "$tmp"
mv "$tmp" .env
echo "token stored for runner-$n (.env 0600 $OWNER)"
