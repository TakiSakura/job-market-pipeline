import json
from pathlib import Path

from google.cloud import bigquery

from pipeline_config import DATASET_ID, PROJECT_ID


ROOT_DIR = Path(__file__).resolve().parents[1]
CLEAN_PATH = ROOT_DIR / "data" / "clean_jobs.json"

TABLE_ID = "jobs_current"


def main():
    # Read cleaned jobs
    with open(CLEAN_PATH, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    print(f"Loaded {len(jobs)} clean jobs.")

    # Connect to BigQuery using ADC
    client = bigquery.Client(project=PROJECT_ID)

    table_id = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

    print(f"Writing to: {table_id}")

    # Define table schema
    schema = [
        bigquery.SchemaField("job_id", "STRING"),
        bigquery.SchemaField("title", "STRING"),
        bigquery.SchemaField("company", "STRING"),
        bigquery.SchemaField("city", "STRING"),
        bigquery.SchemaField("province", "STRING"),
        bigquery.SchemaField("country", "STRING"),
        bigquery.SchemaField("posted_date", "STRING"),
        bigquery.SchemaField("salary_min", "FLOAT"),
        bigquery.SchemaField("salary_max", "FLOAT"),
        bigquery.SchemaField("description", "STRING"),
        bigquery.SchemaField("category", "STRING"),
        bigquery.SchemaField("contract_type", "STRING"),
        bigquery.SchemaField("source", "STRING"),
        bigquery.SchemaField("job_url", "STRING"),
    ]

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    # Upload JSON records
    load_job = client.load_table_from_json(
        jobs,
        table_id,
        job_config=job_config,
    )

    # Wait for BigQuery to finish
    load_job.result()

    table = client.get_table(table_id)

    print("BigQuery load successful!")
    print(f"Table: {table.full_table_id}")
    print(f"Rows:  {table.num_rows}")


if __name__ == "__main__":
    main()
