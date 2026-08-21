CREATE OR REPLACE VIEW `weekly-market-trend.job_market.published_jobs` AS
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
  quality_score,
  quality_status,
  quality_flags,
  is_publishable
FROM `weekly-market-trend.job_market.curated_jobs`
WHERE is_publishable = TRUE;
