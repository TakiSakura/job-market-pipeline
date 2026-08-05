# Job Market Data Pipeline

A Python-based end-to-end data pipeline for collecting, cleaning, tracking, and analyzing job posting data.

The current version runs locally and demonstrates the full pipeline flow from data extraction to historical tracking and pipeline run logging.

## Current Pipeline

```text
Job Bank
   ↓
Data Extraction
   ↓
Raw JSON
   ↓
Cleaning & Normalization
   ↓
Clean JSON
   ↓
Historical Tracking
   ↓
Pipeline Run Logging
```

## Features

- Configurable job search by role and location
- Web scraping with Python and BeautifulSoup
- Raw and clean data layers
- Location normalization
- Stable job ID extraction
- Historical tracking with `first_seen_at` and `last_seen_at`
- Job observation history
- End-to-end pipeline orchestration
- Pipeline run logging
- Failure detection with failed-step tracking

## Project Structure

```text
job-market-data-pipeline/
│
├── config/
│   └── search_config.json
│
├── src/
│   ├── main.py
│   ├── clean_jobs.py
│   ├── track_history.py
│   └── pipeline.py
│
├── data/
│   └── generated pipeline outputs
│
├── requirements.txt
├── .gitignore
└── README.md
```

## Example Configuration

```json
{
  "country": "Canada",
  "location": "Toronto",
  "role": "Data Analyst"
}
```

## Run the Pipeline

Create and activate a virtual environment, install dependencies, then run:

```bash
pip install -r requirements.txt
python src/pipeline.py
```

The pipeline will automatically execute:

```text
Extract
  ↓
Clean
  ↓
Historical Tracking
  ↓
Run Logging
```

## Historical Tracking

Each job is identified using a stable `job_id`.

The pipeline maintains:

- `first_seen_at`
- `last_seen_at`
- current job state
- historical observation records

This allows repeated pipeline runs to distinguish newly discovered jobs from previously observed jobs.

## Pipeline Monitoring

Each execution records:

- Run ID
- Start and finish time
- Run status
- Duration
- Records extracted
- Records cleaned
- Failed step
- Error message

This provides a foundation for pipeline monitoring and failure analysis.

## Tech Stack

**Python · Requests · BeautifulSoup · JSON · Git**

## Planned Architecture

The next phase will migrate the local pipeline to Google Cloud:

```text
Cloud Scheduler
      ↓
Cloud Run
      ↓
Python Pipeline
      ↓
BigQuery
      ↓
Power BI
```

Planned improvements include:

- BigQuery data warehouse integration
- Cloud Run deployment
- Scheduled pipeline execution
- Cloud logging and monitoring
- Improved location filtering
- Pagination support
- Additional job data sources
- Power BI dashboards

## Goal

The goal of this project is to build a reusable job market data pipeline that continuously collects changing job data, preserves historical information, and prepares analytics-ready datasets for market trend analysis.
