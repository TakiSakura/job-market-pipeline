import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

import pipeline  # noqa: E402


class PipelineOrchestrationTests(unittest.TestCase):
    def test_step_order_and_run_id_propagation(self):
        calls = []
        local_logs = []
        bigquery_logs = []

        def record_step(step_name, script_name, run_id):
            calls.append((step_name, script_name, run_id))

        with (
            patch.object(pipeline.uuid, "uuid4", return_value="shared-run-id"),
            patch.object(pipeline, "run_step", side_effect=record_step),
            patch.object(pipeline, "load_record_count", side_effect=[50, 46]),
            patch.object(pipeline, "append_run_log", side_effect=local_logs.append),
            patch.object(
                pipeline,
                "write_run_log_to_bigquery",
                side_effect=bigquery_logs.append,
            ),
        ):
            pipeline.main()

        self.assertEqual(
            [script for _, script, _ in calls],
            [
                "main.py",
                "load_raw_bigquery.py",
                "clean_jobs.py",
                "data_quality.py",
                "load_curated_bigquery.py",
                "load_bigquery.py",
                "load_observations_bigquery.py",
                "track_history.py",
            ],
        )
        self.assertTrue(all(run_id == "shared-run-id" for _, _, run_id in calls))
        self.assertEqual(local_logs[0]["records_extracted"], 50)
        self.assertEqual(local_logs[0]["records_clean"], 46)
        self.assertEqual(local_logs[0]["status"], "SUCCESS")
        self.assertEqual(bigquery_logs, local_logs)

    def test_extract_failure_does_not_count_stale_files(self):
        local_logs = []

        with (
            patch.object(pipeline.uuid, "uuid4", return_value="failed-run-id"),
            patch.object(
                pipeline,
                "run_step",
                side_effect=subprocess.CalledProcessError(1, "main.py"),
            ),
            patch.object(pipeline, "load_record_count") as load_count,
            patch.object(pipeline, "append_run_log", side_effect=local_logs.append),
            patch.object(pipeline, "write_run_log_to_bigquery"),
            self.assertRaises(SystemExit),
        ):
            pipeline.main()

        load_count.assert_not_called()
        self.assertEqual(local_logs[0]["records_extracted"], 0)
        self.assertEqual(local_logs[0]["records_clean"], 0)
        self.assertEqual(local_logs[0]["failed_step"], "EXTRACT")


if __name__ == "__main__":
    unittest.main()
