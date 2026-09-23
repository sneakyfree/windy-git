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
  RETURNING j.id, j.run_id, j.name, j.runs_on, j.created
), runs AS (
  UPDATE action_run r
     SET status = CASE
           WHEN EXISTS (SELECT 1 FROM action_run_job x WHERE x.run_id = r.id AND x.status = 2) THEN 2
           WHEN EXISTS (SELECT 1 FROM action_run_job x WHERE x.run_id = r.id AND x.status IN (5, 6, 7)
                          AND x.id NOT IN (SELECT id FROM dead)) THEN r.status
           ELSE 3 END,
         stopped = CASE WHEN r.stopped = 0 THEN extract(epoch from now())::bigint ELSE r.stopped END
   WHERE r.id IN (SELECT DISTINCT run_id FROM dead)
  RETURNING r.id
)
-- One JSON line per cancelled job: the telemetry emitter ships these as
-- ci.job_cancelled (declared with Telemetry Boss, 2026-09-23).
SELECT json_build_object(
         'repo', p.lower_name,
         'workflow', regexp_replace(r.workflow_id, '\.ya?ml$', ''),
         'job', d.name,
         'reason', 'unrunnable_label',
         'runs_on', (SELECT string_agg(l, ',') FROM jsonb_array_elements_text(d.runs_on::jsonb) l),
         'waited_s', (extract(epoch from now())::bigint - d.created))::text
  FROM dead d JOIN action_run r ON r.id = d.run_id JOIN repository p ON p.id = r.repo_id
 WHERE (SELECT count(*) FROM runs) >= 0;

-- Jobs BLOCKED on `needs:` inside a run that has already finished (a needed job
-- failed): Gitea leaves them status 7 forever. They were never going to run;
-- mark them skipped (4), which is what GitHub shows for the same situation.
UPDATE action_run_job j
   SET status = 4, updated = extract(epoch from now())::bigint
  FROM action_run r
 WHERE r.id = j.run_id
   AND j.status = 7
   AND r.status IN (1, 2, 3)
   AND to_timestamp(j.created) < now() - interval '30 minutes'
RETURNING j.run_id;
COMMIT;
