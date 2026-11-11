# Shared helpers for the Windy Git nightly sweep on Veron (moved from Windy 0, 2026-10-21).
# The checks run here, next to /srv/windygit/src. The orchestra pages and the BOARD still
# live on Windy 0 (~/windy-orchestra), so pages and BOARD lines are written there over ssh.
# A failed write fails the step (never silent).
W0=eth-windy0
SSH=(timeout 90 ssh -o BatchMode=yes -o ConnectTimeout=15 "$W0")
STATE=~/.local/state/windygit-sweep
mkdir -p "$STATE"

# put_page <local file> <page name, e.g. RUNNER_GUARD.md>: atomic replace, keeps the old file mode.
put_page() {
  "${SSH[@]}" "f=~/windy-orchestra/$2; t=\$f.tmp.\$\$; cat > \"\$t\" && { [ -e \"\$f\" ] && chmod --reference=\"\$f\" \"\$t\"; mv \"\$t\" \"\$f\"; }" < "$1"
}

# get_page <page name> <local file>: copy a Windy 0 orchestra page here (read-only).
get_page() {
  "${SSH[@]}" "cat ~/windy-orchestra/$1" > "$2"
}

# board <line>: one BOARD line through board-say (BOARD STANDARD, Windy Boss 2026-11-10T18:29:46Z), which adds
# "- [time Windy Git]" with Windy 0's clock. The callers' leading "<time> Windy Git" / "Windy Git:" is dropped
# (board-say refuses a line that starts with a time), so "<time> Windy Git -> Boss: x" posts as "-> Boss: x".
# Fails (non-zero) unless board-say answers "OK ...".
board() {
  local t
  t=$(printf '%s' "$1" | sed -E '1s/^(- )?\[?20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:]{5,8}Z\]? *//; 1s/^Windy Git:? *//')
  printf '%s\n' "$t" | "${SSH[@]}" '~/windy-orchestra/bin/board-say "Windy Git"' | grep -q '^OK '
}
