"""scripts/backup.sh uploads only age-encrypted files (Boss's backup-encryption sweep, 10-10).

Runs the real script with a throwaway keypair, a throwaway bare repo, and stub `docker`
(the pg_dump) and `aws` (R2 upload -> a local dir). Skips where `age` is not installed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (shutil.which("age") and shutil.which("sha256sum")),
    reason="age / sha256sum not installed",
)

_B32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32(hrp: str, data: bytes) -> str:
    """BIP-173 bech32 (what age uses for its keys), so the test needs no age-keygen."""
    acc = bits = 0
    five = []
    for b in data:
        acc, bits = (acc << 8) | b, bits + 8
        while bits >= 5:
            bits -= 5
            five.append((acc >> bits) & 31)
    if bits:
        five.append((acc << (5 - bits)) & 31)

    def polymod(values):
        gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
        chk = 1
        for v in values:
            top = chk >> 25
            chk = (chk & 0x1FFFFFF) << 5 ^ v
            for i in range(5):
                chk ^= gen[i] if (top >> i) & 1 else 0
        return chk

    hrp_x = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    pm = polymod(hrp_x + five + [0] * 6) ^ 1
    check = [(pm >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_B32[d] for d in five + check)


def _keypair(key: Path) -> str:
    """A throwaway age X25519 identity in `key`; returns its recipient."""
    if shutil.which("age-keygen"):
        subprocess.run(["age-keygen", "-o", str(key)], check=True, capture_output=True)
        return next(line.split(": ")[1] for line in key.read_text().splitlines()
                    if line.startswith("# public key"))
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    sk = X25519PrivateKey.generate()
    raw = sk.private_bytes(ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption())
    pub = sk.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
    key.write_text(_bech32("age-secret-key-", raw).upper() + "\n")
    return _bech32("age", pub)


def _exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def world(tmp_path):
    # one real repo with one commit, where backup.sh looks for repositories
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "f").write_text("x")
    subprocess.run(["git", "-C", str(seed), "add", "f"], check=True)
    subprocess.run(["git", "-C", str(seed), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "c"], check=True)
    repos = tmp_path / "data/git/repositories/windyadmin"
    repos.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(repos / "demo.git")], check=True)

    key = tmp_path / "id.txt"
    recipient = _keypair(key)
    (tmp_path / "recipient.txt").write_text(recipient + "\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _exe(bin_dir / "docker", "#!/bin/sh\necho 'CREATE TABLE windgit.tokens (id int);'\n")
    up = tmp_path / "uploaded"
    # `aws s3 --endpoint-url X cp SRC s3://bucket/STAMP/ --recursive ...` -> copy SRC into $UP; `ls` -> nothing
    _exe(bin_dir / "aws", f"""#!/bin/bash
args=("$@")
for ((i=0;i<${{#args[@]}};i++)); do
  if [[ ${{args[$i]}} == cp ]]; then mkdir -p {up}; cp -r "${{args[$((i+1))]}}"/. {up}/; exit 0; fi
done
exit 0
""")
    env = {**os.environ,
           "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "GIT_DATA_ROOT": str(tmp_path / "data"),
           "R2_ACCESS_KEY_ID": "fake", "R2_SECRET_ACCESS_KEY": "fake", "R2_ACCOUNT_ID": "fake",
           "BACKUP_AGE_RECIPIENT_FILE": str(tmp_path / "recipient.txt"),
           "GIT_CONFIG_GLOBAL": "/dev/null"}
    return tmp_path, env, key, up


def _run(env):
    return subprocess.run(["bash", str(ROOT / "scripts/backup.sh")], env=env,
                          capture_output=True, text=True, timeout=120)


def test_only_encrypted_files_leave_and_they_decrypt_to_the_logged_sums(world):
    tmp, env, key, up = world
    r = _run(env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok — 1 repos + database" in r.stdout
    names = sorted(p.name for p in up.iterdir())
    assert names == ["SHA256SUMS", "windgit.sql.age", "windyadmin__demo.bundle.age"]
    sums = dict(reversed(line.split("  ", 1)) for line in (up / "SHA256SUMS").read_text().splitlines())
    for enc in up.glob("*.age"):
        plain = subprocess.run(["age", "-d", "-i", str(key), str(enc)], capture_output=True, check=True).stdout
        assert hashlib.sha256(plain).hexdigest() == sums[enc.name.removesuffix(".age")]
        assert b"CREATE TABLE" not in enc.read_bytes()  # the dump is not readable in the upload


def test_missing_recipient_refuses_and_uploads_nothing(world):
    tmp, env, key, up = world
    (tmp / "recipient.txt").write_text("")
    r = _run(env)
    assert r.returncode == 1
    assert "refusing to upload anything plain" in r.stdout
    assert not up.exists()


def test_missing_age_refuses_and_uploads_nothing(world):
    tmp, env, key, up = world
    no_age = tmp / "noage"
    no_age.mkdir()
    for tool in ("bash", "git", "sha256sum", "mktemp", "date", "dirname", "basename", "grep", "rm", "cat"):
        if shutil.which(tool):
            (no_age / tool).symlink_to(shutil.which(tool))
    env = {**env, "PATH": f"{tmp / 'bin'}:{no_age}"}
    r = _run(env)
    assert r.returncode == 1
    assert "refusing to upload anything plain" in r.stdout
    assert not up.exists()
