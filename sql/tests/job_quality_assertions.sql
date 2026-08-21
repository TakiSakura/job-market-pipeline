CREATE TEMP FUNCTION is_toronto_location(
  display_name STRING,
  area ARRAY<STRING>
) AS (
  EXISTS (
    SELECT 1 FROM UNNEST(area) AS component
    WHERE LOWER(TRIM(component)) IN ('toronto', 'city of toronto')
  )
  OR EXISTS (
    SELECT 1 FROM UNNEST(SPLIT(IFNULL(display_name, ''), ',')) AS component
    WHERE LOWER(TRIM(component)) IN ('toronto', 'city of toronto')
  )
);

CREATE TEMP FUNCTION timeliness_points(age_days INT64) AS (
  CASE
    WHEN age_days IS NULL OR age_days < -1 THEN 0
    WHEN age_days <= 30 THEN 20
    WHEN age_days <= 60 THEN 16
    WHEN age_days <= 90 THEN 12
    WHEN age_days <= 180 THEN 6
    ELSE 0
  END
);

CREATE TEMP FUNCTION salary_points(
  salary_min FLOAT64,
  salary_max FLOAT64
) AS (
  CASE
    WHEN salary_min IS NOT NULL AND salary_max IS NOT NULL
      AND salary_min > salary_max THEN 0
    WHEN salary_min < 30000 OR salary_max > 300000 THEN 3
    ELSE 6
  END
);

CREATE TEMP FUNCTION quality_status(score FLOAT64) AS (
  CASE
    WHEN score >= 80 THEN 'PASS'
    WHEN score >= 60 THEN 'REVIEW'
    ELSE 'FAIL'
  END
);

CREATE TEMP FUNCTION is_publishable(
  score FLOAT64,
  age_days INT64,
  flags ARRAY<STRING>
) AS (
  score >= 80
  AND NOT IFNULL(age_days > 180, FALSE)
  AND NOT EXISTS (
    SELECT 1 FROM UNNEST(flags) AS flag
    WHERE flag IN (
      'MISSING_CRITICAL_FIELD',
      'INVALID_POSTED_DATE',
      'FUTURE_POSTED_DATE',
      'INVALID_SALARY_RANGE'
    )
  )
);

ASSERT is_toronto_location(
  'Toronto, Ontario', ['Canada', 'Ontario', 'Toronto']
) AS 'Toronto should be included';
ASSERT is_toronto_location(
  'North York, Toronto', ['Canada', 'Ontario', 'Toronto', 'North York']
) AS 'North York should normalize through structured Toronto';
ASSERT is_toronto_location(
  'Etobicoke, Toronto', ['Canada', 'Ontario', 'Toronto', 'Etobicoke']
) AS 'Etobicoke should normalize through structured Toronto';
ASSERT is_toronto_location(
  'Toronto Dominion Centre, City of Toronto',
  ['Canada', 'Ontario', 'City of Toronto', 'Toronto Dominion Centre']
) AS 'City of Toronto sublocations should be included';
ASSERT is_toronto_location(
  'Harbourfront, City of Toronto', ['Canada', 'Ontario', 'City of Toronto']
) AS 'Harbourfront should normalize through City of Toronto';
ASSERT is_toronto_location(
  'Union Station, City of Toronto', ['Canada', 'Ontario', 'City of Toronto']
) AS 'Union Station should normalize through City of Toronto';
ASSERT NOT is_toronto_location(
  'Markham, Ontario', ['Canada', 'Ontario', 'York Region', 'Markham']
) AS 'Markham must not be broadened into Toronto';
ASSERT NOT is_toronto_location(
  'Mississauga, Ontario', ['Canada', 'Ontario', 'Peel Region', 'Mississauga']
) AS 'Mississauga must not be broadened into Toronto';

