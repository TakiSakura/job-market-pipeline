import os


PROJECT_ID = "weekly-market-trend"
DATASET_ID = "job_market"
BIGQUERY_LOCATION = "northamerica-northeast2"

PIPELINE_RUN_ID_ENV = "PIPELINE_RUN_ID"
QUALITY_PUBLISH_THRESHOLD_ENV = "QUALITY_PUBLISH_THRESHOLD"
DEFAULT_QUALITY_PUBLISH_THRESHOLD = 80.0
RUN_CONTROL_TABLE = "job_run_control"
AUTO_TRANSFORM_ENV = "AUTO_TRANSFORM"
AUTO_TRANSFORM_TRUE_VALUES = {"1", "true", "yes"}


def get_pipeline_run_id():
    run_id = os.getenv(PIPELINE_RUN_ID_ENV, "").strip()
    if not run_id:
        raise RuntimeError(
            f"{PIPELINE_RUN_ID_ENV} is required for pipeline traceability."
        )
    return run_id


def get_quality_publish_threshold():
    raw_value = os.getenv(
        QUALITY_PUBLISH_THRESHOLD_ENV,
        str(DEFAULT_QUALITY_PUBLISH_THRESHOLD),
    )

    try:
        threshold = float(raw_value)
    except ValueError as error:
        raise RuntimeError(
            f"{QUALITY_PUBLISH_THRESHOLD_ENV} must be a number from 0 to 100."
        ) from error

    if not 0 <= threshold <= 100:
        raise RuntimeError(
            f"{QUALITY_PUBLISH_THRESHOLD_ENV} must be from 0 to 100."
        )

    return threshold


def get_auto_transform():
    return os.getenv(AUTO_TRANSFORM_ENV, "false").strip().casefold() in (
        AUTO_TRANSFORM_TRUE_VALUES
    )
