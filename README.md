# Job Market Data Pipeline

A Python data pipeline that extracts Toronto job postings from the Adzuna Jobs API, validates and scores them, and persists raw, curated, published, historical, and monitoring data in BigQuery.

## Architecture

```text
Adzuna API
    -> RAW layer
    -> Cleaning and data quality scoring
    -> CURATED layer
    -> Quality gate
    -> PUBLISH layer
    -> Power BI / downstream analytics (planned consumer)
```

The pipeline entry point remains `python src/pipeline.py`. It runs in this order:

```text
EXTRACT
  -> BIGQUERY RAW
  -> CLEAN
  -> DATA QUALITY / SCORING
  -> BIGQUERY CURATED
  -> BIGQUERY CURRENT
  -> BIGQUERY OBSERVATIONS
  -> BIGQUERY STATE
  -> RUN LOG
```

The orchestrator generates one UUID and passes it to downstream steps as `PIPELINE_RUN_ID`, allowing raw, curated, quality, observation, and monitoring records to be traced to the same execution.

## Adzuna Pagination

Extraction fetches pages sequentially using the configured page size and maximum page count. The current configuration requests up to three pages of 50 results each:

```json
{
  "results_per_page": 50,
  "max_pages": 3
}
```

Pagination stops when any of these occurs:

- an empty page is returned after at least one successful page
- a page contains fewer rows than `results_per_page`
- `max_pages` is reached

Results from all fetched pages are combined and deduplicated by Adzuna `job_id`. Logs report pages fetched, rows before deduplication, unique rows, and duplicates removed. Any HTTP, timeout, or response failure on any requested page fails extraction, and no partial batch is written as a successful current snapshot.

The page limit controls API usage and should remain conservative because Adzuna applies rate limits. Setting `max_pages` to `1` preserves single-page behavior.

## Toronto Location Normalization

The raw layer preserves both Adzuna's location display name and its structured `location.area` hierarchy. Cleaning checks the structured hierarchy first, then exact comma-separated display-name components.

Locations containing an exact `Toronto` or `City of Toronto` component are normalized to:

```text
city = Toronto
province = Ontario
country = Canada
```

This includes Toronto, North York, Etobicoke, Toronto Dominion Centre, Harbourfront, and Union Station when the structured hierarchy or display components identify them as Toronto. It does not use broad substring or proximity matching, so municipalities such as Mississauga, Brampton, Markham, Vaughan, and Richmond Hill are not included merely because they are in the GTA.

## Data Layers

### RAW

`job_market.raw_jobs` is an append-only snapshot history of the normalized Adzuna extraction output. Each row includes:

- `run_id`
- `ingested_at`
- the fields stored in transient `data/raw_jobs.json`

The Cloud Run filesystem is ephemeral; BigQuery is the persistent raw layer.

### CURATED

`job_market.curated_jobs` contains the current cleaned snapshot plus:

- `run_id`
- `quality_score`
- `quality_status`
- `quality_flags` as a repeated string field
- `is_publishable`

All clean rows are retained, including rows that fail the publish gate. This MVP uses `WRITE_TRUNCATE` because historical snapshots already exist in `raw_jobs` and `job_observations`.

### PUBLISH

`job_market.published_jobs` is a BigQuery view over `curated_jobs`:

```sql
SELECT *
FROM `weekly-market-trend.job_market.curated_jobs`
WHERE is_publishable = TRUE
```

The curated loader creates the view when missing and updates it only when its definition changes. Power BI is not implemented by this repository; it can later connect to this view.

## Row-Level Data Quality Score

Each curated job receives an explainable score from 0 to 100.

Completeness — 50 points:

| Field | Points |
|---|---:|
| `job_id` | 10 |
| `title` | 10 |
| `company` | 8 |
| `city` | 6 |
| `province` | 4 |
| `country` | 4 |
| `posted_date` | 4 |
| `description` | 4 |

Validity — 30 points:

- parseable posted date: 8
- posted date not more than one day in the future: 4
- valid salary when supplied: 6; suspicious salary receives 3; invalid range receives 0; no salary receives all 6
- usable HTTP/HTTPS job URL: 6
- populated source: 6

Timeliness — 20 points:

- 0–30 days old: 20
- 31–60 days: 16
- 61–90 days: 12
- 91–180 days: 6
- over 180 days, invalid date, or unreasonable future date: 0

