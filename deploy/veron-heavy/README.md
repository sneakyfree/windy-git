# veron-heavy

Counting semaphore for heavy jobs on Veron (Boss's VERON LOAD RULE, 11-04; caps added 11-05). Install:

    sudo install -m 755 deploy/veron-heavy/veron-heavy /usr/local/bin/veron-heavy
    sudo install -m 644 deploy/veron-heavy/veron-heavy.tmpfiles.conf /etc/tmpfiles.d/veron-heavy.conf

    veron-heavy -- npm ci
    veron-heavy --lane windy-pro -- npx vitest run --maxWorkers=2
    veron-heavy --status

- at most 4 holders fleet-wide (flock slots in /run/veron-heavy);
- WAITS (never fails) while `/proc/pressure/io` some avg60 >= 30 OR 1-min load >= 48, printing one "waiting" line a minute;
  gives up only after 4 h (exit 75);
- the job runs under `nice -n 10` + `ionice -c2 -n7` with JEST_MAX_WORKERS / PYTEST_XDIST_AUTO_NUM_WORKERS /
  PYTEST_XDIST_WORKERS = 2 and MAKEFLAGS=-j2 (VERON_HEAVY_WORKERS changes the 2). Jest has no env var for workers, so
  a jest command should still carry --maxWorkers=2;
- a holder is stopped after 2 h (`--max-run`); every acquire/wait/release is in `journalctl -t veron-heavy`; the holder
  record never contains command arguments.

Tests: `bash deploy/veron-heavy/test_veron_heavy.sh` (43 checks, ~45 s; run by api/tests/test_veron_heavy.py).
