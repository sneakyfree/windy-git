#!/usr/bin/env bash
# Refresh the READ-ONLY CI input cache for windy-pro desktop jobs from the FROZEN
# release clone on Veron. Reads ~/windy-pro-release only; never writes to it.
# Run when the release lane says engines / wheels / the portable bundle changed.
# Linux inputs only: 3 models + requirements-bundle.txt, bundled-portable/linux-x64,
# native/enter-monitor/build. Result is chmod a-w and mounted :ro into dind.
set -euo pipefail
SRC=/home/user1-gpu/windy-pro-release
DST=/home/user1-gpu/ci-inputs/windy-pro
models=$(ls "$SRC/extraResources/model" | grep -E '^windy-(nano|lite|core)-ct2$')
[ "$(wc -w <<<"$models")" = 3 ] || { echo "expected 3 models, got: $models"; exit 1; }
mkdir -p "$DST/extraResources/model" "$DST/bundled-portable" "$DST/native-enter-monitor-build"
chmod -R u+w "$DST"
R="ionice -c3 nice -n 19 rsync -a --delete"
for m in $models; do $R "$SRC/extraResources/model/$m/" "$DST/extraResources/model/$m/"; done
$R "$SRC/extraResources/requirements-bundle.txt" "$DST/extraResources/requirements-bundle.txt"
$R "$SRC/bundled-portable/linux-x64/" "$DST/bundled-portable/linux-x64/"
$R "$SRC/native/enter-monitor/build/" "$DST/native-enter-monitor-build/"
date -u +%FT%TZ > "$DST/.refreshed-from-windy-pro-release"
chmod -R a-w "$DST"
du -sh --apparent-size "$DST"
