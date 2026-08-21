import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery

from pipeline_config import BIGQUERY_LOCATION, DATASET_ID, PROJECT_ID


ROOT_DIR = Path(__file__).resolve().parents[1]
CLEAN_PATH = ROOT_DIR / "data" / "clean_jobs.json"

STATE_TABLE = "jobs_state"


def utc_now():
    return datetime.now(timezone.utc)


def load_clean_jobs():
    with open(CLEAN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def create_state_table_if_needed(client):
    table_id = (
        f"{PROJECT_ID}."
        f"{DATASET_ID}."
        f"{STATE_TABLE}"
    )

    schema = [
        bigquery.SchemaField("job_id", "STRING", mode="REQUIRED"),
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
        bigquery.SchemaField("first_seen_at", "TIMESTAMP"),
        bigquery.SchemaField("last_seen_at", "TIMESTAMP"),
        bigquery.SchemaField("is_active", "BOOLEAN"),
    ]

    table = bigquery.Table(
        table_id,
        schema=schema
    )

    client.create_table(
        table,
        exists_ok=True
    )

    return table_id


def main():
    jobs = load_clean_jobs()

    observed_at = utc_now().isoformat(
        timespec="seconds"
    )

    client = bigquery.Client(
        project=PROJECT_ID
    )

    state_table_id = create_state_table_if_needed(
        client
    )

    # Temporary staging table for this pipeline run
    staging_table_id = (
        f"{PROJECT_ID}."
        f"{DATASET_ID}."
        f"jobs_state_staging_{uuid.uuid4().hex}"
    )

    staging_schema = [
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
        bigquery.SchemaField("observed_at", "TIMESTAMP"),
    ]

    rows = []

    for job in jobs:
        job_id = job.get("job_id")

        if not job_id:
            continue

        rows.append({
            **job,
            "observed_at": observed_at
        })

    staging_config = bigquery.LoadJobConfig(
        schema=staging_schema,
        write_disposition=(
            bigquery.WriteDisposition.WRITE_TRUNCATE
        )
    )

    print(
        f"Loading {len(rows)} jobs "
        "into temporary staging table..."
    )

    load_job = client.load_table_from_json(
        rows,
        staging_table_id,
        job_config=staging_config
    )

    load_job.result()

    merge_sql = f"""
    MERGE `{state_table_id}` AS target
    USING `{staging_table_id}` AS source
    ON target.job_id = source.job_id

    WHEN MATCHED THEN
      UPDATE SET
        title = source.title,
        company = source.company,
        city = source.city,
        province = source.province,
        country = source.country,
        posted_date = source.posted_date,
        salary_min = source.salary_min,
        salary_max = source.salary_max,
        description = source.description,
        category = source.category,
        contract_type = source.contract_type,
        source = source.source,
        job_url = source.job_url,
        last_seen_at = source.observed_at,
        is_active = TRUE

    WHEN NOT MATCHED THEN
      INSERT (
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
        first_seen_at,
        last_seen_at,
        is_active
      )
      VALUES (
        source.job_id,
        source.title,
        source.company,
        source.city,
        source.province,
        source.country,
        source.posted_date,
        source.salary_min,
        source.salary_max,
        source.description,
        source.category,
        source.contract_type,
        source.source,
        source.job_url,
        source.observed_at,
        source.observed_at,
        TRUE
      )
    """

    print("Merging jobs into jobs_state...")

    query_job = client.query(
        merge_sql,
        location=BIGQUERY_LOCATION
    )

    query_job.result()

    # Temporary table is no longer needed
    client.delete_table(
        staging_table_id,
        not_found_ok=True
    )

    table = client.get_table(
        state_table_id
    )

    print("Historical state update successful!")
    print(f"Observed at: {observed_at}")
    print(f"Jobs processed: {len(rows)}")
    print(f"Total jobs in state: {table.num_rows}")


if __name__ == "__main__":
    main()
