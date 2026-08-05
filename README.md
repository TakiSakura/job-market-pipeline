# Job Market Data Pipeline

A Python end-to-end pipeline that collects job postings from the Adzuna Jobs API, normalizes them, tracks their history, and logs every pipeline run.

## Current Pipeline

```text
Adzuna Jobs API
  -> Extract to raw JSON
  -> Clean and normalize
  -> Historical tracking
  -> Pipeline run logging
```

The current implementation runs locally. Google Cloud Run and BigQuery are planned architecture and are not yet implemented.

## Features

- Configurable country, location, and role in `config/search_config.json`
- Adzuna credentials supplied only through environment variables
- Raw and clean JSON data layers
- Location and field normalization
- API-provided stable job IDs
- Historical state with `first_seen_at`, `last_seen_at`, and `is_active`
- Append-only job observations in `data/job_observations.jsonl`
- Fail-fast pipeline orchestration and run logging in `data/pipeline_runs.jsonl`

## Project Structure

```text
job-market-pipeline/
|-- config/
|   `-- search_config.json
|-- src/
|   |-- main.py
|   |-- clean_jobs.py
|   |-- track_history.py
|   `-- pipeline.py
|-- data/                 # generated pipeline outputs
|-- requirements.txt
|-- .gitignore
`-- README.md
```

## Configuration

`config/search_config.json`:

```json
{
  "country": "Canada",
  "location": "Toronto",
  "role": "Data Analyst"
}
```

The country can be a supported country name or a two-letter Adzuna country code such as `ca`.

Create a local `.env` file (already ignored by Git):

```dotenv
ADZUNA_APP_ID=your_app_id
ADZUNA_APP_KEY=your_app_key
```

Environment variables provided by the runtime take precedence, which makes the same code suitable for later deployment to Cloud Run.

## Run Locally

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python src\pipeline.py
```

The pipeline stops immediately if extraction, cleaning, or historical tracking fails, and writes the outcome to `data/pipeline_runs.jsonl`.

## Generated Data

- `data/raw_jobs.json`: normalized Adzuna extraction output
- `data/clean_jobs.json`: cleaned records matching the configured location
- `data/job_state.json`: latest known state of every observed job
- `data/job_observations.jsonl`: append-only observation history
- `data/pipeline_runs.jsonl`: pipeline execution history

## Migration from Canada Job Bank

Adzuna's API `id` is now used directly as `job_id`; IDs are no longer parsed from Job Bank URLs. Salary is represented by `salary_min` and `salary_max`, and clean records now also retain description, category, and contract type. Existing Job Bank state and observations are not rewritten; if retained, they remain historical records alongside newly collected Adzuna records.

## Planned Architecture

```text
Cloud Scheduler
  -> Google Cloud Run (planned)
  -> Python pipeline
  -> BigQuery (planned)
  -> BI/dashboard layer (planned)
```

Planned work includes Cloud Run deployment, BigQuery storage, scheduling, cloud logging and monitoring, pagination, and dashboards.
