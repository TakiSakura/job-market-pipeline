from pathlib import Path

from google.cloud import bigquery

from pipeline_config import BIGQUERY_LOCATION, PROJECT_ID


ROOT_DIR = Path(__file__).resolve().parents[1]
SQL_FILES = [
    ROOT_DIR / "sql" / "setup" / "001_elt_resources.sql",
    ROOT_DIR / "sql" / "routines" / "job_run_rows.sql",
    ROOT_DIR / "sql" / "routines" / "process_job_run.sql",
    ROOT_DIR / "sql" / "views" / "published_jobs.sql",
]


def main():
    client = bigquery.Client(project=PROJECT_ID)
    for path in SQL_FILES:
        print(f"Applying {path.relative_to(ROOT_DIR)}...")
        client.query(
            path.read_text(encoding="utf-8"),
            location=BIGQUERY_LOCATION,
        ).result()
        print(f"Applied {path.relative_to(ROOT_DIR)}")


if __name__ == "__main__":
    main()