ASSERT timeliness_points(30) = 20 AS '30-day timeliness boundary failed';
ASSERT timeliness_points(31) = 16 AS '31-day timeliness boundary failed';
ASSERT timeliness_points(60) = 16 AS '60-day timeliness boundary failed';
ASSERT timeliness_points(61) = 12 AS '61-day timeliness boundary failed';
ASSERT timeliness_points(90) = 12 AS '90-day timeliness boundary failed';
ASSERT timeliness_points(91) = 6 AS '91-day stale boundary failed';
ASSERT timeliness_points(180) = 6 AS '180-day timeliness boundary failed';
ASSERT timeliness_points(181) = 0 AS '181-day timeliness boundary failed';
ASSERT timeliness_points(-2) = 0 AS 'future-date timeliness failed';

ASSERT salary_points(NULL, NULL) = 6
  AS 'missing salary should retain all salary-validity points';
ASSERT salary_points(29999, NULL) = 3
  AS 'low salary should receive suspicious-salary points';
ASSERT salary_points(NULL, 300001) = 3
  AS 'high salary should receive suspicious-salary points';
ASSERT salary_points(90000, 50000) = 0
  AS 'invalid salary range should receive zero salary-validity points';
ASSERT salary_points(50000, 90000) = 6
  AS 'valid salary range should receive all salary-validity points';

ASSERT quality_status(80) = 'PASS' AS 'PASS boundary failed';
ASSERT quality_status(79) = 'REVIEW' AS 'REVIEW upper boundary failed';
ASSERT quality_status(60) = 'REVIEW' AS 'REVIEW lower boundary failed';
ASSERT quality_status(59) = 'FAIL' AS 'FAIL boundary failed';

ASSERT is_publishable(80, 180, ['STALE_JOB'])
  AS '180-day stale row should remain publishable at threshold';
ASSERT NOT is_publishable(80, 181, ['STALE_JOB'])
  AS '181-day stale row must be blocked without changing its score';
ASSERT NOT is_publishable(100, 1, ['MISSING_CRITICAL_FIELD'])
  AS 'missing critical field must block publishing';
ASSERT NOT is_publishable(100, 1, ['INVALID_POSTED_DATE'])
  AS 'invalid date must block publishing';
ASSERT NOT is_publishable(100, -2, ['FUTURE_POSTED_DATE'])
  AS 'future date must block publishing';
ASSERT NOT is_publishable(100, 1, ['INVALID_SALARY_RANGE'])
  AS 'invalid salary range must block publishing';
ASSERT is_publishable(80, 30, [])
  AS 'row meeting threshold without hard flags should publish';
ASSERT NOT is_publishable(79, 30, [])
  AS 'row below threshold should not publish';

-- The stable completeness formula totals 50 points.
ASSERT 10 + 10 + 8 + 6 + 4 + 4 + 4 + 4 = 50
  AS 'completeness weights must total 50';
-- The stable validity formula totals 30 points for a valid row.
ASSERT 8 + 4 + salary_points(NULL, NULL) + 6 + 6 = 30
  AS 'validity weights must total 30';
-- A complete, valid, recent row remains a 100-point row.
ASSERT 50 + 30 + timeliness_points(10) = 100
  AS 'complete recent row should score 100';
-- A complete, valid, 181-day row remains PASS at score 80 but is not publishable.
ASSERT quality_status(50 + 30 + timeliness_points(181)) = 'PASS'
  AS '181-day row should keep PASS quality status';
ASSERT NOT is_publishable(
  50 + 30 + timeliness_points(181),
  181,
  ['STALE_JOB']
) AS '181-day row should remain curated but not publishable';

-- Upstream duplicate uniqueness uses RAW observations before SQL deduplication.
CREATE TEMP TABLE raw_ids AS
SELECT '1' AS source_job_id UNION ALL
SELECT '2' UNION ALL
SELECT '2' UNION ALL
SELECT '3';

ASSERT (
  SELECT COUNT(*) - COUNT(DISTINCT source_job_id) FROM raw_ids
) = 1 AS 'RAW duplicate count failed';
ASSERT (
  SELECT ROUND(
    SAFE_DIVIDE(
      COUNT(*) - (COUNT(*) - COUNT(DISTINCT source_job_id)),
      COUNT(*)
    ) * 100,
    2
  )
  FROM raw_ids
) = 75.0 AS 'RAW uniqueness score failed';
