import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.cloud import bigquery

from clean_jobs import normalize_job_location
from data_quality import calculate_quality_metrics, score_jobs
from load_curated_bigquery import CURATED_SCHEMA
from pipeline_config import BIGQUERY_LOCATION, DATASET_ID, PROJECT_ID


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config" / "search_config.json"
BASELINE_TABLE = "curated_jobs_etl_baseline"
SHADOW_TABLE = "curated_jobs_elt_shadow"
PUBLISH_THRESHOLD = 80.0


def table_id(name):
    return f"{PROJECT_ID}.{DATASET_ID}.{name}"


def query_rows(client, sql, parameters):
    config = bigquery.QueryJobConfig(query_parameters=parameters)
    return list(
        client.query(
            sql,
            job_config=config,
            location=BIGQUERY_LOCATION,
        ).result()
    )


def captured_raw(client, run_id):
    rows = query_rows(
        client,
        f"""
        SELECT
          job_id, title, company, location, location_area, posted_date,
          salary_min, salary_max, description, category, contract_type,
          source, job_url
        FROM `{table_id('raw_jobs')}`
        WHERE run_id = @run_id
        ORDER BY ingested_at, job_id
        """,
        [bigquery.ScalarQueryParameter("run_id", "STRING", run_id)],
    )
    return [dict(row.items()) for row in rows]


def baseline_checked_at(client, run_id):
    rows = query_rows(
        client,
        f"""
        SELECT checked_at
        FROM `{table_id('data_quality_runs')}`
        WHERE run_id = @run_id
        ORDER BY checked_at DESC
        LIMIT 1
        """,
        [bigquery.ScalarQueryParameter("run_id", "STRING", run_id)],
    )
    if not rows:
        raise RuntimeError(
            "The captured run needs an existing stable Python data-quality record."
        )
    return rows[0]["checked_at"]


def python_baseline(raw_jobs, config, run_id, checked_at):
    clean_jobs = []
    target_location = config["location"].strip().casefold()
    for job in raw_jobs:
        location = normalize_job_location(job, config)
        clean_job = {
            "job_id": job.get("job_id"),
            "title": job.get("title"),
            "company": job.get("company"),
            "city": location["city"],
            "province": location["province"],
            "country": location["country"],
            "posted_date": job.get("posted_date"),
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "description": job.get("description"),
            "category": job.get("category"),
            "contract_type": job.get("contract_type"),
            "source": job.get("source"),
            "job_url": job.get("job_url"),
        }
        if location["city"] and location["city"].casefold() == target_location:
            clean_jobs.append(clean_job)

    curated, evaluations = score_jobs(
        clean_jobs,
        run_id,
        checked_at,
        PUBLISH_THRESHOLD,
    )
    report = calculate_quality_metrics(
        clean_jobs,
        evaluations,
        run_id,
        checked_at,
        PUBLISH_THRESHOLD,
    )
    return curated, report


