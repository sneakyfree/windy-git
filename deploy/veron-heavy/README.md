# veron-heavy

Counting semaphore for heavy jobs on Veron (Boss's VERON LOAD RULE, 11-04; caps added 11-05). Install:

    sudo install -m 755 deploy/veron-heavy/veron-heavy /usr/local/bin/veron-heavy
    sudo install -m 644 deploy/veron-heavy/veron-heavy.tmpfiles.conf /etc/tmpfiles.d/veron-heavy.conf

    veron-heavy -- npm ci
    veron-heavy --lane windy-pro -- npx vitest run --maxWorkers=2
    veron-heavy --status

- at most 4 holders fleet-wide (flock slots in /run/veron-heavy);
- WAITS (never fails) while any gate is shut, printing one "waiting" line a minute; gives up only after 4 h (exit 75).
  Gates (11-09, Test Boss's CAPACITY plan; each has an env var and a flag):
  - `/proc/pressure/io` some avg60 >= 20 (`VERON_HEAVY_IO_MAX`, `--io-max`; was 30);
  - `/proc/pressure/cpu` some avg60 >= 25 (`VERON_HEAVY_CPU_MAX`, `--cpu-max`): real CPU contention, unlike load1,
    which also counts tasks queued on a pinned job's own cores;
  - MemAvailable < 48 GB (`VERON_HEAVY_MEM_MIN_GB`, `--mem-min-gb`);
  - 1-min load >= 48, now a backstop (`VERON_HEAVY_LOAD_MAX`, `--load-max`).
  A gate whose file cannot be read is open, never a silent block;
- the job runs under `nice -n 10` + `ionice -c2 -n7` with JEST_MAX_WORKERS / PYTEST_XDIST_AUTO_NUM_WORKERS /
  PYTEST_XDIST_WORKERS = 2 and MAKEFLAGS=-j2 (VERON_HEAVY_WORKERS changes the 2). Jest has no env var for workers, so
  a jest command should still carry --maxWorkers=2;
- a holder is stopped after 2 h (`--max-run`); every acquire/wait/release is in `journalctl -t veron-heavy`; the holder
  record never contains command arguments.

Tests: `bash deploy/veron-heavy/test_veron_heavy.sh` (43 checks, ~45 s; run by api/tests/test_veron_heavy.py).
