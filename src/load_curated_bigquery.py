import json
from pathlib import Path

from google.cloud import bigquery
from google.api_core.exceptions import NotFound

from pipeline_config import DATASET_ID, PROJECT_ID


ROOT_DIR = Path(__file__).resolve().parents[1]
CURATED_PATH = ROOT_DIR / "data" / "curated_jobs.json"
CURATED_TABLE = "curated_jobs"
PUBLISHED_VIEW = "published_jobs"


CURATED_SCHEMA = [
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
    bigquery.SchemaField("run_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("quality_score", "FLOAT", mode="REQUIRED"),
    bigquery.SchemaField("quality_status", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("quality_flags", "STRING", mode="REPEATED"),
    bigquery.SchemaField("is_publishable", "BOOLEAN", mode="REQUIRED"),
]


def ensure_published_view(client, curated_table_id):
    view_id = f"{PROJECT_ID}.{DATASET_ID}.{PUBLISHED_VIEW}"
    view_query = (
        f"SELECT * FROM `{curated_table_id}` "
        "WHERE is_publishable = TRUE"
    )

    try:
        view = client.get_table(view_id)
    except NotFound:
        view = bigquery.Table(view_id)
        view.view_query = view_query
        client.create_table(view)
        print(f"Created publish view: {view_id}")
        return

    if view.table_type != "VIEW":
        raise RuntimeError(
            f"{view_id} already exists but is not a BigQuery view."
        )

    if " ".join((view.view_query or "").split()) != " ".join(view_query.split()):
        view.view_query = view_query
        client.update_table(view, ["view_query"])
        print(f"Updated publish view: {view_id}")
    else:
        print(f"Publish view already current: {view_id}")


def main():
    with open(CURATED_PATH, "r", encoding="utf-8") as file:
        jobs = json.load(file)

    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{CURATED_TABLE}"
    job_config = bigquery.LoadJobConfig(
        schema=CURATED_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    print(f"Writing {len(jobs)} curated jobs to {table_id}...")
    load_job = client.load_table_from_json(
        jobs,
        table_id,
        job_config=job_config,
    )
    load_job.result()

    ensure_published_view(client, table_id)

    publishable_count = sum(job["is_publishable"] for job in jobs)
    print("Curated BigQuery load successful!")
    print(f"Curated rows: {len(jobs)}")
    print(f"Publishable rows: {publishable_count}")


if __name__ == "__main__":
    main()
