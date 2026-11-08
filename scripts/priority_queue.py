#!/usr/bin/env python3
"""Priority for dated slots (Boss 11-04 16:48Z): a PR that Boss NAMES on the BOARD runs before the rest of the queue.

Boss writes one token on a BOARD line of his own:

    PRIORITY <repo>#<PR> until <YYYY-MM-DDTHH:MMZ>          e.g.  PRIORITY windy-pro#1706 until 2026-11-05T12:35Z

Every run (a timer, every 2 minutes) this reads the BOARD tail and, for each ACTIVE token, moves that PR's WAITING
jobs to the front of Windy Git's queue. Gitea 1.24 has no priority knob: a runner is handed the waiting job with
the lowest `updated`, then the lowest `id` (the mechanism scripts/queue_jump.sh proves for a hand jump). So the
moved jobs get `updated` = one second below the oldest NON-priority waiting job. Re-running is a no-op.

Rules (each one tested):
  * only a line that BOARD-says it is from `Windy Boss` counts (the header: an ISO time, then `Windy Boss`);
    a lane that quotes the token in its own line is ignored. (Anyone can append to the BOARD file, so a forged
    Boss header would reorder the queue; it cannot cancel, delete or touch a running job.)
  * `until` is at most 24 h after the EARLIER of that line's own time and now (a later `until` is clamped); a line
    dated more than 5 min in the future is ignored; the token expires by itself; only the last 2,000 BOARD lines are read;
  * at most 3 PRs at once (the newest tokens win); the LAST line for one repo#PR wins, so a line with a past
    `until` revokes it;
  * a QUOTED token (right after ' " ` or a curly quote) is a description, never a grant; a Boss line that says
    NO PRIORITY grants nothing, but its past-`until` tokens still revoke (Boss 11-08 22:28:41Z: his 21:16:44Z line
    ruled "NO PRIORITY token for windy-pro #1718" and quoted the fallback's text, which was read as live);
  * only WAITING (status 5), unclaimed (task_id 0) jobs of the NEWEST run on that PR's ref (a superseded head is
    cancelled by cancel_superseded, never promoted); never a running job, never another repo, never a cancel;
  * the BOARD cannot be read (Windy 0 down and no fallback file): do nothing and say so (exit 1, never "ok");
  * a token whose PR no OTHER Windy Boss line of the same UTC day names is logged once as UNVERIFIED TOKEN (it is still
    applied: Boss wants to see it, not to block it);
  * one BOARD line when a token is first seen, one (at most every 30 min per PR) when jobs were moved, one when
    it expires.
Output for windy-job --expect: `priority: ok (...)` or `priority: UNREADABLE ...`.
  * the token names the GITHUB PR number (what Boss and the lanes see). Windy Git's own PR number differs for most
    repos (windy-calendar GitHub #130 is Windy Git PR 73), so the number is resolved to the PR's head sha through
    GitHub (cached 5 min) and the jobs matched by that commit on a pull ref; only when GitHub cannot be asked
    does it fall back to refs/pull/<number>/head (right for repos whose numbers agree).
  --dry   print what would move, write nothing.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cancel_superseded as cs  # noqa: E402  (psql, board, BOARD_USER, FALLBACK_DIR)

STATE = Path(os.environ.get("PRIORITY_STATE", "/var/lib/windygit/priority-queue.json"))
TAIL_LINES = 2000       # ~5 days of BOARD (about 390 lines a day); an old forged line has long expired anyway
MAX_PRS = 3
MAX_HOURS = 24
MOVED_POST_EVERY_S = 1800
OWNER = "windyadmin"

HEADER = re.compile(r"^[\s\-*\[]*(\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?Z)[\],\s]+\[?\s*Windy Boss\b")
TOKEN = re.compile(r"\bPRIORITY ([A-Za-z0-9._-]{1,100})#(\d{1,7}) until (\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?Z)(?![\w:])")
NO_PRIORITY = re.compile(r"\bNO[\s-]+PRIORITY\b", re.IGNORECASE)
QUOTES = set("'\"`\u2018\u201c")   # a token right after one of these opens a quote: never a grant


def ts(s: str) -> int:
    s = s if s.count(":") == 2 else s[:-1] + ":00Z"
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))


def _parse(text: str, now: int):
    out: dict[tuple[str, int], tuple[int, int, int]] = {}      # key -> (line_ts, until, line index)
    notes: list[str] = []
    for idx, line in enumerate(text.splitlines()):
        h = HEADER.match(line)
        if not h or "PRIORITY" not in line:
            continue
        line_ts = ts(h.group(1))
        if line_ts > now + 300:
            notes.append("ignored a token on a line dated in the future")
            continue
        body = line[h.end():]
        refuses = bool(NO_PRIORITY.search(body))
        for m in TOKEN.finditer(body):
            repo, pr, until_s = m.groups()
            # A QUOTED token is a description, not a grant (11-08: Boss ruled "NO PRIORITY token ... tonight" and
            # quoted the fallback's full text "PRIORITY windy-pro#1718 until ..."; the quote was read as live).
            if body[:m.start()].rstrip()[-1:] in QUOTES:
                notes.append(f"ignored a quoted token ({repo}#{pr})")
                continue
            # never more than 24 h from the EARLIER of the line's own time and now (Hub #130): a forged, far-future
            # line time cannot buy more than 24 h, and a line dated in the future is dropped above
            until = min(ts(until_s), min(line_ts, now) + MAX_HOURS * 3600)
            # A line that says NO PRIORITY grants nothing; it can still REVOKE (an until at or before its own
            # time), so a ruling against a token never keeps one alive.
            if refuses and until > line_ts:
                notes.append(f"ignored a grant on a NO PRIORITY line ({repo}#{pr})")
                continue
            out[(repo, int(pr))] = (line_ts, until, idx)   # a later line replaces an earlier one
    keep = {k: v for k, v in out.items()}
    # newest MAX_PRS tokens (by line time) among the still-active ones
    active = sorted(((k, v) for k, v in keep.items() if v[1] > now), key=lambda kv: kv[1][0], reverse=True)
    if len(active) > MAX_PRS:
        notes.append(f"{len(active)} active tokens: only the newest {MAX_PRS} are used")
    return {k: v[1] for k, v in active[:MAX_PRS]}, notes, {k: (v[0], v[2]) for k, v in active[:MAX_PRS]}


def parse_board(text: str, now: int) -> tuple[dict[tuple[str, int], int], list[str]]:
    """{(repo, pr): until_epoch} for the tokens that count (last line wins; clamped to 24 h), plus notes."""
    active, notes, _where = _parse(text, now)
    return active, notes


LOOKS_LIKE_TOKEN = re.compile(r"\bPRIORITY\s+[A-Za-z0-9._-]{1,100}#\d{1,7}\b")
UNPARSED_MAX_PER_PASS = 3


def unparsed(text: str, now: int) -> list[tuple[str, str]]:
    """Boss lines (dated within the last 24 h, not in the future) that NAME a PRIORITY repo#PR but whose token does
    not parse: [(dedupe key, short snippet)]. A silently ignored token was the 11-05 failure (#1764, 'until ...:00Z')."""
    out = []
    for line in text.splitlines():
        h = HEADER.match(line)
        if not h or "PRIORITY" not in line:
            continue
        line_ts = ts(h.group(1))
        if line_ts > now + 300 or now - line_ts > MAX_HOURS * 3600:
            continue
        body = line[h.end():]
        if len(LOOKS_LIKE_TOKEN.findall(body)) > len(TOKEN.findall(body)):
            snip = re.sub(r"[^\x20-\x7e]|[`$\"\\]", "?", body.strip())[:110]   # BOARD line rule: no backtick, $, quote, backslash
            out.append((f"{line_ts}:{hashlib.sha1(snip.encode()).hexdigest()[:8]}", snip))
    return out


def verified(text: str, repo: str, pr: int, line_ts: int, line_idx: int) -> bool:
    """Boss 11-04 17:07Z: is this PR ALSO named in another `Windy Boss` BOARD line dated the same UTC day as the token
    line (a slot line)? A line carrying this PR's own token does not count. False = log it as an unverified token."""
    day = time.strftime("%Y-%m-%d", time.gmtime(line_ts))
    mention = re.compile(rf"#{pr}(?!\d)")
    own = re.compile(rf"PRIORITY {re.escape(repo)}#{pr} until")
    for i, line in enumerate(text.splitlines()):
        h = HEADER.match(line)
        if i == line_idx or not h or not h.group(1).startswith(day):
            continue
        if mention.search(own.sub("", line[h.end():])):
            return True
    return False


def read_board() -> str | None:
    try:
        r = subprocess.run(["runuser", "-u", cs.BOARD_USER, "--", "timeout", "25", "ssh", "-o", "BatchMode=yes",
                            "-o", "ConnectTimeout=8", "eth-windy0", f"tail -n {TAIL_LINES} ~/windy-orchestra/BOARD.md"],
                           capture_output=True, text=True, timeout=40)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    except (subprocess.SubprocessError, OSError):
        pass
    path = Path(cs.FALLBACK_DIR) / f"BOARD-FALLBACK-{time.strftime('%Y%m%d', time.gmtime())}.md"
    try:
        return "\n".join(path.read_text().splitlines()[-TAIL_LINES:])
    except OSError:
        return None


def gh_head(repo: str, pr: int) -> str | None:
    """Head sha of GitHub PR repo#pr, asked as the BOARD user (it holds the gh login). None when it cannot be told."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", repo):
        return None
    try:
        out = subprocess.run(["runuser", "-u", cs.BOARD_USER, "--", "timeout", "25", "gh", "api",
                              f"repos/sneakyfree/{repo}/pulls/{int(pr)}", "--jq", ".head.sha"],
                             capture_output=True, text=True, timeout=40).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out if re.fullmatch(r"[0-9a-f]{40}", out) else None


def jobs_sql(repo: str, pr: int, sha: str) -> str:
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,100}", repo) and isinstance(pr, int) and pr > 0
    assert isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha)
    where_ref = f"r.ref like 'refs/pull/%/head' and r.commit_sha = '{sha}'"
    return f"""
select j.id, j.name from action_run_job j
join action_run r on r.id = j.run_id
join repository p on p.id = j.repo_id
where p.owner_name = '{OWNER}' and p.name = '{repo}' and {where_ref}
  and r.event in ('pull_request', 'pull_request_sync')
  and j.status = 5 and j.task_id = 0
  and r.id = (select max(r2.id) from action_run r2 where r2.repo_id = r.repo_id and r2.ref = r.ref
              and r2.workflow_id = r.workflow_id)
order by j.id;"""


def floor_sql(ids: list[int]) -> str:
    lst = ",".join(str(int(i)) for i in ids)
    return f"select coalesce(min(updated), 0), count(*) from action_run_job where status = 5 and task_id = 0 and id not in ({lst});"


def move_sql(ids: list[int], floor: int) -> str:
    lst = ",".join(str(int(i)) for i in ids)
    return (f"update action_run_job set updated = {int(floor) - 1} where id in ({lst}) and status = 5 and task_id = 0 "
            f"and updated >= {int(floor)} returning id, name;")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st))
        os.replace(tmp, STATE)
    except OSError as e:
        print(f"  state not saved ({e}); a BOARD line may repeat")


def main(query=cs.psql, post=cs.board, read=read_board, now_fn=time.time, dry=False, head=gh_head) -> int:
    now = int(now_fn())
    text = read()
    if text is None:
        print("priority: UNREADABLE board (Windy 0 down and no fallback file): nothing moved")
        return 1
    active, notes, where = _parse(text, now)
    st = load_state()
    seen = st.setdefault("seen", {})
    posted = st.setdefault("moved_posted", {})
    flagged = st.setdefault("unverified", {})
    heads = st.setdefault("heads", {})
    heads_at = st.setdefault("heads_at", {})
    warned = st.setdefault("unparsed", {})
    for k in [k for k in warned if int(k.split(":")[0]) < now - 2 * MAX_HOURS * 3600]:
        warned.pop(k)                                           # state does not grow forever
    n_warn = 0
    for key, snip in unparsed(text, now):
        if key in warned or n_warn >= UNPARSED_MAX_PER_PASS:
            continue
        n_warn += 1
        if not dry:
            post(f"[Windy Git] PRIORITY WARN: a Windy Boss line names a PRIORITY token I CANNOT PARSE, so it is IGNORED: \"{snip}\". "
                 f"Format: PRIORITY repo#PR until YYYY-MM-DDTHH:MMZ (seconds allowed). Re-post it in that form.")
            warned[key] = now
    total = 0
    unresolved: list[str] = []
    for (repo, pr), until in sorted(active.items()):
        key = f"{repo}#{pr}"
        until_s = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(until))
        if key not in seen or seen[key] != until:
            if not dry:
                post(f"[Windy Git] PRIORITY ACTIVE {key} until {until_s} (Boss's BOARD token): its WAITING jobs go first in the CI queue; "
                     f"nothing running or other lanes' jobs are touched.")
            seen[key] = until
        lts, lidx = where[(repo, pr)]
        if not verified(text, repo, pr, lts, lidx):
            if flagged.get(key) != until and not dry:
                post(f"[Windy Git] PRIORITY UNVERIFIED TOKEN {key} until {until_s}: no other Windy Boss line dated that day "
                     f"(UTC) names #{pr}, so I cannot tell a slot line from a forged one. It is applied (reorders WAITING jobs "
                     f"only); Boss: confirm in a slot line, or revoke with a past `until`.")
            flagged[key] = until
        else:
            flagged.pop(key, None)
        sha = heads.get(key)
        if not sha or now - heads_at.get(key, 0) > 300:
            sha = head(repo, pr) or sha
            if sha:
                heads[key], heads_at[key] = sha, now
        if not sha:
            # FAIL CLOSED: without the head sha the number would be read as a Windy Git PR number, which for most repos
            # is somebody else's PR (Hub #135 MED). Move nothing, say so (rate-limited), retry next tick.
            print(f"  UNRESOLVED {key} (GitHub unreachable): nothing moved")
            unresolved.append(key)
            if not dry and now - posted.get("unresolved:" + key, 0) >= MOVED_POST_EVERY_S:
                post(f"[Windy Git] priority: UNRESOLVED {key} (GitHub unreachable), nothing moved; retrying every tick.")
                posted["unresolved:" + key] = now
            continue
        rows = query(jobs_sql(repo, pr, sha))
        ids = [int(r[0]) for r in rows]
        if not ids:
            continue
        fl = query(floor_sql(ids))
        if not fl or int(fl[0][1]) == 0:
            continue                       # every waiting job is a priority job: nothing to get ahead of
        floor = int(fl[0][0])
        if dry:
            print(f"  would move {len(ids)} waiting job(s) of {key} below updated={floor}")
            continue
        moved = query(move_sql(ids, floor))
        total += len(moved)
        if moved and now - posted.get(key, 0) >= MOVED_POST_EVERY_S:
            post(f"[Windy Git] PRIORITY {key}: moved {len(moved)} waiting job(s) to the front of the queue "
                 f"({', '.join(sorted({m[1] for m in moved}))[:150]}); token ends {until_s}.")
            posted[key] = now
    for key in [k for k in list(seen) if k not in {f"{r}#{p}" for r, p in active}]:
        if not dry:
            post(f"[Windy Git] PRIORITY ENDED {key}: its token expired or was revoked; the PR queues like the others now.")
        seen.pop(key, None)
        posted.pop(key, None)
        flagged.pop(key, None)
    if not dry:
        save_state(st)
    names = ", ".join(f"{r}#{p}" for r, p in sorted(active)) or "none"
    print(f"priority: ok ({len(active)} active token(s): {names}; {total} job(s) moved{'; ' + '; '.join(notes) if notes else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main(dry="--dry" in sys.argv))
