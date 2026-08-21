import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery

from pipeline_config import (
    PIPELINE_RUN_ID_ENV,
    PROJECT_ID,
    get_quality_publish_threshold,
)
from run_control import mark_extract_failed, mark_raw_loaded, start_ingestion_run


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
DATA_DIR = ROOT_DIR / "data"

RAW_PATH = DATA_DIR / "raw_jobs.json"
CLEAN_PATH = DATA_DIR / "clean_jobs.json"
RUN_LOG_PATH = DATA_DIR / "pipeline_runs.jsonl"

PYTHON = sys.executable


def utc_now():
    return datetime.now(timezone.utc)


def load_record_count(path):
    if not path.exists():
        return 0

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return len(data)

        return 0

    except Exception:
        return 0


def append_run_log(record):
    RUN_LOG_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(RUN_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                record,
                ensure_ascii=False
            )
            + "\n"
        )


def subprocess_environment(run_id):
    environment = os.environ.copy()
    environment[PIPELINE_RUN_ID_ENV] = run_id
    return environment


def run_step(step_name, script_name, run_id):
    script_path = SRC_DIR / script_name

    print("\n" + "=" * 60)
    print(f"STEP: {step_name}")
    print("=" * 60)

    subprocess.run(
        [PYTHON, str(script_path)],
        check=True,
        env=subprocess_environment(run_id),
    )

    print(f"\n[OK] {step_name} completed")


def write_run_log_to_bigquery(run_record):
    print("\n" + "=" * 60)
    print("STEP: BIGQUERY RUN LOG")
    print("=" * 60)

    try:
        subprocess.run(
            [
                PYTHON,
                str(SRC_DIR / "log_run_bigquery.py"),
                json.dumps(run_record)
            ],
            check=True,
            env=subprocess_environment(run_record["run_id"]),
        )

        print(
            "\n[OK] BIGQUERY RUN LOG completed"
        )

    except subprocess.CalledProcessError as error:
        print(
            "\n[WARNING] Failed to write pipeline run "
            "log to BigQuery."
        )

        print(
            f"Logging process exited with code "
            f"{error.returncode}."
        )


def main():
    run_id = str(uuid.uuid4())
    started_at = utc_now()

    status = "EXTRACTING"
    error_message = None
    failed_step = None
    control_started = False

    records_extracted = 0
    records_clean = 0
    publish_threshold = get_quality_publish_threshold()

    print("\nJOB MARKET DATA PIPELINE")
    print("=" * 60)

    print(f"Run ID: {run_id}")

    print(
        f"Pipeline started at: "
        f"{started_at.isoformat(timespec='seconds')}"
    )

    try:
        control_client = bigquery.Client(project=PROJECT_ID)
        start_ingestion_run(
            control_client,
            run_id,
            started_at,
            publish_threshold,
        )
        control_started = True

        # -------------------------
        # STEP 1: EXTRACT
        # -------------------------

        failed_step = "EXTRACT"

        run_step(
            "EXTRACT",
            "main.py",
            run_id,
        )

        records_extracted = load_record_count(
            RAW_PATH
        )

        # -------------------------
        # STEP 2: BIGQUERY RAW
        # -------------------------

        failed_step = "BIGQUERY_RAW"

        run_step(
            "BIGQUERY RAW",
            "load_raw_bigquery.py",
            run_id,
        )

        mark_raw_loaded(
            control_client,
            run_id,
            utc_now(),
            records_extracted,
        )

        status = "RAW_LOADED"
        failed_step = None

    except subprocess.CalledProcessError as error:
        status = "EXTRACT_FAILED"

        error_message = (
            f"Step {failed_step} failed "
            f"with exit code {error.returncode}"
        )

    except Exception as error:
        status = "EXTRACT_FAILED"
        error_message = str(error)

    if status == "EXTRACT_FAILED" and control_started:
        try:
            mark_extract_failed(
                control_client,
                run_id,
                utc_now(),
                error_message,
            )
        except Exception as control_error:
            print(
                "[WARNING] Failed to record extraction failure in run control: "
                f"{control_error}"
            )

    finished_at = utc_now()

    duration = (
        finished_at - started_at
    ).total_seconds()

    run_record = {
        "run_id": run_id,
        "started_at": started_at.isoformat(
            timespec="seconds"
        ),
        "finished_at": finished_at.isoformat(
            timespec="seconds"
        ),
        "status": status,
        "duration_seconds": round(duration, 2),
        "records_extracted": records_extracted,
        "records_clean": records_clean,
        "failed_step": failed_step,
        "error_message": error_message
    }

    # Local fallback log
    append_run_log(
        run_record
    )

    # BigQuery run log
    write_run_log_to_bigquery(
        run_record
    )

    print("\n" + "=" * 60)

    if status == "RAW_LOADED":
        print("INGESTION RAW_LOADED")
    else:
        print("INGESTION EXTRACT_FAILED")

    print("=" * 60)

    print(f"Run ID: {run_id}")

    print(
        f"Finished at: "
        f"{finished_at.isoformat(timespec='seconds')}"
    )

    print(
        f"Duration: {duration:.2f} seconds"
    )

    print(
        f"Records extracted: "
        f"{records_extracted}"
    )

    print(
        f"Records clean: "
        f"{records_clean}"
    )

    print(
        f"Local fallback run log:\n"
        f"{RUN_LOG_PATH}"
    )

    if status == "EXTRACT_FAILED":
        print(
            f"Failed step: {failed_step}"
        )

        print(
            f"Error: {error_message}"
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
