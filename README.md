# Job Market Data Pipeline

This project extracts Toronto job postings from the Adzuna Jobs API and stores
them in BigQuery. The active architecture is warehouse-native ELT: Python (and
the Cloud Run Job that hosts it) performs ingestion only, while BigQuery owns
deduplication, cleaning, quality scoring, current/history maintenance, and the
publish gate.

The migration reduces Python/Cloud Run transformation work. It does not imply
automatic cost savings: BigQuery queries must remain scoped to one `run_id`.

## Architecture

```text
Adzuna API
    -> Python pagination and provenance
    -> BigQuery raw_jobs (append-only)
    -> extract_status = RAW_LOADED; Cloud Run ends

manual/future orchestration trigger
    -> CALL job_market.process_job_run(run_id)
    -> BigQuery deduplication and Toronto normalization
    -> row and run data-quality calculations
    -> curated_jobs + jobs_current
    -> job_observations + jobs_state
    -> published_jobs view
    -> transform_status = SUCCESS
```

`python src/pipeline.py` no longer runs Python business transformations. It
generates one UUID, calls Adzuna sequentially, writes the local transient RAW
file, appends it to BigQuery, records `RAW_LOADED`, and exits. A successful
Cloud Run execution therefore means ingestion succeeded; it does not mean the
warehouse transformation succeeded.

The stable Python transformation modules remain in `src/` for migration
comparison and rollback analysis, but they are not called by the active path.

## Ingestion and RAW

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

Pages are requested sequentially. Pagination stops at `max_pages`, an empty
later page, or a page smaller than `results_per_page`. Any requested-page
failure fails the entire ingestion; a partial result is never marked
`RAW_LOADED`.

`raw_jobs` remains append-only and keeps its legacy columns. Additive ELT
provenance columns are:

- `source_job_id`
- `page_number`
- `position_in_page`
- `search_role`
- `search_location`
- `raw_payload` as BigQuery `JSON`

Every source result is retained, including repeated Adzuna IDs across pages.
Cross-page deduplication no longer occurs before RAW persistence. The source
payload is preserved except that client-attribution query data is removed from
redirect URLs so local credential identifiers are not persisted.

The Cloud Run filesystem is ephemeral. `data/raw_jobs.json` is a transient
staging artifact; BigQuery is the persistent RAW layer.

## BigQuery transformation

Repository SQL is organized as:

```text
sql/
  setup/001_elt_resources.sql
  routines/job_run_rows.sql
  routines/process_job_run.sql
  views/published_jobs.sql
  tests/job_quality_assertions.sql
```

`job_run_rows` is a parameterized table function used for shadow parity and by
the stored procedure. `process_job_run` is the central warehouse API:

```sql
CALL `weekly-market-trend.job_market.process_job_run`('<run-id>');
```

For the specified run only, it:

1. validates exactly one run-control record, `RAW_LOADED` extraction, a
   non-empty RAW batch, and agreement between recorded and actual RAW counts;
2. counts RAW rows, unique source IDs, and upstream duplicate rows;
3. deterministically deduplicates source IDs by page, position, and ingestion
   time;
4. reads source values from `raw_payload`, with legacy RAW-column fallbacks;
5. recognizes and normalizes exact Toronto components;
6. calculates row scores, flags, status, and publishability;
7. transactionally replaces `curated_jobs` and `jobs_current` current
   snapshots;
8. replaces only the same run's `job_observations`, making retries idempotent;
9. merges identified jobs into `jobs_state`;
10. replaces only the same run's `data_quality_runs` record; and
11. records transformation counts and `SUCCESS` in `job_run_control`.

If transformation fails, its transaction is rolled back, RAW is retained, and
the control record becomes `TRANSFORM_FAILED`. The same RAW run can be retried.
The original `transform_started_at` is reused on retry, so observation and
state timestamps do not drift.

## Toronto normalization

Structured `location.area` is preferred. An exact `Toronto` or
`City of Toronto` hierarchy component normalizes to:

```text
city = Toronto
province = Ontario
country = Canada
```

Exact comma-separated display components are the legacy-data fallback. This
handles Toronto, North York, Etobicoke, Toronto Dominion Centre, Harbourfront,
and Union Station when the source hierarchy identifies Toronto. It does not
use substring or proximity matching, and it does not broaden the search to
Mississauga, Brampton, Markham, Vaughan, or Richmond Hill.

## Data quality and publish gate

The stable Python scoring formula is reproduced in SQL.

Completeness contributes 50 points: `job_id` 10, `title` 10, `company` 8,
`city` 6, `province` 4, `country` 4, `posted_date` 4, and `description` 4.

Validity contributes 30 points: parseable date 8, date no more than one day in
the future 4, salary validity 6, usable HTTP/HTTPS URL 6, and populated source
6. Missing salary still receives all six salary-validity points. A suspicious
salary receives three; an invalid min/max range receives zero.

Timeliness contributes 20 points for 0–30 days, 16 for 31–60, 12 for 61–90,
6 for 91–180, and 0 beyond 180 days or for an unreasonable future/invalid
date.

Statuses remain:

