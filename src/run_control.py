from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from pipeline_config import (
    BIGQUERY_LOCATION,
    DATASET_ID,
    PROJECT_ID,
    RUN_CONTROL_TABLE,
)


TABLE_ID = RUN_CONTROL_TABLE


RUN_CONTROL_SCHEMA = [
    bigquery.SchemaField("run_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("extract_status", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("transform_status", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("started_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("raw_loaded_at", "TIMESTAMP"),
    bigquery.SchemaField("transform_started_at", "TIMESTAMP"),
    bigquery.SchemaField("transform_finished_at", "TIMESTAMP"),
    bigquery.SchemaField("raw_count", "INTEGER"),
    bigquery.SchemaField("curated_count", "INTEGER"),
    bigquery.SchemaField("published_count", "INTEGER"),
    bigquery.SchemaField("transform_job_id", "STRING"),
    bigquery.SchemaField("error_message", "STRING"),
    bigquery.SchemaField("publish_threshold", "FLOAT"),
]


def table_id():
    return f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"


def ensure_run_control_table(client):
    full_table_id = table_id()
    try:
        client.get_table(full_table_id)
        return full_table_id
    except NotFound:
        table = bigquery.Table(full_table_id, schema=RUN_CONTROL_SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(field="started_at")
        table.clustering_fields = ["run_id", "extract_status", "transform_status"]
        client.create_table(table)
        return full_table_id


def start_ingestion_run(client, run_id, started_at, publish_threshold):
    full_table_id = ensure_run_control_table(client)
    query = f"""
    MERGE `{full_table_id}` AS target
    USING (
      SELECT @run_id AS run_id,
             @started_at AS started_at,
             @publish_threshold AS publish_threshold
    ) AS source
    ON target.run_id = source.run_id
    WHEN MATCHED THEN UPDATE SET
      extract_status = 'EXTRACTING',
      transform_status = 'PENDING',
      started_at = source.started_at,
      raw_loaded_at = NULL,
      transform_started_at = NULL,
      transform_finished_at = NULL,
      raw_count = NULL,
      curated_count = NULL,
      published_count = NULL,
      transform_job_id = NULL,
      error_message = NULL,
      publish_threshold = source.publish_threshold
    WHEN NOT MATCHED THEN INSERT (
      run_id, extract_status, transform_status, started_at, publish_threshold
    ) VALUES (
      source.run_id, 'EXTRACTING', 'PENDING', source.started_at,
      source.publish_threshold
    )
    """
    _run_query(
        client,
        query,
        run_id,
        started_at,
        publish_threshold=publish_threshold,
    )


def mark_raw_loaded(client, run_id, raw_loaded_at, raw_count):
    query = f"""
    UPDATE `{table_id()}`
    SET extract_status = 'RAW_LOADED',
        transform_status = 'PENDING',
        raw_loaded_at = @event_at,
        raw_count = @raw_count,
        error_message = NULL
    WHERE run_id = @run_id
    """
    _run_query(client, query, run_id, raw_loaded_at, raw_count)


def mark_extract_failed(client, run_id, failed_at, error_message):
    query = f"""
    UPDATE `{table_id()}`
    SET extract_status = 'EXTRACT_FAILED',
        transform_status = 'PENDING',
        raw_loaded_at = NULL,
        error_message = @error_message
    WHERE run_id = @run_id
    """
    _run_query(client, query, run_id, failed_at, error_message=error_message)


def get_transform_job_id(client, run_id):
    query = f"""
    SELECT transform_job_id
    FROM `{table_id()}`
    WHERE run_id = @run_id
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
        ]
    )
    rows = list(
        client.query(
            query,
            job_config=config,
            location=BIGQUERY_LOCATION,
        ).result()
    )
    if len(rows) != 1:
        raise RuntimeError(
            "Expected exactly one run-control row before transform submission."
        )
    return rows[0]["transform_job_id"]


def record_transform_job_id(client, run_id, transform_job_id):
    query = f"""
    UPDATE `{table_id()}`
    SET transform_job_id = @transform_job_id,
        error_message = NULL
    WHERE run_id = @run_id
      AND extract_status = 'RAW_LOADED'
    """
    _run_query(
        client,
        query,
        run_id,
        event_at=None,
        transform_job_id=transform_job_id,
    )


def mark_transform_submission_failed(client, run_id, error_message):
    query = f"""
    UPDATE `{table_id()}`
    SET error_message = @error_message
    WHERE run_id = @run_id
      AND extract_status = 'RAW_LOADED'
      AND transform_status = 'PENDING'
    """
    _run_query(
        client,
        query,
        run_id,
        event_at=None,
        error_message=error_message,
    )


def _run_query(
    client,
    query,
    run_id,
    event_at,
    raw_count=None,
    error_message=None,
    publish_threshold=None,
    transform_job_id=None,
):
    parameters = [
        bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
    ]
    if "@started_at" in query:
        parameters.append(
            bigquery.ScalarQueryParameter("started_at", "TIMESTAMP", event_at)
        )
    if "@event_at" in query:
        parameters.append(
            bigquery.ScalarQueryParameter("event_at", "TIMESTAMP", event_at)
        )
    if "@raw_count" in query:
        parameters.append(
            bigquery.ScalarQueryParameter("raw_count", "INT64", raw_count)
        )
    if "@error_message" in query:
        parameters.append(
            bigquery.ScalarQueryParameter("error_message", "STRING", error_message)
        )
    if "@publish_threshold" in query:
        parameters.append(
            bigquery.ScalarQueryParameter(
                "publish_threshold", "FLOAT64", publish_threshold
            )
        )
    if "@transform_job_id" in query:
        parameters.append(
            bigquery.ScalarQueryParameter(
                "transform_job_id", "STRING", transform_job_id
            )
        )

    config = bigquery.QueryJobConfig(query_parameters=parameters)
    client.query(query, job_config=config, location=BIGQUERY_LOCATION).result()
