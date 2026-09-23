-- Cancel CI jobs that can never run (called by scripts/cancel_unrunnable.sh).
--
-- A job whose runs-on names a label no Windy Git runner offers (ubuntu-latest,
-- macos-latest, windows-latest …) waits forever: Gitea evaluates a job's `if:`
-- only when a runner picks it, so even `if: false` / tag-only jobs sit in the
-- queue, invisible to /actions/tasks, and keep their run "waiting" for good.
-- After 30 minutes they are cancelled here; the run's status is then recomputed
-- (failure > still-active > cancelled > success), the same precedence Gitea uses.
-- Keep RUNNER_LABELS in step with deploy/runner/config.yaml.
BEGIN;
WITH dead AS (
  UPDATE action_run_job j
     SET status = 3, stopped = extract(epoch from now())::bigint, updated = extract(epoch from now())::bigint
   WHERE j.status IN (5, 7)
     AND to_timestamp(j.created) < now() - interval '30 minutes'
     AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(j.runs_on::jsonb) l
                 WHERE l NOT IN ('veron-1', 'linux-x64', 'self-hosted', 'linux', 'x64'))
  RETURNING j.run_id
)
UPDATE action_run r
   SET status = CASE
         WHEN EXISTS (SELECT 1 FROM action_run_job x WHERE x.run_id = r.id AND x.status = 2) THEN 2
         WHEN EXISTS (SELECT 1 FROM action_run_job x WHERE x.run_id = r.id AND x.status IN (5, 6, 7)) THEN r.status
         WHEN EXISTS (SELECT 1 FROM action_run_job x WHERE x.run_id = r.id AND x.status = 3) THEN 3
         ELSE 1 END,
       stopped = CASE WHEN r.stopped = 0 THEN extract(epoch from now())::bigint ELSE r.stopped END
 WHERE r.id IN (SELECT DISTINCT run_id FROM dead)
RETURNING r.id;
COMMIT;
