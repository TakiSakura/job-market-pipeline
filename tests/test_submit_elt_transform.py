import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

import submit_elt_transform  # noqa: E402


class SubmitEltTransformTests(unittest.TestCase):
    def test_parameterized_call_is_submitted_once_without_waiting(self):
        client = MagicMock()
        lookup_job = MagicMock()
        lookup_job.result.return_value = [{"transform_job_id": None}]
        transform_job = MagicMock()
        transform_job.job_id = "query-job-id"
        record_job = MagicMock()
        record_job.result.return_value = None
        client.query.side_effect = [lookup_job, transform_job, record_job]

        job_id, submitted = submit_elt_transform.submit_elt_transform(
            client,
            "run-1",
        )

        self.assertEqual(job_id, "query-job-id")
        self.assertTrue(submitted)
        call_queries = [
            call.args[0]
            for call in client.query.call_args_list
            if "CALL" in call.args[0]
        ]
        self.assertEqual(
            call_queries,
            [
                "CALL `weekly-market-trend.job_market.process_job_run`(@run_id)"
            ],
        )
        call_config = client.query.call_args_list[1].kwargs["job_config"]
        parameters = {
            parameter.name: parameter.value
            for parameter in call_config.query_parameters
        }
        self.assertEqual(parameters, {"run_id": "run-1"})
        transform_job.result.assert_not_called()
        record_sql = client.query.call_args_list[2].args[0]
        self.assertIn("transform_job_id = @transform_job_id", record_sql)
        self.assertNotIn("transform_status = 'SUCCESS'", record_sql)
        record_config = client.query.call_args_list[2].kwargs["job_config"]
        record_parameters = {
            parameter.name: parameter.value
            for parameter in record_config.query_parameters
        }
        self.assertEqual(record_parameters["run_id"], "run-1")
        self.assertEqual(record_parameters["transform_job_id"], "query-job-id")

    def test_existing_job_id_prevents_duplicate_submission(self):
        client = MagicMock()
        lookup_job = MagicMock()
        lookup_job.result.return_value = [
            {"transform_job_id": "existing-query-job-id"}
        ]
        client.query.return_value = lookup_job

        job_id, submitted = submit_elt_transform.submit_elt_transform(
            client,
            "run-1",
        )

        self.assertEqual(job_id, "existing-query-job-id")
        self.assertFalse(submitted)
        self.assertEqual(client.query.call_count, 1)
        self.assertNotIn("CALL", client.query.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
