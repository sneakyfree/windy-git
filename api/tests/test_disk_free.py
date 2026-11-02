"""scripts/disk_free.py: GB tiers (150 LOW / 50 CRITICAL), one BOARD line + one Boss line per downward
crossing, silent while staying, re-armed on recovery, a failed post is retried (Boss 11-02)."""

from __future__ import annotations

import importlib.util
import sys
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("disk_free", ROOT / "scripts" / "disk_free.py")
df = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(df)
U = namedtuple("U", "total used free")
GB = 10**9


def disk(free_gb, total_gb=3600):
    return lambda p: U(total_gb * GB, (total_gb - free_gb) * GB, int(free_gb * GB))


def test_tiers_at_the_boundaries():
    assert df.tier(150) == 0 and df.tier(149.9) == 1 and df.tier(50) == 1 and df.tier(49.9) == 2
    assert df.tier(0) == 2


def test_check_lines_and_the_healthy_line_stay_exact():
    lines, tiers = df.check(["/"], disk(238, 3664))
    assert lines == ["disk free: 238 GB of 3664 GB (6.5%) on /", "disk: ok"] and tiers["/"] == (0, 238)
    low, _ = df.check(["/"], disk(120))
    assert low[-1] == "disk: LOW under 150 GB free on / (BOARD + Boss)"
    crit, _ = df.check(["/"], disk(40))
    assert crit[-1] == "disk: CRITICAL under 50 GB free on / (BOARD + Boss)"


def test_old_ten_percent_warn_is_retired():
    # 5% free of 3600 GB = 180 GB: the old rule warned (under 10%), the new one is quiet.
    assert df.check(["/"], disk(180))[0][-1] == "disk: ok"


def test_worst_mount_decides():
    sizes = {"/": U(1000 * GB, 0, 500 * GB), "/srv": U(1000 * GB, 0, 10 * GB)}
    out, _ = df.check(["/", "/srv"], lambda p: sizes[p])
    assert out[-1] == "disk: CRITICAL under 50 GB free on /srv (BOARD + Boss)" and len(out) == 3


class Posts:
    def __init__(self, board_ok=True, say_ok=True):
        self.board_ok, self.say_ok, self.board_lines, self.says = board_ok, say_ok, [], []

    def board(self, line):
        self.board_lines.append(line)
        return self.board_ok

    def say(self, text):
        self.says.append(text)
        return self.say_ok


def run(state, free_gb, posts):
    _, tiers = df.check(["/"], disk(free_gb))
    return df.announce(tiers, state, board=posts.board, say=posts.say)


def test_one_line_per_crossing_then_silent_then_rearmed():
    p, st = Posts(), {}
    st = run(st, 238, p)
    assert (p.board_lines, p.says) == ([], [])  # healthy: nothing
    st = run(st, 140, p)  # crosses under 150
    assert len(p.board_lines) == 1 and p.board_lines[0].startswith("[Windy Git] [AUTOMATED disk-watch] Veron free 140 GB")
    assert p.says == ["[AUTOMATED disk-watch] Veron free 140 GB"]
    st = run(st, 139, p)
    st = run(st, 120, p)  # still LOW: silent
    assert len(p.board_lines) == 1 and len(p.says) == 1
    st = run(st, 45, p)  # crosses under 50: bold line
    assert len(p.board_lines) == 2 and p.board_lines[1].startswith("[Windy Git] **[AUTOMATED disk-watch] Veron free 45 GB")
    assert p.says[1] == "[AUTOMATED disk-watch] Veron free 45 GB"
    st = run(st, 44, p)  # still CRITICAL: silent
    assert len(p.board_lines) == 2
    st = run(st, 300, p)  # recovered: silent, re-armed
    assert len(p.board_lines) == 2 and st["/"]["tier"] == 0
    st = run(st, 100, p)  # crosses again: speaks again
    assert len(p.board_lines) == 3 and len(p.says) == 3


def test_a_critical_drop_straight_from_ok_speaks_once_as_critical():
    p = Posts()
    run({}, 30, p)
    assert len(p.board_lines) == 1 and "**" in p.board_lines[0] and len(p.says) == 1


def test_recovery_from_critical_to_low_is_silent_and_does_not_reannounce():
    p, st = Posts(), {}
    st = run(st, 40, p)
    st = run(st, 100, p)  # critical -> low: better, no line
    st = run(st, 99, p)
    assert len(p.board_lines) == 1 and len(p.says) == 1


def test_failed_board_is_not_recorded_and_retries():
    p = Posts(board_ok=False)
    st = run({}, 100, p)
    assert p.says == [] and st["/"].get("done") is None  # no Boss line without a BOARD line
    p.board_ok = True
    st = run(st, 100, p)
    assert len(p.board_lines) == 2 and len(p.says) == 1 and st["/"]["done"] is True


def test_failed_fleet_say_retries_alone_without_a_second_board_line():
    p = Posts(say_ok=False)
    st = run({}, 100, p)
    assert len(p.board_lines) == 1 and st["/"]["board"] is True and not st["/"].get("done")
    p.say_ok = True
    st = run(st, 100, p)
    assert len(p.board_lines) == 1 and len(p.says) == 2 and st["/"]["done"] is True
    run(st, 100, p)
    assert len(p.says) == 2  # done: silent


def test_state_file_roundtrip_and_garbage(tmp_path):
    f = tmp_path / "s" / "d.json"
    df.save_state({"/": {"tier": 1, "board": True, "done": True}}, f)
    assert df.load_state(f) == {"/": {"tier": 1, "board": True, "done": True}}
    f.write_text("not json")
    assert df.load_state(f) == {}
    f.write_text("[1]")
    assert df.load_state(f) == {}
