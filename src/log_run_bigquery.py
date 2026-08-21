import json
import sys

from google.cloud import bigquery

from pipeline_config import DATASET_ID, PROJECT_ID


TABLE_ID = "pipeline_runs"


def main():
    if len(sys.argv) != 2:
        raise RuntimeError(
            "Expected one JSON run record argument."
        )

    run_record = json.loads(sys.argv[1])

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
            "STRING",
            mode="REQUIRED"
        ),
        bigquery.SchemaField(
            "started_at",
            "TIMESTAMP"
        ),
        bigquery.SchemaField(
            "finished_at",
            "TIMESTAMP"
        ),
        bigquery.SchemaField(
            "status",
            "STRING"
        ),
        bigquery.SchemaField(
            "duration_seconds",
            "FLOAT"
        ),
        bigquery.SchemaField(
            "records_extracted",
            "INTEGER"
        ),
        bigquery.SchemaField(
            "records_clean",
            "INTEGER"
        ),
        bigquery.SchemaField(
            "failed_step",
            "STRING"
        ),
        bigquery.SchemaField(
            "error_message",
            "STRING"
        ),
    ]

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=(
            bigquery.WriteDisposition.WRITE_APPEND
        ),
    )

    print(
        f"Writing pipeline run {run_record['run_id']} "
        "to BigQuery..."
    )

    load_job = client.load_table_from_json(
        [run_record],
        table_id,
        job_config=job_config,
    )

    load_job.result()

    table = client.get_table(
        table_id
    )

    print(
        "Pipeline run log saved to BigQuery!"
    )

    print(
        f"Total pipeline runs: {table.num_rows}"
    )


if __name__ == "__main__":
    main()
