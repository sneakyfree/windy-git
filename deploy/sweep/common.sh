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

# board <line>: append one line to the BOARD.
board() {
  printf '%s\n' "$1" | "${SSH[@]}" 'cat >> ~/windy-orchestra/BOARD.md'
}
