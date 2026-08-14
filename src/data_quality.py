import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from google.cloud import bigquery

from pipeline_config import (
    DATASET_ID,
    PROJECT_ID,
    get_pipeline_run_id,
    get_quality_publish_threshold,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
CLEAN_PATH = ROOT_DIR / "data" / "clean_jobs.json"
CURATED_PATH = ROOT_DIR / "data" / "curated_jobs.json"
TABLE_ID = "data_quality_runs"

COMPLETENESS_WEIGHTS = {
    "job_id": 10,
    "title": 10,
    "company": 8,
    "city": 6,
    "province": 4,
    "country": 4,
    "posted_date": 4,
    "description": 4,
}
COMPLETENESS_MAX_POINTS = sum(COMPLETENESS_WEIGHTS.values())
VALIDITY_MAX_POINTS = 30
TIMELINESS_MAX_POINTS = 20

LOW_SALARY_THRESHOLD = 30000
HIGH_SALARY_THRESHOLD = 300000
FUTURE_DATE_TOLERANCE_DAYS = 1
REVIEW_THRESHOLD = 60.0
PASS_STATUS_THRESHOLD = 80.0
PUBLISH_MAX_AGE_DAYS = 180

HARD_FAILURE_FLAGS = {
    "MISSING_CRITICAL_FIELD",
    "INVALID_POSTED_DATE",
    "FUTURE_POSTED_DATE",
    "INVALID_SALARY_RANGE",
}


def load_jobs():
    with open(CLEAN_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def save_curated_jobs(jobs):
    CURATED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CURATED_PATH, "w", encoding="utf-8") as file:
        json.dump(jobs, file, ensure_ascii=False, indent=2)


def safe_rate(count, total):
    if total == 0:
        return 0.0
    return round(count / total * 100, 2)


def is_populated(value):
    return bool(str(value or "").strip())


def parse_posted_date(value):
    if not is_populated(value):
        return None

    try:
        posted_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)

    return posted_at.astimezone(timezone.utc)


