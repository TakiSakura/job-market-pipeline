# Job Market Data Pipeline

This project extracts Toronto job postings from the Adzuna Jobs API and stores them in BigQuery. The active architecture is warehouse-native ELT: Python and the Cloud Run Job perform ingestion and lightweight orchestration only, while BigQuery owns deduplication, cleaning, quality scoring, current/history maintenance, and the publish gate.

## Architecture

```text
Cloud Scheduler (planned)
    -> Cloud Run Job
    -> Adzuna API
    -> Python pagination and provenance
    -> BigQuery raw_jobs (append-only)
    -> extract_status = RAW_LOADED
    -> optionally submit one asynchronous BigQuery CALL
    -> Cloud Run ends

BigQuery query job
    -> CALL job_market.process_job_run(run_id)
    -> deterministic deduplication
    -> Toronto normalization
    -> row and run data-quality calculations
    -> curated_jobs + jobs_current
    -> job_observations + jobs_state
    -> published_jobs view
    -> transform_status = SUCCESS
```

`python src/pipeline.py` does not run Python business transformations. It generates one UUID, calls Adzuna sequentially, writes the transient RAW file, appends it to BigQuery, and records `RAW_LOADED`.

When `AUTO_TRANSFORM=false`, the process stops there and transformation can be invoked manually. When `AUTO_TRANSFORM=true`, Cloud Run submits one parameterized BigQuery `CALL`, records its `transform_job_id`, and exits without waiting for completion. BigQuery then executes the warehouse transformation asynchronously.

Cloud Run success therefore means ingestion succeeded and, when automatic submission is enabled, the transform query was accepted for execution. The authoritative final pipeline state is always `job_run_control.transform_status`.

## Current deployment status

The ELT migration and automatic Cloud Run-to-BigQuery orchestration have both been validated in the live GCP environment.

Latest validated automatic run:

```text
RAW                150
CURATED            150
PUBLISHED          139
extract_status     RAW_LOADED
transform_status   SUCCESS
error_message      NULL
```

The repository defaults `AUTO_TRANSFORM` to `false` for safe backward compatibility. The deployed Cloud Run Job has also been validated with `AUTO_TRANSFORM=true`.

Cloud Scheduler is the remaining automation step. Scheduler/IAM configuration is currently pending the required project permissions.

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

Pages are requested sequentially. Pagination stops at `max_pages`, an empty later page, or a page smaller than `results_per_page`. Any requested-page failure fails the entire ingestion; a partial result is never marked `RAW_LOADED`.

`raw_jobs` remains append-only and keeps its legacy columns. ELT provenance includes:

- `source_job_id`
- `page_number`
- `position_in_page`
- `search_role`
- `search_location`
- `raw_payload` as BigQuery `JSON`

Every source result is retained, including repeated Adzuna IDs across pages. Cross-page deduplication no longer occurs before RAW persistence. BigQuery owns logical deduplication.

## BigQuery transformation

The central warehouse API is:

```sql
CALL `weekly-market-trend.job_market.process_job_run`('<run-id>');
```

For the requested run, BigQuery:

1. validates run-control state and RAW completeness;
2. rejects stale/out-of-order runs;
3. calculates RAW uniqueness metrics;
4. deterministically deduplicates source rows;
5. normalizes Toronto locations;
6. calculates row-level data quality;
7. replaces `curated_jobs` and `jobs_current`;
8. writes retry-safe `job_observations`;
9. MERGEs `jobs_state`;
10. writes run-level `data_quality_runs`;
11. applies the publish gate through `published_jobs`;
12. records `SUCCESS` in `job_run_control`.

Failures roll back warehouse mutations, preserve RAW, and record `TRANSFORM_FAILED`.

## Data quality

Completeness: 50 points total.

Validity: 30 points total.

Timeliness: 20 points total.

Statuses:

- `PASS`: score >= 80
- `REVIEW`: score >= 60 and < 80
- `FAIL`: score < 60

Missing salary remains a source-coverage issue rather than a hard failure.

The publish threshold defaults to 80. A row is publishable only when its score meets the threshold, it has no hard-failure flag, and it is no more than 180 days old.

Recent validated run:

```text
completeness_score      100.0
validity_score           99.6
uniqueness_score        100.0
timeliness_score         79.93
overall_quality_score    96.87
quality_status           PASS
publishable_jobs         139 / 150
```

## Automatic orchestration

Set:

```dotenv
AUTO_TRANSFORM=true
```

After RAW persistence succeeds, Python submits exactly one parameterized query:

```sql
CALL `weekly-market-trend.job_market.process_job_run`(@run_id);
```

The query is asynchronous. Python records the returned BigQuery `job_id` and does not wait for transformation completion.

Failure semantics:

- extraction / RAW-load failure -> `EXTRACT_FAILED`, exit non-zero;
- RAW success with `AUTO_TRANSFORM=false` -> `RAW_LOADED` / `PENDING`, exit 0;
- RAW success + transform submission success -> exit 0;
- RAW success + transform submission failure -> RAW remains available and the process exits non-zero.

The authoritative final state remains `job_run_control.transform_status`.

## Cloud Scheduler plan

Cloud Scheduler is not yet configured.

Intended final flow:

```text
Cloud Scheduler
    -> authenticated Cloud Run Job invocation
    -> Adzuna ingestion
    -> RAW_LOADED
    -> asynchronous BigQuery transform submission
    -> BigQuery SUCCESS
```

Recommended identity design:

- dedicated Scheduler service account used only to invoke the Cloud Run Job;
- Cloud Run runtime identity owns RAW-writing and BigQuery job submission permissions;
- Scheduler receives no BigQuery transformation permissions.

Scheduler setup is deferred until the required IAM / Cloud Scheduler permissions are available.

## Cost controls

BigQuery transformations are scoped to the requested `run_id`.

Future optimization may include:

```sql
PARTITION BY DATE(ingested_at)
CLUSTER BY run_id, source_job_id
```

At the current dataset size this is an optimization backlog item rather than a functional blocker.

## Configuration

```dotenv
ADZUNA_APP_ID=your_app_id
ADZUNA_APP_KEY=your_app_key
QUALITY_PUBLISH_THRESHOLD=80
AUTO_TRANSFORM=false
```

Never commit API credentials.

## Validation history

Validated milestones:

- Python ETL vs BigQuery ELT parity passed with zero row-level and run-metric differences for the captured baseline batch;
- BigQuery SQL assertions passed;
- stale-run rejection validated live;
- same-run retry behavior validated;
- Docker build passed;
- Cloud Run ingestion-only mode validated;
- `AUTO_TRANSFORM=false` backward-compatible mode validated;
- `AUTO_TRANSFORM=true` asynchronous Cloud Run-to-BigQuery submission validated live;
- orchestration test suite: `42 / 42` Python tests passed;
- latest automatic live flow: `150 RAW -> 150 curated -> 139 published`, final `transform_status = SUCCESS`.

The tag `elt-e2e-validated` marks the validated ELT baseline before automatic orchestration changes.

## Known limitations

- `max_pages = 3` limits source coverage.
- Adzuna ranking changes can move jobs outside the configured pages.
- Salary and contract type coverage are source-limited.
- Existing production data tables are not fully partitioned/clustered for long-term scale.
- Absence does not automatically mark a job inactive.
- Current-snapshot table semantics are intentionally preserved.
- An explicit transform concurrency lock is not implemented.
- Cloud Scheduler is not yet configured because required project permissions are pending.
- Downstream BI integration remains future work.
