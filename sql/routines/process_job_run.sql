CREATE OR REPLACE PROCEDURE `weekly-market-trend.job_market.process_job_run`(
  requested_run_id STRING
)
BEGIN
  DECLARE control_rows INT64 DEFAULT 0;
  DECLARE recorded_raw_count INT64;
  DECLARE actual_raw_count INT64 DEFAULT 0;
  DECLARE raw_source_id_count INT64 DEFAULT 0;
  DECLARE raw_unique_job_ids INT64 DEFAULT 0;
  DECLARE duplicate_source_rows INT64 DEFAULT 0;
  DECLARE transformed_curated_count INT64 DEFAULT 0;
  DECLARE transformed_published_count INT64 DEFAULT 0;
  DECLARE processed_at TIMESTAMP;
  DECLARE configured_publish_threshold FLOAT64 DEFAULT 80.0;
  DECLARE failure_message STRING;
  DECLARE transaction_open BOOL DEFAULT FALSE;
  DECLARE requested_started_at TIMESTAMP;
  DECLARE latest_success_started_at TIMESTAMP;
  DECLARE latest_success_run_id STRING;

  BEGIN
    SET control_rows = (
      SELECT COUNT(*)
      FROM `weekly-market-trend.job_market.job_run_control`
      WHERE run_id = requested_run_id
    );
    ASSERT requested_run_id IS NOT NULL AND TRIM(requested_run_id) != ''
      AS 'run_id must be populated';
    ASSERT control_rows = 1
      AS 'run_id must identify exactly one run-control row';
    ASSERT (
      SELECT extract_status = 'RAW_LOADED'
      FROM `weekly-market-trend.job_market.job_run_control`
      WHERE run_id = requested_run_id
    ) AS 'run extraction status must be RAW_LOADED';

    SET requested_started_at = (
      SELECT started_at
      FROM `weekly-market-trend.job_market.job_run_control`
      WHERE run_id = requested_run_id
    );
    SET (
      latest_success_run_id,
      latest_success_started_at
    ) = (
      SELECT AS STRUCT run_id, started_at
      FROM `weekly-market-trend.job_market.job_run_control`
      WHERE transform_status = 'SUCCESS'
        AND curated_count IS NOT NULL
      ORDER BY started_at DESC, run_id DESC
      LIMIT 1
    );
    ASSERT
      latest_success_run_id IS NULL
      OR requested_run_id = latest_success_run_id
      OR requested_started_at > latest_success_started_at
      OR (
        requested_started_at = latest_success_started_at
        AND requested_run_id > latest_success_run_id
      )
      AS 'run is older than the latest successful current-producing run';

    SET recorded_raw_count = (
      SELECT raw_count
      FROM `weekly-market-trend.job_market.job_run_control`
      WHERE run_id = requested_run_id
    );
    SET processed_at = (
      SELECT COALESCE(transform_started_at, CURRENT_TIMESTAMP())
      FROM `weekly-market-trend.job_market.job_run_control`
      WHERE run_id = requested_run_id
    );
    SET configured_publish_threshold = (
      SELECT COALESCE(publish_threshold, 80.0)
      FROM `weekly-market-trend.job_market.job_run_control`
      WHERE run_id = requested_run_id
    );
    ASSERT configured_publish_threshold BETWEEN 0 AND 100
      AS 'publish threshold must be between 0 and 100';

    SET (
      actual_raw_count,
      raw_source_id_count,
      raw_unique_job_ids
    ) = (
      SELECT AS STRUCT
        COUNT(*),
        COUNTIF(
          COALESCE(
            NULLIF(source_job_id, ''),
            NULLIF(job_id, ''),
            NULLIF(JSON_VALUE(raw_payload, '$.id'), '')
          ) IS NOT NULL
        ),
        COUNT(DISTINCT COALESCE(
          NULLIF(source_job_id, ''),
          NULLIF(job_id, ''),
          NULLIF(JSON_VALUE(raw_payload, '$.id'), '')
        ))
      FROM `weekly-market-trend.job_market.raw_jobs`
      WHERE run_id = requested_run_id
    );
    SET duplicate_source_rows = raw_source_id_count - raw_unique_job_ids;

    ASSERT recorded_raw_count IS NOT NULL
      AS 'run-control raw_count must be populated';
    ASSERT actual_raw_count > 0 AS 'RAW batch must contain at least one row';
    ASSERT recorded_raw_count = actual_raw_count
      AS 'RAW batch count does not match run-control raw_count';

    UPDATE `weekly-market-trend.job_market.job_run_control`
    SET transform_status = 'TRANSFORMING',
        transform_started_at = processed_at,
        transform_finished_at = NULL,
        curated_count = NULL,
        published_count = NULL,
        error_message = NULL
    WHERE run_id = requested_run_id;

    CREATE TEMP TABLE transformed_rows AS
    SELECT *
    FROM `weekly-market-trend.job_market.job_run_rows`(
      requested_run_id,
      processed_at,
      configured_publish_threshold
    );

    SET transformed_curated_count = (SELECT COUNT(*) FROM transformed_rows);
    SET transformed_published_count = (
      SELECT COUNTIF(is_publishable)
      FROM transformed_rows
    );
    ASSERT transformed_curated_count > 0
      AS 'RAW batch produced no Toronto curated rows';

    BEGIN TRANSACTION;
    SET transaction_open = TRUE;

    DELETE FROM `weekly-market-trend.job_market.curated_jobs` WHERE TRUE;
    INSERT INTO `weekly-market-trend.job_market.curated_jobs` (
      job_id, title, company, city, province, country, posted_date,
      salary_min, salary_max, description, category, contract_type,
      source, job_url, run_id, quality_score, quality_status,
      quality_flags, is_publishable
    )
    SELECT
      job_id, title, company, city, province, country, posted_date,
      salary_min, salary_max, description, category, contract_type,
      source, job_url, run_id, quality_score, quality_status,
      quality_flags, is_publishable
    FROM transformed_rows;

    DELETE FROM `weekly-market-trend.job_market.jobs_current` WHERE TRUE;
    INSERT INTO `weekly-market-trend.job_market.jobs_current` (
      job_id, title, company, city, province, country, posted_date,
      salary_min, salary_max, description, category, contract_type,
      source, job_url
    )
    SELECT
      job_id, title, company, city, province, country, posted_date,
      salary_min, salary_max, description, category, contract_type,
      source, job_url
    FROM transformed_rows;

    -- Replacing this run's observations is append-history preserving and retry-safe.
    DELETE FROM `weekly-market-trend.job_market.job_observations`
    WHERE run_id = requested_run_id;
    INSERT INTO `weekly-market-trend.job_market.job_observations` (
      run_id, observed_at, job_id, title, company, city, province, country,
      posted_date, salary_min, salary_max, description, category,
      contract_type, source, job_url
    )
    SELECT
      run_id, processed_at, job_id, title, company, city, province, country,
      posted_date, salary_min, salary_max, description, category,
      contract_type, source, job_url
    FROM transformed_rows;

    MERGE `weekly-market-trend.job_market.jobs_state` AS target
    USING (
      SELECT *
      FROM transformed_rows
      WHERE job_id IS NOT NULL AND TRIM(job_id) != ''
    ) AS source
    ON target.job_id = source.job_id
    WHEN MATCHED THEN UPDATE SET
      title = source.title,
      company = source.company,
      city = source.city,
      province = source.province,
      country = source.country,
      posted_date = source.posted_date,
      salary_min = source.salary_min,
      salary_max = source.salary_max,
      description = source.description,
      category = source.category,
      contract_type = source.contract_type,
      source = source.source,
      job_url = source.job_url,
      last_seen_at = processed_at,
      is_active = TRUE
    WHEN NOT MATCHED THEN INSERT (
      job_id, title, company, city, province, country, posted_date,
      salary_min, salary_max, description, category, contract_type,
      source, job_url, first_seen_at, last_seen_at, is_active
    ) VALUES (
      source.job_id, source.title, source.company, source.city,
      source.province, source.country, source.posted_date, source.salary_min,
      source.salary_max, source.description, source.category,
      source.contract_type, source.source, source.job_url,
      processed_at, processed_at, TRUE
    );

    DELETE FROM `weekly-market-trend.job_market.data_quality_runs`
    WHERE run_id = requested_run_id;
    INSERT INTO `weekly-market-trend.job_market.data_quality_runs` (
      run_id, checked_at, total_jobs, unique_job_ids, duplicate_job_ids,
      missing_job_id, missing_title, missing_company, missing_city,
      missing_posted_date, salary_coverage_count, salary_coverage_pct,
      contract_type_coverage_count, contract_type_coverage_pct,
      low_salary_candidates, high_salary_candidates, invalid_salary_ranges,
      stale_jobs, stale_jobs_pct, invalid_posted_dates, future_posted_dates,
      completeness_score, validity_score, uniqueness_score,
      timeliness_score, overall_quality_score, quality_status,
      publish_threshold, publishable_jobs, raw_row_count,
      raw_unique_job_ids
    )
    WITH metrics AS (
      SELECT
        COUNT(*) AS total_jobs,
        COUNT(DISTINCT job_id) AS unique_job_ids,
        COUNTIF(job_id IS NULL OR TRIM(job_id) = '') AS missing_job_id,
        COUNTIF(title IS NULL OR TRIM(title) = '') AS missing_title,
        COUNTIF(company IS NULL OR TRIM(company) = '') AS missing_company,
        COUNTIF(city IS NULL OR TRIM(city) = '') AS missing_city,
        COUNTIF(posted_date IS NULL OR TRIM(posted_date) = '')
          AS missing_posted_date,
        COUNTIF(salary_min IS NOT NULL OR salary_max IS NOT NULL)
          AS salary_coverage_count,
        COUNTIF(contract_type IS NOT NULL AND TRIM(contract_type) != '')
          AS contract_type_coverage_count,
        COUNTIF('LOW_SALARY_OUTLIER' IN UNNEST(quality_flags))
          AS low_salary_candidates,
        COUNTIF('HIGH_SALARY_OUTLIER' IN UNNEST(quality_flags))
          AS high_salary_candidates,
        COUNTIF('INVALID_SALARY_RANGE' IN UNNEST(quality_flags))
          AS invalid_salary_ranges,
        COUNTIF('STALE_JOB' IN UNNEST(quality_flags)) AS stale_jobs,
        COUNTIF('INVALID_POSTED_DATE' IN UNNEST(quality_flags))
          AS invalid_posted_dates,
        COUNTIF('FUTURE_POSTED_DATE' IN UNNEST(quality_flags))
          AS future_posted_dates,
        ROUND(SAFE_DIVIDE(SUM(completeness_points), COUNT(*) * 50) * 100, 2)
          AS completeness_score,
        ROUND(SAFE_DIVIDE(SUM(validity_points), COUNT(*) * 30) * 100, 2)
          AS validity_score,
        ROUND(SAFE_DIVIDE(SUM(timeliness_points), COUNT(*) * 20) * 100, 2)
          AS timeliness_score,
        COUNTIF(is_publishable) AS publishable_jobs
      FROM transformed_rows
    ), scored_metrics AS (
      SELECT
        *,
        ROUND(
          SAFE_DIVIDE(actual_raw_count - duplicate_source_rows,
            actual_raw_count) * 100,
          2
        ) AS uniqueness_score
      FROM metrics
    ), final_metrics AS (
      SELECT
        *,
        ROUND(
          completeness_score * 0.40
          + validity_score * 0.30
          + uniqueness_score * 0.15
          + timeliness_score * 0.15,
          2
        ) AS overall_quality_score
      FROM scored_metrics
    )
    SELECT
      requested_run_id,
      processed_at,
      total_jobs,
      unique_job_ids,
      duplicate_source_rows,
      missing_job_id,
      missing_title,
      missing_company,
      missing_city,
      missing_posted_date,
      salary_coverage_count,
      ROUND(SAFE_DIVIDE(salary_coverage_count, total_jobs) * 100, 2),
      contract_type_coverage_count,
      ROUND(SAFE_DIVIDE(contract_type_coverage_count, total_jobs) * 100, 2),
      low_salary_candidates,
      high_salary_candidates,
      invalid_salary_ranges,
      stale_jobs,
      ROUND(SAFE_DIVIDE(stale_jobs, total_jobs) * 100, 2),
      invalid_posted_dates,
      future_posted_dates,
      completeness_score,
      validity_score,
      uniqueness_score,
      timeliness_score,
      overall_quality_score,
      CASE
        WHEN overall_quality_score >= 80 THEN 'PASS'
        WHEN overall_quality_score >= 60 THEN 'REVIEW'
        ELSE 'FAIL'
      END,
      configured_publish_threshold,
      publishable_jobs,
      actual_raw_count,
      raw_unique_job_ids
    FROM final_metrics;

    UPDATE `weekly-market-trend.job_market.job_run_control`
    SET transform_status = 'SUCCESS',
        transform_finished_at = CURRENT_TIMESTAMP(),
        curated_count = transformed_curated_count,
        published_count = transformed_published_count,
        error_message = NULL
    WHERE run_id = requested_run_id;

    COMMIT TRANSACTION;
    SET transaction_open = FALSE;
  EXCEPTION WHEN ERROR THEN
    IF transaction_open THEN
      ROLLBACK TRANSACTION;
      SET transaction_open = FALSE;
    END IF;
    IF @@error.message IS NOT NULL THEN
      SET failure_message = SUBSTR(@@error.message, 1, 1024);
    ELSE
      SET failure_message = 'Unknown BigQuery transformation error';
    END IF;

    IF control_rows = 1 THEN
      UPDATE `weekly-market-trend.job_market.job_run_control`
      SET transform_status = 'TRANSFORM_FAILED',
          transform_finished_at = CURRENT_TIMESTAMP(),
          error_message = failure_message
      WHERE run_id = requested_run_id;
    END IF;
    RAISE;
  END;
END;