Jobs older than 90 days receive `STALE_JOB`. Other flags include:

- `LOW_SALARY_OUTLIER`
- `HIGH_SALARY_OUTLIER`
- `INVALID_SALARY_RANGE`
- `INVALID_POSTED_DATE`
- `FUTURE_POSTED_DATE`
- `MISSING_CRITICAL_FIELD`
- `INVALID_JOB_URL`
- `MISSING_SOURCE`

Quality status is numeric:

- `PASS`: score >= 80
- `REVIEW`: score >= 60 and < 80
- `FAIL`: score < 60

The publish threshold defaults to 80 and can be configured with `QUALITY_PUBLISH_THRESHOLD`. A row is publishable only when its score meets the configured threshold, it is no more than 180 days old, and it has none of these hard-failure flags:

- `MISSING_CRITICAL_FIELD`
- `INVALID_POSTED_DATE`
- `FUTURE_POSTED_DATE`
- `INVALID_SALARY_RANGE`

The 180-day rule is a hard publish gate only. Jobs older than 180 days remain in `curated_jobs`, retain the `STALE_JOB` flag, and keep the same quality score produced by the scoring formula.

## Run-Level Data Quality Score

Every relevant run appends a report to `job_market.data_quality_runs`. Component scores are derived from the current batch:

- completeness: average earned row completeness points / 50
- validity: average earned row validity points / 30
- uniqueness: `(total rows - duplicate job IDs) / total rows`
- timeliness: average earned row timeliness points / 20

The overall score is:

```text
completeness * 40%
+ validity * 30%
+ uniqueness * 15%
+ timeliness * 15%
```

The report retains the underlying counts and coverage metrics, including duplicates, missing core values, salary anomalies, invalid dates/ranges, stale jobs, salary coverage, and contract-type coverage.

Missing salary and contract type are monitored rather than treated as hard failures because Adzuna frequently omits them. Suspicious salary values are still flagged and reduce validity.

## Existing BigQuery Tables

- `jobs_current`: current clean snapshot, still replaced on each successful current load
- `job_observations`: append-only observations; new rows include `run_id`
- `jobs_state`: MERGE by `job_id`; preserves `first_seen_at`, updates `last_seen_at`, and does not deactivate absent jobs
- `pipeline_runs`: append-only execution monitoring
- `data_quality_runs`: append-only batch quality reports, now including `run_id` and component scores
- `raw_jobs`: append-only raw snapshots
- `curated_jobs`: current quality-scored snapshot
- `published_jobs`: view exposing publishable curated rows

## Configuration

Search settings are in `config/search_config.json`:

```json
{
  "country": "Canada",
  "location": "Toronto",
  "role": "Data Analyst",
  "results_per_page": 50,
  "max_pages": 3
}
```

Local credentials belong in an ignored `.env` file:

```dotenv
ADZUNA_APP_ID=your_app_id
ADZUNA_APP_KEY=your_app_key
```

Optional quality configuration:

```dotenv
QUALITY_PUBLISH_THRESHOLD=80
```

BigQuery uses Application Default Credentials. No API credentials are stored in source code or BigQuery job URLs.

## Run Locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
.\.venv\Scripts\python.exe src\pipeline.py
```

Run unit tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Build the Linux container used by Cloud Run Jobs:

```powershell
docker build -t job-market-pipeline .
```

The container continues to use `python:3.14-slim` and starts with `python src/pipeline.py`.

## Known Limitations

- Extraction is capped by configurable `max_pages`; pagination improves coverage but does not guarantee every matching Adzuna posting or complete Toronto market coverage.
- Toronto normalization recognizes structured Toronto sublocations but intentionally does not expand the search to the broader GTA.
- Search ranking and upstream result changes can still move jobs beyond the configured page limit.
- Absence from a later run does not prove a job is inactive, so the state MERGE does not set missing jobs to `is_active = false`.
- Pipeline retries remain disabled because append operations are not fully idempotent.
- Salary and contract type have limited source coverage.
- Cloud Scheduler setup and Power BI integration are not part of the current implementation.

## Google Cloud

- Project: `weekly-market-trend`
- Dataset: `weekly-market-trend.job_market`
- Dataset and Cloud Run region: `northamerica-northeast2`
- Cloud Run Job: `job-market-pipeline`

This repository does not create or modify IAM, service accounts, Cloud Scheduler, Cloud Run configuration, Secret Manager, or Artifact Registry permissions.
