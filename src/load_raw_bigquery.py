import json
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery

from pipeline_config import DATASET_ID, PROJECT_ID, get_pipeline_run_id


ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT_DIR / "data" / "raw_jobs.json"
TABLE_ID = "raw_jobs"


RAW_SCHEMA = [
    bigquery.SchemaField("run_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("job_id", "STRING"),
    bigquery.SchemaField("title", "STRING"),
    bigquery.SchemaField("company", "STRING"),
    bigquery.SchemaField("location", "STRING"),
    bigquery.SchemaField("location_area", "STRING", mode="REPEATED"),
    bigquery.SchemaField("posted_date", "STRING"),
    bigquery.SchemaField("salary_min", "FLOAT"),
    bigquery.SchemaField("salary_max", "FLOAT"),
    bigquery.SchemaField("description", "STRING"),
    bigquery.SchemaField("category", "STRING"),
    bigquery.SchemaField("contract_type", "STRING"),
    bigquery.SchemaField("source", "STRING"),
    bigquery.SchemaField("job_url", "STRING"),
    bigquery.SchemaField("source_job_id", "STRING"),
    bigquery.SchemaField("page_number", "INTEGER"),
    bigquery.SchemaField("position_in_page", "INTEGER"),
    bigquery.SchemaField("search_role", "STRING"),
    bigquery.SchemaField("search_location", "STRING"),
    bigquery.SchemaField("raw_payload", "JSON"),
]


def main():
    with open(RAW_PATH, "r", encoding="utf-8") as file:
        jobs = json.load(file)

    run_id = get_pipeline_run_id()
    ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [
        {
            "run_id": run_id,
            "ingested_at": ingested_at,
            **job,
        }
        for job in jobs
    ]

    table_id = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    client = bigquery.Client(project=PROJECT_ID)
    job_config = bigquery.LoadJobConfig(
        schema=RAW_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema_update_options=[
            bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION,
        ],
    )

    print(f"Appending {len(rows)} raw jobs to {table_id}...")
    load_job = client.load_table_from_json(
        rows,
        table_id,
        job_config=job_config,
    )
    load_job.result()

    print("Raw BigQuery load successful!")
    print(f"Run ID: {run_id}")


if __name__ == "__main__":
    main()
