#!/usr/bin/env bash
# Install the shared hash-only secret tools on THIS machine (Windy 0): secret-scan + env-names.
# Source of truth is this repo (scripts/); re-run after a pull to update.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
dest="$HOME/.local/share/secret-tools"
mkdir -p "$dest" "$HOME/.local/bin"
cp "$here/secret_shapes.py" "$here/secret_scan.py" "$here/env_names.py" "$here/lockbox_put.py" "$dest/"
for pair in "secret-scan:secret_scan.py" "env-names:env_names.py" "lockbox-put:lockbox_put.py"; do
  n=${pair%%:*}; f=${pair##*:}
  printf '#!/usr/bin/env bash\nexec python3 "%s/%s" "$@"\n' "$dest" "$f" > "$HOME/.local/bin/$n"
  chmod 755 "$HOME/.local/bin/$n"
done
echo "installed secret-scan, env-names and lockbox-put (shapes from secret_shapes.py, same as secret-guard)"