- `PASS`: score >= 80
- `REVIEW`: score >= 60 and < 80
- `FAIL`: score < 60

The default publish threshold is 80. A row publishes only when it reaches the
threshold, has no hard-failure flag, and is no more than 180 days old. The
hard flags are `MISSING_CRITICAL_FIELD`, `INVALID_POSTED_DATE`,
`FUTURE_POSTED_DATE`, and `INVALID_SALARY_RANGE`. A row older than 180 days
stays in `curated_jobs`, keeps `STALE_JOB`, and can retain `PASS`; the age rule
does not alter its score.

Run-level completeness, validity, uniqueness, and timeliness percentages are
calculated in BigQuery. The overall score remains:

```text
completeness * 40%
+ validity * 30%
+ uniqueness * 15%
+ timeliness * 15%
```

Uniqueness now measures the upstream RAW observations before SQL deduplication,
which is an intentional ELT observability improvement.

## Warehouse resources and semantics

- `raw_jobs`: append-only source history with `run_id` lineage
- `curated_jobs`: current scored snapshot
- `published_jobs`: view over publishable curated rows
- `jobs_current`: current cleaned snapshot
- `job_observations`: append-only across runs and retry-safe within a run
- `jobs_state`: one state row per identified job
- `pipeline_runs`: append-only ingestion execution log
- `data_quality_runs`: one retry-safe quality record per transformed run
- `job_run_control`: separate extraction/transformation lifecycle

`jobs_state.first_seen_at` is preserved for existing IDs; `last_seen_at` is
updated when the current run sees an ID. Missing jobs are not automatically
deactivated because absence from the configured Adzuna pages is not proof that
a job is inactive.

Run-control statuses are separate:

```text
EXTRACTING -> RAW_LOADED
                    -> TRANSFORMING -> SUCCESS
EXTRACT_FAILED         TRANSFORM_FAILED
```

`job_run_control` is partitioned by `DATE(started_at)` and clustered by
`run_id`, `extract_status`, and `transform_status`.

## Cost controls

Every RAW read in the transformation includes `WHERE run_id = requested_run_id`.
The existing production tables were unpartitioned and unclustered, and this
migration does not destructively recreate them. Consequently BigQuery may
still scan more storage than ideal even with run predicates. A future table
migration should consider:

```sql
PARTITION BY DATE(ingested_at)
CLUSTER BY run_id, source_job_id
```

for RAW, plus an appropriate append-oriented curated design if warehouse
semantics are later redesigned. That physical migration is intentionally not
performed here.

## Configuration and local credentials

Create an ignored `.env` file in the project root:

```dotenv
ADZUNA_APP_ID=your_app_id
ADZUNA_APP_KEY=your_app_key
# Optional; defaults to 80
QUALITY_PUBLISH_THRESHOLD=80
```

BigQuery uses Application Default Credentials locally. Cloud Run continues to
use its runtime service account. API credentials must not be committed, logged,
or placed in SQL.

## Install and run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
gcloud auth application-default login
```

Install or update the additive schema, routines, and publish view:

```powershell
.\.venv\Scripts\python.exe src\install_elt_sql.py
```

Run ingestion only:

```powershell
.\.venv\Scripts\python.exe src\pipeline.py
```

Copy the printed run ID, then transform it with either BigQuery SQL:

```sql
CALL `weekly-market-trend.job_market.process_job_run`('<run-id>');
```

or the optional local manual wrapper:

```powershell
.\.venv\Scripts\python.exe src\run_elt_transform.py <run-id>
```

The wrapper submits only the single warehouse routine; it does not execute
business transformations in Python and is not called by the active ingestion
path.

Run tests and parity validation:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe src\validate_elt_parity.py <captured-stable-run-id>
```

Build the Cloud Run-compatible Linux container locally:

```powershell
docker build -t job-market-pipeline .
```

## Future orchestration (not deployed)

No Scheduler, IAM, service-account, Secret Manager, or Cloud Run configuration
is created by this repository change.

Two future trigger designs are supported conceptually:

1. After RAW load, Cloud Run submits one BigQuery job containing only
   `CALL process_job_run(run_id)`. This avoids a timing race and starts promptly
   while keeping all transformation compute inside BigQuery.
2. A BigQuery Scheduled Query finds `RAW_LOADED`/`PENDING` runs and calls the
   procedure. This separates ingestion and warehouse scheduling but adds
   polling latency, locking, and a second scheduler configuration.

The first option is recommended because it provides one event-driven chain
without moving transformation logic back into Cloud Run. It is intentionally
disabled until deployment/orchestration work is separately authorized.

## Known limitations

- `max_pages` limits source coverage; this is not complete Toronto-market data.
- Adzuna ranking changes can move jobs outside the configured pages.
- Salary and contract type coverage are source-limited.
- Existing production data tables remain unpartitioned/unclustered.
- Absence does not trigger `is_active = FALSE`.
- Current-snapshot table semantics are preserved rather than redesigned.
- Manual operators must avoid transforming older runs out of order; future
  automation should claim pending runs and serialize current-snapshot writes.
- Scheduler/orchestration and downstream BI integration are not deployed.
