#!/usr/bin/env python3
"""Add a "prod vs lock" column to GUARDS_STATUS.md from PROD_LOCK_DRIFT.md.

PROD_LOCK_DRIFT.md (Windy Search lane, daily 11:30 UTC) checks what RUNS
against the deployed lockfile, one row per service. This maps services to
repos and shows each repo's WORST verdict, so the CI guards (what the code
says) and prod (what actually runs) sit side by side. Unmapped services are
listed, never guessed.  Usage: merge-prod-lock-drift.py GUARDS_STATUS.md PROD_LOCK_DRIFT.md
"""
import re
import sys
from pathlib import Path

# service-name pattern -> bridged repo (first match wins)
SERVICE_REPO = [
    (r"^windy-(push-gateway|backup|onboarding|directory|media|agent-roster|call-history|hub|social|translation)\b", "windy-chat"),
    (r"^windy-cloud-", "WindyCloud"), (r"^windysites-", "windy-cloud-sites"),
    (r"^windydomains-", "windy-cloud-domains"), (r"^windy-cloud-vps|^windyvps-", "windy-cloud-vps"),
    (r"^windymind-", "windy-mind"), (r"^windycodeweb-", "windy-code-web"),
    (r"^account-server-", "windy-pro"), (r"^eternitas-", "eternitas"),
    (r"^windy-registry", "windy-registry"), (r"^windyclone-", "Windy-Clone"),
    (r"^windymail", "windy-mail"), (r"^windysearch-", "windy-search"),
    (r"^windy-git-", "windy-git"), (r"^windy-hand-", "windy-hand"),
    (r"^windytalk-", "windytalk"),  # windy-jarvis retired by Windy Talk (09-23)
    (r"^windy-translate-", "windy-translate"),
    (r"^windy-calendar|^windycalendar-", "windy-calendar"), (r"^windy-connect|^windyconnect-", "windy-connect"),
    (r"^windy-drops|^windydrops-", "windy-drops"), (r"^windy-traveler|^windytraveler-", "windy-traveler"),
]
# Services Grant owns directly (not a bridged lane repo): shown by name, not as "unmapped".
GRANT_SERVICES = [r"^windy-stt(-v2)?$"]  # Windy Word 45 (Windy Search, 09-23)


def severity(v: str) -> tuple[int, int]:
    """Higher = worse. (class, diff count)."""
    m = re.search(r"(\d+) diffs?", v)
    if m:
        return (3, int(m.group(1)))
    if v.startswith("no lock") or v.startswith("no true lock"):
        return (2, 0)
    if v.startswith("unreadable"):
        return (1, 0)
    return (0, 0)  # identical


def short(v: str) -> str:
    m = re.search(r"(\d+) diffs?", v)
    if m:
        return f"{m.group(1)} diffs"
    for k in ("no true lock", "no lock", "unreadable", "identical"):
        if v.startswith(k):
            return k
    return v[:20]


def main(guards: str, drift: str) -> int:
    d = Path(drift).read_text()
    gen = re.search(r"_Generated ([^_]*?) by", d)
    per_repo: dict[str, list[tuple[str, str]]] = {}
    unmapped, grant = [], []
    for line in d.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] not in ("kit0", "veron"):
            continue
        svc = re.sub(r"\s*\(user\)$", "", cells[1]).removesuffix(".service")
        verdict = cells[3].replace("*", "")
        repo = next((r for pat, r in SERVICE_REPO if re.search(pat, svc)), None)
        if repo:
            per_repo.setdefault(repo, []).append((svc, verdict))
        elif any(re.search(g, svc) for g in GRANT_SERVICES):
            grant.append(f"{cells[0]}:{svc} ({short(verdict)})")
        else:
            unmapped.append(f"{cells[0]}:{svc} ({short(verdict)})")
    out, in_table = [], False
    for line in Path(guards).read_text().splitlines():
        if line.startswith("| Repo |") and "| first items |" in line and "prod vs lock" not in line:
            ncols = line.count("|") - 1  # 6 since the owner column (09-23); "first items" is last
            line = line.replace("| first items |", "| prod vs lock | first items |")
            in_table = True
        elif in_table and line.startswith("|---|") and line.count("|") == ncols + 1:
            line = "|---" * (ncols + 1) + "|"
        elif in_table and line.startswith("| ") and line.count("|") == ncols + 1:
            cells = line.split("|")
            repo = cells[1].strip()
            svcs = per_repo.get(repo, [])
            if svcs:
                worst = max(svcs, key=lambda s: severity(s[1]))
                col = short(worst[1]) if len(svcs) == 1 else f"worst {short(worst[1])} ({worst[0]}; {len(svcs)} svcs)"
                if severity(worst[1])[0] == 0:
                    col = "identical ✅" if len(svcs) == 1 else f"identical ✅ ({len(svcs)} svcs)"
            else:
                col = "—"
            cells.insert(ncols, f" {col} ")
            line = "|".join(cells)
        elif in_table and not line.startswith("|"):
            in_table = False
            out.append(f"_prod vs lock: PROD_LOCK_DRIFT.md (Windy Search lane, generated {gen.group(1) if gen else '?'}); worst verdict per repo. "
                       f"Grant's services: {', '.join(grant) or 'none'}. Unmapped: {', '.join(unmapped) or 'none'}._")
        out.append(line)
    Path(guards).write_text("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
