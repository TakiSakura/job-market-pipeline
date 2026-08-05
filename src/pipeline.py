import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


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
    """
    Return the number of records in a JSON array.
    """
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
    """
    Append one pipeline run record as a JSON line.
    """
    with open(RUN_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                record,
                ensure_ascii=False
            )
            + "\n"
        )


def run_step(step_name, script_name):
    """
    Run one pipeline step.

    If the step fails, stop the entire pipeline.
    """

    script_path = SRC_DIR / script_name

    print("\n" + "=" * 60)
    print(f"STEP: {step_name}")
    print("=" * 60)

    subprocess.run(
        [PYTHON, str(script_path)],
        check=True
    )

    print(f"\n✓ {step_name} completed")


def main():

    run_id = str(uuid.uuid4())

    started_at = utc_now()

    status = "RUNNING"
    error_message = None
    failed_step = None

    print("\nJOB MARKET DATA PIPELINE")
    print("=" * 60)

    print(f"Run ID: {run_id}")

    print(
        f"Pipeline started at: "
        f"{started_at.isoformat(timespec='seconds')}"
    )

    try:

        # -------------------------
        # STEP 1: EXTRACT
        # -------------------------

        failed_step = "EXTRACT"

        run_step(
            "EXTRACT",
            "main.py"
        )

        # -------------------------
        # STEP 2: CLEAN
        # -------------------------

        failed_step = "CLEAN"

        run_step(
            "CLEAN",
            "clean_jobs.py"
        )

        # -------------------------
        # STEP 3: HISTORICAL TRACKING
        # -------------------------

        failed_step = "HISTORICAL_TRACKING"

        run_step(
            "HISTORICAL TRACKING",
            "track_history.py"
        )

        status = "SUCCESS"
        failed_step = None

    except subprocess.CalledProcessError as error:

        status = "FAILED"

        error_message = (
            f"Step {failed_step} failed "
            f"with exit code {error.returncode}"
        )

    except Exception as error:

        status = "FAILED"

        error_message = str(error)

    finished_at = utc_now()

    duration = (
        finished_at - started_at
    ).total_seconds()

    # -------------------------
    # RUN METRICS
    # -------------------------

    records_extracted = load_record_count(
        RAW_PATH
    )

    records_clean = load_record_count(
        CLEAN_PATH
    )

    # -------------------------
    # SAVE RUN LOG
    # -------------------------

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

    append_run_log(
        run_record
    )

    # -------------------------
    # FINAL OUTPUT
    # -------------------------

    print("\n" + "=" * 60)

    if status == "SUCCESS":
        print("PIPELINE SUCCESS")
    else:
        print("PIPELINE FAILED")

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
        f"Run log saved to:\n"
        f"{RUN_LOG_PATH}"
    )

    if status == "FAILED":

        print(
            f"Failed step: {failed_step}"
        )

        print(
            f"Error: {error_message}"
        )

        sys.exit(1)


if __name__ == "__main__":
    main()