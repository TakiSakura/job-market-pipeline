CREATE TABLE IF NOT EXISTS `weekly-market-trend.job_market.job_run_control` (
  run_id STRING NOT NULL,
  extract_status STRING NOT NULL,
  transform_status STRING NOT NULL,
  started_at TIMESTAMP NOT NULL,
  raw_loaded_at TIMESTAMP,
  transform_started_at TIMESTAMP,
  transform_finished_at TIMESTAMP,
  raw_count INT64,
  curated_count INT64,
  published_count INT64,
  transform_job_id STRING,
  error_message STRING,
  publish_threshold FLOAT64
)
PARTITION BY DATE(started_at)
CLUSTER BY run_id, extract_status, transform_status;

ALTER TABLE `weekly-market-trend.job_market.raw_jobs`
ADD COLUMN IF NOT EXISTS source_job_id STRING;

ALTER TABLE `weekly-market-trend.job_market.raw_jobs`
ADD COLUMN IF NOT EXISTS page_number INT64;

ALTER TABLE `weekly-market-trend.job_market.raw_jobs`
ADD COLUMN IF NOT EXISTS position_in_page INT64;

ALTER TABLE `weekly-market-trend.job_market.raw_jobs`
ADD COLUMN IF NOT EXISTS search_role STRING;

ALTER TABLE `weekly-market-trend.job_market.raw_jobs`
ADD COLUMN IF NOT EXISTS search_location STRING;

ALTER TABLE `weekly-market-trend.job_market.raw_jobs`
ADD COLUMN IF NOT EXISTS raw_payload JSON;

ALTER TABLE `weekly-market-trend.job_market.data_quality_runs`
ADD COLUMN IF NOT EXISTS raw_row_count INT64;

ALTER TABLE `weekly-market-trend.job_market.data_quality_runs`
ADD COLUMN IF NOT EXISTS raw_unique_job_ids INT64;

ALTER TABLE `weekly-market-trend.job_market.job_run_control`
ADD COLUMN IF NOT EXISTS publish_threshold FLOAT64;