def is_usable_url(value):
    if not is_populated(value):
        return False

    parsed = urlsplit(str(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def get_quality_status(score):
    if score >= PASS_STATUS_THRESHOLD:
        return "PASS"
    if score >= REVIEW_THRESHOLD:
        return "REVIEW"
    return "FAIL"


def passes_publish_gate(score, flags, publish_threshold, age_days=None):
    is_too_old = age_days is not None and age_days > PUBLISH_MAX_AGE_DAYS
    return (
        score >= publish_threshold
        and not (HARD_FAILURE_FLAGS & set(flags))
        and not is_too_old
    )


def timeliness_points(age_days):
    if age_days is None or age_days < -FUTURE_DATE_TOLERANCE_DAYS:
        return 0
    if age_days <= 30:
        return 20
    if age_days <= 60:
        return 16
    if age_days <= 90:
        return 12
    if age_days <= 180:
        return 6
    return 0


def evaluate_job(job, now, publish_threshold):
    flags = []

    completeness = sum(
        weight
        for field, weight in COMPLETENESS_WEIGHTS.items()
        if is_populated(job.get(field))
    )

    if not is_populated(job.get("job_id")) or not is_populated(job.get("title")):
        flags.append("MISSING_CRITICAL_FIELD")

    posted_value = job.get("posted_date")
    posted_at = parse_posted_date(posted_value)
    validity = 0
    age_days = None

    if posted_at is not None:
        validity += 8
        age_days = (now - posted_at).days
        if age_days < -FUTURE_DATE_TOLERANCE_DAYS:
            flags.append("FUTURE_POSTED_DATE")
        else:
            validity += 4
    elif is_populated(posted_value):
        flags.append("INVALID_POSTED_DATE")

    salary_min = job.get("salary_min")
    salary_max = job.get("salary_max")
    invalid_salary_range = (
        salary_min is not None
        and salary_max is not None
        and salary_min > salary_max
    )
    low_salary = salary_min is not None and salary_min < LOW_SALARY_THRESHOLD
    high_salary = salary_max is not None and salary_max > HIGH_SALARY_THRESHOLD

    if invalid_salary_range:
        flags.append("INVALID_SALARY_RANGE")
    if low_salary:
        flags.append("LOW_SALARY_OUTLIER")
    if high_salary:
        flags.append("HIGH_SALARY_OUTLIER")

    if invalid_salary_range:
        salary_validity = 0
    elif low_salary or high_salary:
        salary_validity = 3
    else:
        # Missing salaries are a source-coverage issue, not a row validity failure.
        salary_validity = 6
    validity += salary_validity

    if is_usable_url(job.get("job_url")):
        validity += 6
    else:
        flags.append("INVALID_JOB_URL")

    if is_populated(job.get("source")):
        validity += 6
    else:
        flags.append("MISSING_SOURCE")

    timeliness = timeliness_points(age_days)
    if age_days is not None and age_days > 90:
        flags.append("STALE_JOB")

    score = float(completeness + validity + timeliness)
    status = get_quality_status(score)
    is_publishable = passes_publish_gate(
        score,
        flags,
        publish_threshold,
        age_days,
    )

    return {
        "quality_score": round(score, 2),
        "quality_status": status,
        "quality_flags": flags,
        "is_publishable": is_publishable,
        "completeness_points": completeness,
        "validity_points": validity,
        "timeliness_points": timeliness,
        "age_days": age_days,
    }


def score_job(job, run_id, now=None, publish_threshold=None):
    now = now or datetime.now(timezone.utc)
    publish_threshold = (
        get_quality_publish_threshold()
        if publish_threshold is None
        else publish_threshold
    )
    evaluation = evaluate_job(job, now, publish_threshold)

    return {
        **job,
        "run_id": run_id,
        "quality_score": evaluation["quality_score"],
        "quality_status": evaluation["quality_status"],
        "quality_flags": evaluation["quality_flags"],
        "is_publishable": evaluation["is_publishable"],
    }


def score_jobs(jobs, run_id, now, publish_threshold):
    curated_jobs = []
    evaluations = []

    for job in jobs:
        evaluation = evaluate_job(job, now, publish_threshold)
        evaluations.append(evaluation)
        curated_jobs.append({
            **job,
            "run_id": run_id,
            "quality_score": evaluation["quality_score"],
            "quality_status": evaluation["quality_status"],
            "quality_flags": evaluation["quality_flags"],
            "is_publishable": evaluation["is_publishable"],
        })

    return curated_jobs, evaluations


def component_score(evaluations, field, maximum):
    if not evaluations:
        return 0.0
    total_points = sum(item[field] for item in evaluations)
    return round(total_points / (len(evaluations) * maximum) * 100, 2)


def calculate_quality_metrics(
    jobs,
    evaluations,
    run_id,
    now,
    publish_threshold,
):
    total_jobs = len(jobs)
    job_ids = [job.get("job_id") for job in jobs if job.get("job_id")]
    unique_job_ids = len(set(job_ids))
    duplicate_job_ids = len(job_ids) - unique_job_ids

    missing_job_id = sum(not is_populated(job.get("job_id")) for job in jobs)
    missing_title = sum(not is_populated(job.get("title")) for job in jobs)
    missing_company = sum(not is_populated(job.get("company")) for job in jobs)
    missing_city = sum(not is_populated(job.get("city")) for job in jobs)
    missing_posted_date = sum(
        not is_populated(job.get("posted_date")) for job in jobs
    )
    jobs_with_salary = sum(
        job.get("salary_min") is not None or job.get("salary_max") is not None
        for job in jobs
    )
    jobs_with_contract_type = sum(
        is_populated(job.get("contract_type")) for job in jobs
    )

    all_flags = [flag for item in evaluations for flag in item["quality_flags"]]
    stale_jobs = all_flags.count("STALE_JOB")
    invalid_posted_dates = all_flags.count("INVALID_POSTED_DATE")
    future_posted_dates = all_flags.count("FUTURE_POSTED_DATE")
    low_salary_candidates = all_flags.count("LOW_SALARY_OUTLIER")
    high_salary_candidates = all_flags.count("HIGH_SALARY_OUTLIER")
    invalid_salary_ranges = all_flags.count("INVALID_SALARY_RANGE")

    completeness_score = component_score(
        evaluations, "completeness_points", COMPLETENESS_MAX_POINTS
    )
    validity_score = component_score(
        evaluations, "validity_points", VALIDITY_MAX_POINTS
    )
    timeliness_score = component_score(
        evaluations, "timeliness_points", TIMELINESS_MAX_POINTS
    )
    uniqueness_score = (
        safe_rate(total_jobs - duplicate_job_ids, total_jobs)
        if total_jobs
        else 0.0
    )
    overall_quality_score = round(
        completeness_score * 0.40
        + validity_score * 0.30
        + uniqueness_score * 0.15
        + timeliness_score * 0.15,
        2,
    )

    return {
        "run_id": run_id,
        "checked_at": now.isoformat(timespec="seconds"),
        "total_jobs": total_jobs,
        "unique_job_ids": unique_job_ids,
        "duplicate_job_ids": duplicate_job_ids,
        "missing_job_id": missing_job_id,
        "missing_title": missing_title,
        "missing_company": missing_company,
        "missing_city": missing_city,
        "missing_posted_date": missing_posted_date,
        "salary_coverage_count": jobs_with_salary,
        "salary_coverage_pct": safe_rate(jobs_with_salary, total_jobs),
        "contract_type_coverage_count": jobs_with_contract_type,
        "contract_type_coverage_pct": safe_rate(
            jobs_with_contract_type, total_jobs
        ),
        "low_salary_candidates": low_salary_candidates,
        "high_salary_candidates": high_salary_candidates,
        "invalid_salary_ranges": invalid_salary_ranges,
        "stale_jobs": stale_jobs,
        "stale_jobs_pct": safe_rate(stale_jobs, total_jobs),
        "invalid_posted_dates": invalid_posted_dates,
        "future_posted_dates": future_posted_dates,
        "completeness_score": completeness_score,
        "validity_score": validity_score,
        "uniqueness_score": uniqueness_score,
        "timeliness_score": timeliness_score,
        "overall_quality_score": overall_quality_score,
        "quality_status": get_quality_status(overall_quality_score),
        "publish_threshold": publish_threshold,
        "publishable_jobs": sum(
            passes_publish_gate(
                item["quality_score"],
                item["quality_flags"],
                publish_threshold,
                item["age_days"],
            )
            for item in evaluations
        ),
    }


def print_report(report, publish_threshold):
    print("\nDATA QUALITY REPORT")
    print("=" * 50)
    print(f"Run ID: {report['run_id']}")
    print(f"Total jobs: {report['total_jobs']}")
    print(f"Unique job IDs: {report['unique_job_ids']}")
    print(f"Duplicate job IDs: {report['duplicate_job_ids']}")
    print(f"Salary coverage: {report['salary_coverage_pct']}%")
    print(f"Contract type coverage: {report['contract_type_coverage_pct']}%")
    print(f"Stale jobs: {report['stale_jobs']} ({report['stale_jobs_pct']}%)")
    print(f"Completeness score: {report['completeness_score']}")
    print(f"Validity score: {report['validity_score']}")
    print(f"Uniqueness score: {report['uniqueness_score']}")
    print(f"Timeliness score: {report['timeliness_score']}")
    print(f"Overall quality score: {report['overall_quality_score']}")
    print(f"Batch quality status: {report['quality_status']}")
    print(f"Publish threshold: {publish_threshold}")
    print(f"Publishable jobs: {report['publishable_jobs']}")


def write_to_bigquery(report):
    schema = [
        bigquery.SchemaField("run_id", "STRING"),
        bigquery.SchemaField("checked_at", "TIMESTAMP"),
        bigquery.SchemaField("total_jobs", "INTEGER"),
        bigquery.SchemaField("unique_job_ids", "INTEGER"),
        bigquery.SchemaField("duplicate_job_ids", "INTEGER"),
        bigquery.SchemaField("missing_job_id", "INTEGER"),
        bigquery.SchemaField("missing_title", "INTEGER"),
        bigquery.SchemaField("missing_company", "INTEGER"),
        bigquery.SchemaField("missing_city", "INTEGER"),
        bigquery.SchemaField("missing_posted_date", "INTEGER"),
        bigquery.SchemaField("salary_coverage_count", "INTEGER"),
        bigquery.SchemaField("salary_coverage_pct", "FLOAT"),
        bigquery.SchemaField("contract_type_coverage_count", "INTEGER"),
        bigquery.SchemaField("contract_type_coverage_pct", "FLOAT"),
        bigquery.SchemaField("low_salary_candidates", "INTEGER"),
        bigquery.SchemaField("high_salary_candidates", "INTEGER"),
        bigquery.SchemaField("invalid_salary_ranges", "INTEGER"),
        bigquery.SchemaField("stale_jobs", "INTEGER"),
        bigquery.SchemaField("stale_jobs_pct", "FLOAT"),
        bigquery.SchemaField("invalid_posted_dates", "INTEGER"),
        bigquery.SchemaField("future_posted_dates", "INTEGER"),
        bigquery.SchemaField("completeness_score", "FLOAT"),
        bigquery.SchemaField("validity_score", "FLOAT"),
        bigquery.SchemaField("uniqueness_score", "FLOAT"),
        bigquery.SchemaField("timeliness_score", "FLOAT"),
        bigquery.SchemaField("overall_quality_score", "FLOAT"),
        bigquery.SchemaField("quality_status", "STRING"),
        bigquery.SchemaField("publish_threshold", "FLOAT"),
        bigquery.SchemaField("publishable_jobs", "INTEGER"),
    ]

    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema_update_options=[
            bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION,
        ],
    )

    print(f"Writing data quality report to {table_id}...")
    load_job = client.load_table_from_json(
        [report],
        table_id,
        job_config=job_config,
    )
    load_job.result()
    print("Data quality report saved to BigQuery!")


def main():
    jobs = load_jobs()
    run_id = get_pipeline_run_id()
    publish_threshold = get_quality_publish_threshold()
    now = datetime.now(timezone.utc)

    curated_jobs, evaluations = score_jobs(
        jobs,
        run_id,
        now,
        publish_threshold,
    )
    report = calculate_quality_metrics(
        jobs,
        evaluations,
        run_id,
        now,
        publish_threshold,
    )

    save_curated_jobs(curated_jobs)
    print_report(report, publish_threshold)
    write_to_bigquery(report)


if __name__ == "__main__":
    main()
