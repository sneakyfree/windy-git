# journey window + Veron throttle

Boss 11-04 23:44Z (sign-up journeys J1/J3 starved by CI load), narrowed 00:30Z, throttle added 02:13Z.

- **Window:** Veron's three general runners (`veron-1`, `veron-1-2`, `veron-1-3`, Gitea ids 2/4/5) take no new jobs
  from :17 to :40 UTC every hour; to :50 in the J3 hours 15, 19, 23 and in any hour listed (one per line) in
  `/etc/windygit/journey-window.hours`. Running jobs finish.
- **Throttle:** outside the window only the lowest-id runner stays active; the other two are held.
- **How:** Gitea matches a waiting job to a runner by `action_runner.agent_labels`. A held runner's labels become
  `["journey-window"]` (nothing asks for that); the real labels are kept in `/var/lib/windygit/journey-window.json` and
  put back. A runner that restarts and re-declares its labels is held again within a minute. Null 0, Windy 0, the
  canary and the userns runner are never touched.
- **Off switch:** `touch /etc/windygit/journey-window.off` (restores within a minute), or
  `windygit-journey-window restore`. Remove the throttle for good: `KEEP_ACTIVE = 3`.

Install (root, Veron):

    install -m 755 deploy/journey-window/windygit-journey-window /usr/local/sbin/
    install -m 644 deploy/journey-window/windygit-journey-window.{service,timer} /etc/systemd/system/
    mkdir -p /var/lib/windygit /etc/windygit && systemctl daemon-reload && systemctl enable --now windygit-journey-window.timer

Tests: `api/tests/test_journey_window.py` (fake runner table, 12 tests).
