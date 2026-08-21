DECLARE run_a STRING DEFAULT 'run-a';
DECLARE run_b STRING DEFAULT 'run-b';
DECLARE run_c STRING DEFAULT 'run-c';
DECLARE run_a_started_at TIMESTAMP DEFAULT TIMESTAMP('2026-08-21 09:00:00+00');
DECLARE run_b_started_at TIMESTAMP DEFAULT TIMESTAMP('2026-08-21 10:00:00+00');
DECLARE run_c_started_at TIMESTAMP DEFAULT TIMESTAMP('2026-08-21 11:00:00+00');
DECLARE latest_success_run_id STRING DEFAULT run_a;
DECLARE latest_success_started_at TIMESTAMP DEFAULT run_a_started_at;

CREATE TEMP FUNCTION can_replace_current(
  requested_run_id STRING,
  requested_started_at TIMESTAMP,
  latest_run_id STRING,
  latest_started_at TIMESTAMP
) AS (
  latest_run_id IS NULL
  OR requested_run_id = latest_run_id
  OR requested_started_at > latest_started_at
  OR (
    requested_started_at = latest_started_at
    AND requested_run_id > latest_run_id
  )
);

CREATE TEMP TABLE current_snapshot (run_id STRING);
CREATE TEMP TABLE observations (run_id STRING, job_id STRING);
CREATE TEMP TABLE quality_runs (run_id STRING);

-- A has already succeeded. A newer B must be accepted and become current.
INSERT INTO current_snapshot VALUES (run_a);
INSERT INTO observations VALUES (run_a, 'job-1');
INSERT INTO quality_runs VALUES (run_a);

ASSERT can_replace_current(
  run_b,
  run_b_started_at,
  latest_success_run_id,
  latest_success_started_at
) AS 'newer Run B should be accepted after Run A';

DELETE FROM current_snapshot WHERE TRUE;
INSERT INTO current_snapshot VALUES (run_b);
INSERT INTO observations VALUES (run_b, 'job-1');
INSERT INTO quality_runs VALUES (run_b);
SET latest_success_run_id = run_b;
SET latest_success_started_at = run_b_started_at;

-- A is now stale and must not execute any current/history mutation.
ASSERT NOT can_replace_current(
  run_a,
  run_a_started_at,
  latest_success_run_id,
  latest_success_started_at
) AS 'Run A should be rejected after newer Run B succeeds';

IF can_replace_current(
  run_a,
  run_a_started_at,
  latest_success_run_id,
  latest_success_started_at
) THEN
  DELETE FROM current_snapshot WHERE TRUE;
  INSERT INTO current_snapshot VALUES (run_a);
  DELETE FROM observations WHERE run_id = run_a;
  INSERT INTO observations VALUES (run_a, 'job-1');
  DELETE FROM quality_runs WHERE run_id = run_a;
  INSERT INTO quality_runs VALUES (run_a);
END IF;

ASSERT (
  SELECT COUNTIF(run_id = run_b) = 1 AND COUNT(*) = 1
  FROM current_snapshot
) AS 'stale Run A must not replace the Run B current snapshot';
ASSERT (SELECT COUNT(*) FROM observations) = 2
  AS 'stale Run A must not alter observations';
ASSERT (SELECT COUNT(*) FROM quality_runs) = 2
  AS 'stale Run A must not alter quality history';

-- Retrying current Run B remains allowed and replaces only B's run-keyed rows.
ASSERT can_replace_current(
  run_b,
  run_b_started_at,
  latest_success_run_id,
  latest_success_started_at
) AS 'same-run retry for current Run B should be accepted';

DELETE FROM current_snapshot WHERE TRUE;
INSERT INTO current_snapshot VALUES (run_b);
DELETE FROM observations WHERE run_id = run_b;
INSERT INTO observations VALUES (run_b, 'job-1');
DELETE FROM quality_runs WHERE run_id = run_b;
INSERT INTO quality_runs VALUES (run_b);

ASSERT (SELECT COUNT(*) FROM observations WHERE run_id = run_b) = 1
  AS 'same-run retry must not duplicate observations';
ASSERT (SELECT COUNT(*) FROM quality_runs WHERE run_id = run_b) = 1
  AS 'same-run retry must not duplicate quality rows';

-- A later C remains eligible after B.
ASSERT can_replace_current(
  run_c,
  run_c_started_at,
  latest_success_run_id,
  latest_success_started_at
) AS 'newer Run C should remain eligible after Run B';
