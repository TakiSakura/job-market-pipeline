CREATE OR REPLACE TABLE FUNCTION `weekly-market-trend.job_market.job_run_rows`(
  requested_run_id STRING,
  processed_at TIMESTAMP,
  publish_threshold FLOAT64
)
AS (
  WITH scoped_raw AS (
    SELECT
      raw.run_id,
      raw.ingested_at,
      COALESCE(
        NULLIF(raw.source_job_id, ''),
        NULLIF(raw.job_id, ''),
        NULLIF(JSON_VALUE(raw.raw_payload, '$.id'), '')
      ) AS source_job_id,
      COALESCE(raw.page_number, 1) AS page_number,
      COALESCE(raw.position_in_page, 1) AS position_in_page,
      COALESCE(JSON_VALUE(raw.raw_payload, '$.title'), raw.title) AS title,
      COALESCE(
        JSON_VALUE(raw.raw_payload, '$.company.display_name'),
        raw.company
      ) AS company,
      COALESCE(
        JSON_VALUE(raw.raw_payload, '$.location.display_name'),
        raw.location
      ) AS location,
      CASE
        WHEN ARRAY_LENGTH(raw.location_area) > 0 THEN raw.location_area
        ELSE ARRAY(
          SELECT JSON_VALUE(component)
          FROM UNNEST(
            IFNULL(
              JSON_QUERY_ARRAY(raw.raw_payload, '$.location.area'),
              ARRAY<JSON>[]
            )
          ) AS component
          WHERE JSON_VALUE(component) IS NOT NULL
        )
      END AS location_area,
      COALESCE(JSON_VALUE(raw.raw_payload, '$.created'), raw.posted_date)
        AS posted_date,
      COALESCE(
        SAFE_CAST(JSON_VALUE(raw.raw_payload, '$.salary_min') AS FLOAT64),
        raw.salary_min
      ) AS salary_min,
      COALESCE(
        SAFE_CAST(JSON_VALUE(raw.raw_payload, '$.salary_max') AS FLOAT64),
        raw.salary_max
      ) AS salary_max,
      COALESCE(JSON_VALUE(raw.raw_payload, '$.description'), raw.description)
        AS description,
      COALESCE(
        JSON_VALUE(raw.raw_payload, '$.category.label'),
        raw.category
      ) AS category,
      COALESCE(
        JSON_VALUE(raw.raw_payload, '$.contract_type'),
        raw.contract_type
      ) AS contract_type,
      COALESCE(raw.source, 'Adzuna') AS source,
      COALESCE(raw.job_url, JSON_VALUE(raw.raw_payload, '$.redirect_url'))
        AS job_url
    FROM `weekly-market-trend.job_market.raw_jobs` AS raw
    WHERE raw.run_id = requested_run_id
  ),
  deduplicated AS (
    SELECT *
    FROM scoped_raw
    QUALIFY
      source_job_id IS NULL
      OR ROW_NUMBER() OVER (
        PARTITION BY source_job_id
        ORDER BY page_number, position_in_page, ingested_at
      ) = 1
  ),
  toronto_jobs AS (
    SELECT
      source_job_id AS job_id,
      title,
      company,
      'Toronto' AS city,
      'Ontario' AS province,
      'Canada' AS country,
      posted_date,
      salary_min,
      salary_max,
      description,
      category,
      contract_type,
      source,
      job_url,
      run_id
    FROM deduplicated
    WHERE
      EXISTS (
        SELECT 1
        FROM UNNEST(location_area) AS component
        WHERE LOWER(TRIM(component)) IN ('toronto', 'city of toronto')
      )
      OR EXISTS (
        SELECT 1
        FROM UNNEST(SPLIT(IFNULL(location, ''), ',')) AS component
        WHERE LOWER(TRIM(component)) IN ('toronto', 'city of toronto')
      )
  ),
  parsed AS (
    SELECT
      *,
      SAFE_CAST(posted_date AS TIMESTAMP) AS posted_at
    FROM toronto_jobs
  ),
  aged AS (
    SELECT
      *,
      CASE
        WHEN posted_at IS NULL THEN NULL
        ELSE CAST(
          FLOOR(TIMESTAMP_DIFF(processed_at, posted_at, SECOND) / 86400.0)
          AS INT64
        )
      END AS age_days
    FROM parsed
  ),
  components AS (
    SELECT
      *,
      (
        IF(NULLIF(TRIM(job_id), '') IS NOT NULL, 10, 0)
        + IF(NULLIF(TRIM(title), '') IS NOT NULL, 10, 0)
        + IF(NULLIF(TRIM(company), '') IS NOT NULL, 8, 0)
        + IF(NULLIF(TRIM(city), '') IS NOT NULL, 6, 0)
        + IF(NULLIF(TRIM(province), '') IS NOT NULL, 4, 0)
        + IF(NULLIF(TRIM(country), '') IS NOT NULL, 4, 0)
        + IF(NULLIF(TRIM(posted_date), '') IS NOT NULL, 4, 0)
        + IF(NULLIF(TRIM(description), '') IS NOT NULL, 4, 0)
      ) AS completeness_points,
      (
        IF(posted_at IS NOT NULL, 8, 0)
        + IF(posted_at IS NOT NULL AND age_days >= -1, 4, 0)
        + CASE
            WHEN salary_min IS NOT NULL
              AND salary_max IS NOT NULL
              AND salary_min > salary_max THEN 0
            WHEN salary_min < 30000 OR salary_max > 300000 THEN 3
            ELSE 6
          END
        + IF(
            REGEXP_CONTAINS(IFNULL(job_url, ''), r'(?i)^https?://[^/\s]+'),
            6,
            0
          )
        + IF(NULLIF(TRIM(source), '') IS NOT NULL, 6, 0)
      ) AS validity_points,
      CASE
        WHEN age_days IS NULL OR age_days < -1 THEN 0
        WHEN age_days <= 30 THEN 20
        WHEN age_days <= 60 THEN 16
        WHEN age_days <= 90 THEN 12
        WHEN age_days <= 180 THEN 6
        ELSE 0
      END AS timeliness_points
    FROM aged
  ),
  flagged AS (
    SELECT
      *,
      ARRAY_CONCAT(
        IF(
          NULLIF(TRIM(job_id), '') IS NULL
            OR NULLIF(TRIM(title), '') IS NULL,
          ['MISSING_CRITICAL_FIELD'],
          ARRAY<STRING>[]
        ),
        IF(
          NULLIF(TRIM(posted_date), '') IS NOT NULL AND posted_at IS NULL,
          ['INVALID_POSTED_DATE'],
          ARRAY<STRING>[]
        ),
        IF(posted_at IS NOT NULL AND age_days < -1,
          ['FUTURE_POSTED_DATE'], ARRAY<STRING>[]),
        IF(
          salary_min IS NOT NULL
            AND salary_max IS NOT NULL
            AND salary_min > salary_max,
          ['INVALID_SALARY_RANGE'],
          ARRAY<STRING>[]
        ),
        IF(salary_min IS NOT NULL AND salary_min < 30000,
          ['LOW_SALARY_OUTLIER'], ARRAY<STRING>[]),
        IF(salary_max IS NOT NULL AND salary_max > 300000,
          ['HIGH_SALARY_OUTLIER'], ARRAY<STRING>[]),
        IF(
          NOT REGEXP_CONTAINS(
            IFNULL(job_url, ''),
            r'(?i)^https?://[^/\s]+'
          ),
          ['INVALID_JOB_URL'],
          ARRAY<STRING>[]
        ),
        IF(NULLIF(TRIM(source), '') IS NULL,
          ['MISSING_SOURCE'], ARRAY<STRING>[]),
        IF(age_days > 90, ['STALE_JOB'], ARRAY<STRING>[])
      ) AS quality_flags
    FROM components
  ),
  scored AS (
    SELECT
      *,
      CAST(
        completeness_points + validity_points + timeliness_points
        AS FLOAT64
      ) AS quality_score
    FROM flagged
  )
  SELECT
    job_id,
    title,
    company,
    city,
    province,
    country,
    posted_date,
    salary_min,
    salary_max,
    description,
    category,
    contract_type,
    source,
    job_url,
    run_id,
    ROUND(quality_score, 2) AS quality_score,
    CASE
      WHEN quality_score >= 80 THEN 'PASS'
      WHEN quality_score >= 60 THEN 'REVIEW'
      ELSE 'FAIL'
    END AS quality_status,
    quality_flags,
    (
      quality_score >= publish_threshold
      AND NOT IFNULL(age_days > 180, FALSE)
      AND NOT EXISTS (
        SELECT 1
        FROM UNNEST(quality_flags) AS flag
        WHERE flag IN (
          'MISSING_CRITICAL_FIELD',
          'INVALID_POSTED_DATE',
          'FUTURE_POSTED_DATE',
          'INVALID_SALARY_RANGE'
        )
      )
    ) AS is_publishable,
    completeness_points,
    validity_points,
    timeliness_points,
    age_days
  FROM scored
);
