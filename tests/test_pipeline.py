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
            patch.object(pipeline.bigquery, "Client") as client_class,
            patch.object(pipeline, "start_ingestion_run") as start_run,
            patch.object(pipeline, "mark_raw_loaded") as mark_raw_loaded,
            patch.object(pipeline, "run_step", side_effect=record_step),
            patch.object(pipeline, "load_record_count", return_value=50),
            patch.object(pipeline, "append_run_log", side_effect=local_logs.append),
            patch.object(
                pipeline,
                "write_run_log_to_bigquery",
                side_effect=bigquery_logs.append,
            ),
        ):
            result = pipeline.main()

        self.assertEqual(
            [script for _, script, _ in calls],
            [
                "main.py",
                "load_raw_bigquery.py",
            ],
        )
        self.assertTrue(all(run_id == "shared-run-id" for _, _, run_id in calls))
        self.assertEqual(local_logs[0]["records_extracted"], 50)
        self.assertEqual(local_logs[0]["records_clean"], 0)
        self.assertEqual(local_logs[0]["status"], "RAW_LOADED")
        self.assertEqual(bigquery_logs, local_logs)
        start_run.assert_called_once()
        mark_raw_loaded.assert_called_once()
        self.assertIs(mark_raw_loaded.call_args.args[0], client_class.return_value)
        self.assertEqual(mark_raw_loaded.call_args.args[1], "shared-run-id")
        self.assertEqual(mark_raw_loaded.call_args.args[3], 50)
        self.assertIsNone(result)

    def test_extract_failure_does_not_count_stale_files(self):
        local_logs = []

        with (
            patch.object(pipeline.uuid, "uuid4", return_value="failed-run-id"),
            patch.object(pipeline.bigquery, "Client"),
            patch.object(pipeline, "start_ingestion_run"),
            patch.object(pipeline, "mark_extract_failed") as mark_failed,
            patch.object(
                pipeline,
                "run_step",
                side_effect=subprocess.CalledProcessError(1, "main.py"),
            ),
            patch.object(pipeline, "load_record_count") as load_count,
            patch.object(pipeline, "append_run_log", side_effect=local_logs.append),
            patch.object(pipeline, "write_run_log_to_bigquery"),
        ):
            with self.assertRaises(SystemExit) as raised:
                pipeline.main()

        load_count.assert_not_called()
        self.assertEqual(local_logs[0]["records_extracted"], 0)
        self.assertEqual(local_logs[0]["records_clean"], 0)
        self.assertEqual(local_logs[0]["failed_step"], "EXTRACT")
        mark_failed.assert_called_once()
        self.assertEqual(raised.exception.code, 1)

    def test_raw_load_failure_retains_current_extract_count(self):
        local_logs = []
        steps = iter([None, subprocess.CalledProcessError(1, "load_raw")])

        def run_step(*_args):
            result = next(steps)
            if result:
                raise result

        with (
            patch.object(pipeline.uuid, "uuid4", return_value="raw-failed-run"),
            patch.object(pipeline.bigquery, "Client"),
            patch.object(pipeline, "start_ingestion_run"),
            patch.object(pipeline, "mark_extract_failed") as mark_failed,
            patch.object(pipeline, "run_step", side_effect=run_step),
            patch.object(pipeline, "load_record_count", return_value=50),
            patch.object(pipeline, "append_run_log", side_effect=local_logs.append),
            patch.object(pipeline, "write_run_log_to_bigquery"),
        ):
            with self.assertRaises(SystemExit) as raised:
                pipeline.main()

        self.assertEqual(local_logs[0]["records_extracted"], 50)
        self.assertEqual(local_logs[0]["records_clean"], 0)
        self.assertEqual(local_logs[0]["failed_step"], "BIGQUERY_RAW")
        self.assertEqual(local_logs[0]["status"], "EXTRACT_FAILED")
        mark_failed.assert_called_once()
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
