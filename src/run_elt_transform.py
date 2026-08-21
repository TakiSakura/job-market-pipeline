import argparse

from google.cloud import bigquery

from pipeline_config import BIGQUERY_LOCATION, DATASET_ID, PROJECT_ID


def main():
    parser = argparse.ArgumentParser(
        description="Manually invoke the BigQuery ELT routine for one RAW_LOADED run."
    )
    parser.add_argument("run_id", help="The ingestion run_id to transform")
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)
    query = f"CALL `{PROJECT_ID}.{DATASET_ID}.process_job_run`(@run_id)"
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("run_id", "STRING", args.run_id)
        ]
    )
    job = client.query(query, job_config=config, location=BIGQUERY_LOCATION)
    print(f"Submitted BigQuery transform job: {job.job_id}")
    job.result()
    print(f"Transformation succeeded for run_id: {args.run_id}")


if __name__ == "__main__":
    main()
