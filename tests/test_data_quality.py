import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from data_quality import (  # noqa: E402
    calculate_quality_metrics,
    get_quality_status,
    passes_publish_gate,
    score_job,
    score_jobs,
)


NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


def job_fixture(**overrides):
    job = {
        "job_id": "123",
        "title": "Data Analyst",
        "company": "Example Inc.",
        "city": "Toronto",
        "province": "Ontario",
        "country": "Canada",
        "posted_date": (NOW - timedelta(days=10)).isoformat(),
        "salary_min": None,
        "salary_max": None,
        "description": "Analyze product and business data.",
        "category": "IT Jobs",
        "contract_type": None,
        "source": "Adzuna",
        "job_url": "https://www.adzuna.ca/details/123",
    }
    job.update(overrides)
    return job


class RowQualityTests(unittest.TestCase):
    def test_complete_recent_job_scores_100_without_optional_fields(self):
        scored = score_job(job_fixture(), "run-1", NOW, 80)

        self.assertEqual(scored["quality_score"], 100)
        self.assertEqual(scored["quality_flags"], [])
        self.assertEqual(scored["quality_status"], "PASS")
        self.assertTrue(scored["is_publishable"])

    def test_known_quality_flags(self):
        stale = score_job(
            job_fixture(posted_date=(NOW - timedelta(days=100)).isoformat()),
            "run-1",
            NOW,
            80,
        )
        low_salary = score_job(
            job_fixture(salary_min=10000), "run-1", NOW, 80
        )
        invalid_range = score_job(
            job_fixture(salary_min=90000, salary_max=50000),
            "run-1",
            NOW,
            80,
        )
        missing_critical = score_job(
            job_fixture(title=None), "run-1", NOW, 80
        )

        self.assertIn("STALE_JOB", stale["quality_flags"])
        self.assertIn("LOW_SALARY_OUTLIER", low_salary["quality_flags"])
        self.assertIn("INVALID_SALARY_RANGE", invalid_range["quality_flags"])
        self.assertFalse(invalid_range["is_publishable"])
        self.assertIn("MISSING_CRITICAL_FIELD", missing_critical["quality_flags"])
        self.assertFalse(missing_critical["is_publishable"])

    def test_scores_stay_between_zero_and_100(self):
        examples = [
            job_fixture(),
            job_fixture(posted_date="not-a-date", job_url="bad"),
            job_fixture(
                job_id=None,
                title=None,
                company=None,
                city=None,
                province=None,
                country=None,
                posted_date=None,
                description=None,
                source=None,
                job_url=None,
            ),
        ]

        for job in examples:
            score = score_job(job, "run-1", NOW, 80)["quality_score"]
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_publish_status_boundary(self):
        self.assertEqual(get_quality_status(79), "REVIEW")
        self.assertEqual(get_quality_status(80), "PASS")
        self.assertFalse(passes_publish_gate(79, [], 80))
        self.assertTrue(passes_publish_gate(80, [], 80))
        self.assertFalse(
            passes_publish_gate(100, ["MISSING_CRITICAL_FIELD"], 80)
        )

    def test_job_older_than_180_days_is_not_publishable(self):
        old_job = job_fixture(
            posted_date=(NOW - timedelta(days=181)).isoformat()
        )
        scored = score_job(old_job, "run-1", NOW, 80)

        self.assertEqual(scored["quality_score"], 80)
        self.assertEqual(scored["quality_status"], "PASS")
        self.assertIn("STALE_JOB", scored["quality_flags"])
        self.assertFalse(scored["is_publishable"])

    def test_180_day_boundary_does_not_trigger_hard_age_gate(self):
        boundary_job = job_fixture(
            posted_date=(NOW - timedelta(days=180)).isoformat()
        )
        scored = score_job(boundary_job, "run-1", NOW, 80)

        self.assertEqual(scored["quality_score"], 86)
        self.assertIn("STALE_JOB", scored["quality_flags"])
        self.assertTrue(scored["is_publishable"])

    def test_scoring_does_not_add_or_remove_duplicate_ids(self):
        jobs = [job_fixture(), job_fixture(title="Duplicate source row")]
        curated, evaluations = score_jobs(jobs, "run-1", NOW, 80)
        report = calculate_quality_metrics(
            jobs, evaluations, "run-1", NOW, 80
        )

        self.assertEqual(len(curated), len(jobs))
        self.assertEqual([job["job_id"] for job in curated], ["123", "123"])
        self.assertEqual(report["duplicate_job_ids"], 1)
        self.assertEqual(report["uniqueness_score"], 50.0)


if __name__ == "__main__":
    unittest.main()