def write_shadow_tables(client, curated, run_id, checked_at):
    baseline_id = table_id(BASELINE_TABLE)
    load_config = bigquery.LoadJobConfig(
        schema=CURATED_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_json(
        curated,
        baseline_id,
        job_config=load_config,
        location=BIGQUERY_LOCATION,
    ).result()

    baseline_table = client.get_table(baseline_id)
    baseline_table.expires = datetime.now(timezone.utc) + timedelta(days=7)
    client.update_table(baseline_table, ["expires"])

    parameters = [
        bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
        bigquery.ScalarQueryParameter("processed_at", "TIMESTAMP", checked_at),
        bigquery.ScalarQueryParameter(
            "publish_threshold", "FLOAT64", PUBLISH_THRESHOLD
        ),
    ]
    query_rows(
        client,
        f"""
        CREATE OR REPLACE TABLE `{table_id(SHADOW_TABLE)}`
        OPTIONS (
          expiration_timestamp = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
        ) AS
        SELECT
          job_id, title, company, city, province, country, posted_date,
          salary_min, salary_max, description, category, contract_type,
          source, job_url, run_id, quality_score, quality_status,
          quality_flags, is_publishable
        FROM `{table_id('job_run_rows')}`(
          @run_id,
          @processed_at,
          @publish_threshold
        )
        """,
        parameters,
    )


def compare_rows(client):
    columns = """
      job_id, title, company, city, province, country, posted_date,
      salary_min, salary_max, description, category, contract_type,
      source, job_url, run_id, quality_score, quality_status,
      TO_JSON_STRING(ARRAY(
        SELECT flag FROM UNNEST(quality_flags) AS flag ORDER BY flag
      )) AS quality_flags,
      is_publishable
    """
    rows = query_rows(
        client,
        f"""
        WITH baseline AS (
          SELECT {columns} FROM `{table_id(BASELINE_TABLE)}`
        ), shadow AS (
          SELECT {columns} FROM `{table_id(SHADOW_TABLE)}`
        )
        SELECT
          (SELECT COUNT(*) FROM `{table_id(BASELINE_TABLE)}`) AS baseline_rows,
          (SELECT COUNT(*) FROM `{table_id(SHADOW_TABLE)}`) AS shadow_rows,
          (SELECT COUNT(*) FROM (
            SELECT * FROM baseline EXCEPT DISTINCT SELECT * FROM shadow
          )) AS baseline_only,
          (SELECT COUNT(*) FROM (
            SELECT * FROM shadow EXCEPT DISTINCT SELECT * FROM baseline
          )) AS shadow_only
        """,
        [],
    )
    return dict(rows[0].items())


def sql_metrics(client, run_id, checked_at):
    rows = query_rows(
        client,
        f"""
        WITH transformed AS (
          SELECT *
          FROM `{table_id('job_run_rows')}`(@run_id, @processed_at, 80.0)
        ), raw_metrics AS (
          SELECT
            COUNT(*) AS raw_row_count,
            COUNT(DISTINCT COALESCE(
              NULLIF(source_job_id, ''), NULLIF(job_id, ''),
              NULLIF(JSON_VALUE(raw_payload, '$.id'), '')
            )) AS raw_unique_job_ids,
            COUNTIF(COALESCE(
              NULLIF(source_job_id, ''), NULLIF(job_id, ''),
              NULLIF(JSON_VALUE(raw_payload, '$.id'), '')
            ) IS NOT NULL) - COUNT(DISTINCT COALESCE(
              NULLIF(source_job_id, ''), NULLIF(job_id, ''),
              NULLIF(JSON_VALUE(raw_payload, '$.id'), '')
            )) AS duplicate_job_ids
          FROM `{table_id('raw_jobs')}`
          WHERE run_id = @run_id
        ), components AS (
          SELECT
            COUNT(*) AS total_jobs,
            COUNTIF(salary_min IS NOT NULL OR salary_max IS NOT NULL)
              AS salary_coverage_count,
            COUNTIF(contract_type IS NOT NULL AND TRIM(contract_type) != '')
              AS contract_type_coverage_count,
            COUNTIF('STALE_JOB' IN UNNEST(quality_flags)) AS stale_jobs,
            COUNTIF(is_publishable) AS publishable_jobs,
            ROUND(SAFE_DIVIDE(SUM(completeness_points), COUNT(*) * 50) * 100, 2)
              AS completeness_score,
            ROUND(SAFE_DIVIDE(SUM(validity_points), COUNT(*) * 30) * 100, 2)
              AS validity_score,
            ROUND(SAFE_DIVIDE(SUM(timeliness_points), COUNT(*) * 20) * 100, 2)
              AS timeliness_score
          FROM transformed
        ), scored AS (
          SELECT
            *,
            ROUND(SAFE_DIVIDE(
              raw_row_count - duplicate_job_ids, raw_row_count
            ) * 100, 2) AS uniqueness_score
          FROM components CROSS JOIN raw_metrics
        )
        SELECT
          *,
          ROUND(
            completeness_score * 0.40
            + validity_score * 0.30
            + uniqueness_score * 0.15
            + timeliness_score * 0.15,
            2
          ) AS overall_quality_score,
          ROUND(SAFE_DIVIDE(salary_coverage_count, total_jobs) * 100, 2)
            AS salary_coverage_pct,
          ROUND(SAFE_DIVIDE(contract_type_coverage_count, total_jobs) * 100, 2)
            AS contract_type_coverage_pct
        FROM scored
        """,
        [
            bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
            bigquery.ScalarQueryParameter("processed_at", "TIMESTAMP", checked_at),
        ],
    )
    return dict(rows[0].items())


def compare_metrics(raw_jobs, report, warehouse):
    source_ids = [job["job_id"] for job in raw_jobs if job.get("job_id")]
    expected = {
        "raw_row_count": len(raw_jobs),
        "raw_unique_job_ids": len(set(source_ids)),
        "duplicate_job_ids": len(source_ids) - len(set(source_ids)),
        "total_jobs": report["total_jobs"],
        "salary_coverage_count": report["salary_coverage_count"],
        "salary_coverage_pct": report["salary_coverage_pct"],
        "contract_type_coverage_count": report["contract_type_coverage_count"],
        "contract_type_coverage_pct": report["contract_type_coverage_pct"],
        "stale_jobs": report["stale_jobs"],
        "publishable_jobs": report["publishable_jobs"],
        "completeness_score": report["completeness_score"],
        "validity_score": report["validity_score"],
        "uniqueness_score": report["uniqueness_score"],
        "timeliness_score": report["timeliness_score"],
        "overall_quality_score": report["overall_quality_score"],
    }
    return {
        key: {"python": value, "bigquery": warehouse.get(key)}
        for key, value in expected.items()
        if value != warehouse.get(key)
    }


def main():
    parser = argparse.ArgumentParser(
        description="Compare stable Python ETL with BigQuery ELT on one captured run."
    )
    parser.add_argument("run_id", help="Stable captured RAW run_id")
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)
    raw_jobs = captured_raw(client, args.run_id)
    if not raw_jobs:
        raise RuntimeError(f"No RAW rows found for run_id {args.run_id}")
    checked_at = baseline_checked_at(client, args.run_id)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    curated, report = python_baseline(
        raw_jobs,
        config,
        args.run_id,
        checked_at,
    )
    write_shadow_tables(client, curated, args.run_id, checked_at)
    row_result = compare_rows(client)
    metric_mismatches = compare_metrics(
        raw_jobs,
        report,
        sql_metrics(client, args.run_id, checked_at),
    )

    result = {
        "run_id": args.run_id,
        "checked_at": checked_at.isoformat(),
        "rows": row_result,
        "metric_mismatches": metric_mismatches,
        "baseline_table": table_id(BASELINE_TABLE),
        "shadow_table": table_id(SHADOW_TABLE),
    }
    print(json.dumps(result, indent=2, default=str))

    if row_result["baseline_only"] or row_result["shadow_only"]:
        raise SystemExit("Row-level parity failed.")
    if metric_mismatches:
        raise SystemExit("Run-metric parity failed.")
    print("Python ETL and BigQuery ELT parity passed.")


if __name__ == "__main__":
    main()
