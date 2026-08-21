from google.cloud import bigquery

from pipeline_config import BIGQUERY_LOCATION, DATASET_ID, PROJECT_ID
from run_control import get_transform_job_id, record_transform_job_id


CALL_SQL = f"CALL `{PROJECT_ID}.{DATASET_ID}.process_job_run`(@run_id)"


def submit_elt_transform(client, run_id):
    existing_job_id = get_transform_job_id(client, run_id)
    if existing_job_id:
        return existing_job_id, False

    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
        ]
    )
    query_job = client.query(
        CALL_SQL,
        job_config=config,
        location=BIGQUERY_LOCATION,
    )
    if not query_job.job_id:
        raise RuntimeError("BigQuery transform submission returned no job ID.")

    record_transform_job_id(client, run_id, query_job.job_id)
    return query_job.job_id, True
