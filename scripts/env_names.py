#!/usr/bin/env python3
"""env-names: list environment variable NAMES only (Boss ruling 10-01, house rule 10).

  env-names <docker container | systemd unit | env file> [--host H] [--sudo] [--hash]
  env-names A --compare B [--host H] [--host2 H2]

Prints NAME, set|empty, and value LENGTH. Never a value or fragment. --hash adds sha256[:8]
(compare two places for equality; a hash of a weak value can be guessed, so use it for
real secrets only). --compare prints SAME / DIFFERENT / only-in-A / only-in-B per name
(equality by full-value hash, nothing else shown). Values live in memory only.
Targets: an existing file (dotenv style) | a docker container name | a systemd unit
(Environment= + EnvironmentFile=; --sudo to read root-only files). --host runs the docker /
systemctl / file read over ssh (alias from ~/.ssh/config).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys

KV = ("=",)


def run(cmd: list[str], host: str | None, sudo: bool = False) -> tuple[int, str]:
    if sudo:
        cmd = ["sudo", "-n", *cmd]
    if host:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, shlex.join(cmd)]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="ignore", timeout=60)
    return r.returncode, r.stdout


def parse_dotenv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k.replace("_", "").isalnum() and not k[0].isdigit():
            out[k] = v
    return out


def from_file(path: str, host: str | None, sudo: bool) -> dict[str, str] | None:
    if host or sudo:
        rc, out = run(["cat", path], host, sudo)
        return parse_dotenv(out) if rc == 0 else None
    try:
        with open(path, errors="ignore") as fh:
            return parse_dotenv(fh.read())
    except OSError:
        return None


def from_docker(name: str, host: str | None, sudo: bool) -> dict[str, str] | None:
    rc, out = run(["docker", "inspect", "-f", "{{json .Config.Env}}", name], host, sudo)
    if rc != 0 or not out.strip():
        return None
    try:
        items = json.loads(out)
    except ValueError:
        return None
    return {k: v for k, _, v in (i.partition("=") for i in (items or []))}


def from_systemd(unit: str, host: str | None, sudo: bool) -> dict[str, str] | None:
    rc, out = run(["systemctl", "show", unit, "-p", "Environment", "-p", "EnvironmentFiles"], host)
    if rc != 0 or "LoadState=not-found" in out:
        return None
    env: dict[str, str] = {}
    files: list[str] = []
    for line in out.splitlines():
        if line.startswith("Environment="):
            for tok in shlex.split(line[len("Environment="):]):
                k, _, v = tok.partition("=")
                env[k] = v
        elif line.startswith("EnvironmentFiles="):
            f = line[len("EnvironmentFiles="):].split(" (")[0].strip().lstrip("-")
            if f:
                files.append(f)
    for f in files:  # later files override earlier, like systemd
        d = from_file(f, host, sudo)
        if d is None:
            print(f"# note: EnvironmentFile {f} unreadable (try --sudo)", file=sys.stderr)
        else:
            env.update(d)
    return env


def load(target: str, host: str | None, sudo: bool) -> dict[str, str] | None:
    if (not host and os.path.isfile(target)) or target.startswith(("/", "./", "~")):
        return from_file(os.path.expanduser(target), host, sudo)
    if target.endswith((".service", ".timer", ".socket")):
        return from_systemd(target, host, sudo)
    return from_docker(target, host, sudo) or from_systemd(target, host, sudo)


def sh(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="env-names", description="env var NAMES only")
    ap.add_argument("target")
    ap.add_argument("--host")
    ap.add_argument("--host2", help="ssh host for the --compare target")
    ap.add_argument("--sudo", action="store_true")
    ap.add_argument("--hash", action="store_true", help="add sha256[:8] per variable")
    ap.add_argument("--compare", metavar="TARGET2")
    a = ap.parse_args(argv)
    env = load(a.target, a.host, a.sudo)
    if env is None:
        print(f"error: could not read {a.target!r} (file, docker container or systemd unit)")
        return 2
    if a.compare:
        env2 = load(a.compare, a.host2 or a.host, a.sudo)
        if env2 is None:
            print(f"error: could not read {a.compare!r}")
            return 2
        for k in sorted(set(env) | set(env2)):
            if k not in env2:
                print(f"{k:<40} only-in-A")
            elif k not in env:
                print(f"{k:<40} only-in-B")
            else:
                print(f"{k:<40} {'SAME' if sh(env[k]) == sh(env2[k]) else 'DIFFERENT'}"
                      f"  (len {len(env[k])} vs {len(env2[k])})")
        return 0
    for k in sorted(env):
        v = env[k]
        extra = f"  sha256:{sh(v)[:8]}" if a.hash and v else ""
        print(f"{k:<40} {'set  ' if v else 'empty'}  len={len(v)}{extra}")
    print(f"# {len(env)} variable(s); values never printed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never a traceback
        print(f"error: {type(e).__name__}")
        sys.exit(2)
