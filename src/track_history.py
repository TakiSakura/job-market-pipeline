
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]

CLEAN_PATH = ROOT_DIR / "data" / "clean_jobs.json"
STATE_PATH = ROOT_DIR / "data" / "job_state.json"
OBSERVATIONS_PATH = ROOT_DIR / "data" / "job_observations.jsonl"


def load_json(path, default=None):
    """
    Load a JSON file.
    Return default value if the file does not exist.
    """
    if not path.exists():
        return default

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    """
    Save Python data as formatted JSON.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


def append_observation(path, observation):
    """
    Append one observation as a JSON line.
    """
    with open(path, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                observation,
                ensure_ascii=False
            )
            + "\n"
        )


def main():

    clean_jobs = load_json(
        CLEAN_PATH,
        default=[]
    )

    existing_state = load_json(
        STATE_PATH,
        default=[]
    )

    # Convert state list into dictionary:
    # job_id -> job
    state_by_id = {
        job["job_id"]: job
        for job in existing_state
        if job.get("job_id")
    }

    observed_at = datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")

    new_jobs = 0
    existing_jobs = 0
    skipped_jobs = 0

    for job in clean_jobs:

        job_id = job.get("job_id")

        if not job_id:
            skipped_jobs += 1
            continue

        # -------------------------
        # NEW JOB
        # -------------------------
        if job_id not in state_by_id:

            state_record = {
                **job,
                "first_seen_at": observed_at,
                "last_seen_at": observed_at,
                "is_active": True
            }

            state_by_id[job_id] = state_record

            new_jobs += 1

        # -------------------------
        # EXISTING JOB
        # -------------------------
        else:

            previous_record = state_by_id[job_id]

            first_seen_at = previous_record[
                "first_seen_at"
            ]

            state_record = {
                **job,
                "first_seen_at": first_seen_at,
                "last_seen_at": observed_at,
                "is_active": True
            }

            state_by_id[job_id] = state_record

            existing_jobs += 1

        # -------------------------
        # APPEND OBSERVATION
        # -------------------------
        observation = {
            "observed_at": observed_at,
            **job
        }

        append_observation(
            OBSERVATIONS_PATH,
            observation
        )

    # Convert dictionary back to list
    updated_state = list(
        state_by_id.values()
    )

    save_json(
        STATE_PATH,
        updated_state
    )

    print("Historical Tracking")
    print("-------------------")

    print(
        f"Observed at: {observed_at}"
    )

    print(
        f"Jobs in current clean dataset: "
        f"{len(clean_jobs)}"
    )

    print(
        f"New jobs: {new_jobs}"
    )

    print(
        f"Existing jobs: {existing_jobs}"
    )

    print(
        f"Skipped jobs: {skipped_jobs}"
    )

    print(
        f"Total jobs in state: "
        f"{len(updated_state)}"
    )

    print(
        f"\nState saved to:\n{STATE_PATH}"
    )

    print(
        f"\nObservations appended to:\n"
        f"{OBSERVATIONS_PATH}"
    )


if __name__ == "__main__":
    main()