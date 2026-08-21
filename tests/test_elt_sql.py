import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ROUTINE_PATH = ROOT_DIR / "sql" / "routines" / "process_job_run.sql"
ROWS_PATH = ROOT_DIR / "sql" / "routines" / "job_run_rows.sql"


class EltSqlContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.routine = ROUTINE_PATH.read_text(encoding="utf-8")
        cls.rows = ROWS_PATH.read_text(encoding="utf-8")

    def test_raw_reads_are_scoped_to_requested_run(self):
        self.assertGreaterEqual(
            self.routine.count("WHERE run_id = requested_run_id"),
            5,
        )
        self.assertIn("WHERE raw.run_id = requested_run_id", self.rows)

    def test_deduplication_is_in_bigquery_and_deterministic(self):
        self.assertIn("ROW_NUMBER() OVER", self.rows)
        self.assertIn("PARTITION BY source_job_id", self.rows)
        self.assertIn("ORDER BY page_number, position_in_page", self.rows)

    def test_retry_safe_history_and_quality_records(self):
        self.assertIn(
            "DELETE FROM `weekly-market-trend.job_market.job_observations`",
            self.routine,
        )
        self.assertIn(
            "DELETE FROM `weekly-market-trend.job_market.data_quality_runs`",
            self.routine,
        )
        self.assertIn("MERGE `weekly-market-trend.job_market.jobs_state`", self.routine)
        self.assertNotIn("is_active = FALSE", self.routine)

    def test_transform_status_lifecycle_and_rejections(self):
        for status in ("RAW_LOADED", "TRANSFORMING", "SUCCESS", "TRANSFORM_FAILED"):
            self.assertIn(status, self.routine)
        self.assertIn("actual_raw_count > 0", self.routine)
        self.assertIn("recorded_raw_count = actual_raw_count", self.routine)

    def test_stale_run_guard_precedes_all_transform_mutations(self):
        guard = "run is older than the latest successful current-producing run"
        guard_position = self.routine.index(guard)
        transforming_position = self.routine.index("transform_status = 'TRANSFORMING'")
        curated_delete_position = self.routine.index(
            "DELETE FROM `weekly-market-trend.job_market.curated_jobs`"
        )

        self.assertIn("ORDER BY started_at DESC, run_id DESC", self.routine)
        self.assertIn("requested_run_id = latest_success_run_id", self.routine)
        self.assertLess(guard_position, transforming_position)
        self.assertLess(guard_position, curated_delete_position)

    def test_publish_age_gate_is_separate_from_scoring(self):
        self.assertIn("quality_score >= publish_threshold", self.rows)
        self.assertIn("age_days > 180", self.rows)
        self.assertIn("IF(age_days > 90, ['STALE_JOB']", self.rows)


if __name__ == "__main__":
    unittest.main()
