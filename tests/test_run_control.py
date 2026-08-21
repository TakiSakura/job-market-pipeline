import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

import run_control  # noqa: E402


NOW = datetime(2026, 8, 21, tzinfo=timezone.utc)


class RunControlTests(unittest.TestCase):
    def client(self):
        client = MagicMock()
        client.query.return_value.result.return_value = None
        return client

    def test_start_records_separate_extract_and_transform_statuses(self):
        client = self.client()
        with patch.object(
            run_control,
            "ensure_run_control_table",
            return_value="project.dataset.job_run_control",
        ):
            run_control.start_ingestion_run(client, "run-1", NOW, 80.0)

        sql = client.query.call_args.args[0]
        self.assertIn("'EXTRACTING'", sql)
        self.assertIn("'PENDING'", sql)
        self.assertIn("MERGE", sql)
        parameters = client.query.call_args.kwargs["job_config"].query_parameters
        values = {parameter.name: parameter.value for parameter in parameters}
        self.assertEqual(values["publish_threshold"], 80.0)

    def test_raw_loaded_records_current_run_count(self):
        client = self.client()
        run_control.mark_raw_loaded(client, "run-1", NOW, 150)

        sql = client.query.call_args.args[0]
        self.assertIn("extract_status = 'RAW_LOADED'", sql)
        parameters = client.query.call_args.kwargs["job_config"].query_parameters
        values = {parameter.name: parameter.value for parameter in parameters}
        self.assertEqual(values["run_id"], "run-1")
        self.assertEqual(values["raw_count"], 150)

    def test_extract_failure_does_not_claim_raw_loaded(self):
        client = self.client()
        run_control.mark_extract_failed(client, "run-1", NOW, "safe message")

        sql = client.query.call_args.args[0]
        self.assertIn("extract_status = 'EXTRACT_FAILED'", sql)
        self.assertIn("raw_loaded_at = NULL", sql)
        self.assertNotIn("RAW_LOADED", sql)


if __name__ == "__main__":
    unittest.main()
