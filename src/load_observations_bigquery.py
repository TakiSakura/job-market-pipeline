import json
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery

from pipeline_config import DATASET_ID, PROJECT_ID, get_pipeline_run_id


ROOT_DIR = Path(__file__).resolve().parents[1]
CLEAN_PATH = ROOT_DIR / "data" / "clean_jobs.json"

TABLE_ID = "job_observations"


def main():
    with open(CLEAN_PATH, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    observed_at = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    run_id = get_pipeline_run_id()

    rows = []

    for job in jobs:
        rows.append({
            "run_id": run_id,
            "observed_at": observed_at,
            "job_id": job.get("job_id"),
            "title": job.get("title"),
            "company": job.get("company"),
            "city": job.get("city"),
            "province": job.get("province"),
            "country": job.get("country"),
            "posted_date": job.get("posted_date"),
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "description": job.get("description"),
            "category": job.get("category"),
            "contract_type": job.get("contract_type"),
            "source": job.get("source"),
            "job_url": job.get("job_url"),
        })

    client = bigquery.Client(
        project=PROJECT_ID
    )

    table_id = (
        f"{PROJECT_ID}."
        f"{DATASET_ID}."
        f"{TABLE_ID}"
    )

    schema = [
        bigquery.SchemaField(
            "run_id",
            "STRING"
        ),
        bigquery.SchemaField(
            "observed_at",
            "TIMESTAMP"
        ),
        bigquery.SchemaField(
            "job_id",
            "STRING"
        ),
        bigquery.SchemaField(
            "title",
            "STRING"
        ),
        bigquery.SchemaField(
            "company",
            "STRING"
        ),
        bigquery.SchemaField(
            "city",
            "STRING"
        ),
        bigquery.SchemaField(
            "province",
            "STRING"
        ),
        bigquery.SchemaField(
            "country",
            "STRING"
        ),
        bigquery.SchemaField(
            "posted_date",
            "STRING"
        ),
        bigquery.SchemaField(
            "salary_min",
            "FLOAT"
        ),
        bigquery.SchemaField(
            "salary_max",
            "FLOAT"
        ),
        bigquery.SchemaField(
            "description",
            "STRING"
        ),
        bigquery.SchemaField(
            "category",
            "STRING"
        ),
        bigquery.SchemaField(
            "contract_type",
            "STRING"
        ),
        bigquery.SchemaField(
            "source",
            "STRING"
        ),
        bigquery.SchemaField(
            "job_url",
            "STRING"
        ),
    ]

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=(
            bigquery.WriteDisposition.WRITE_APPEND
        ),
        schema_update_options=[
            bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION
        ],
    )

    print(
        f"Appending {len(rows)} observations..."
    )
    print(f"Run ID: {run_id}")

    load_job = client.load_table_from_json(
        rows,
        table_id,
        job_config=job_config,
    )

    load_job.result()

    table = client.get_table(
        table_id
    )

    print(
        "Observation load successful!"
    )

    print(
        f"Table: {table.full_table_id}"
    )

    print(
        f"Total rows: {table.num_rows}"
    )


if __name__ == "__main__":
    main()
