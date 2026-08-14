import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

import main as extractor  # noqa: E402


def api_job(job_id, location=None):
    return {
        "id": str(job_id),
        "title": "Data Analyst",
        "company": {"display_name": "Example Inc."},
        "location": location
        or {
            "display_name": "Toronto, Ontario",
            "area": ["Canada", "Ontario", "Toronto"],
        },
        "created": "2026-08-01T12:00:00Z",
        "description": "Analyze data.",
        "redirect_url": f"https://www.adzuna.ca/details/{job_id}",
    }


class FakeResponse:
    def __init__(self, results=None, status_code=200):
        self.status_code = status_code
        self._results = results or []

    def json(self):
        return {"results": self._results}


class RequestSequence:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        return next(self.responses)


def config(max_pages=3, results_per_page=2):
    return {
        "country": "Canada",
        "location": "Toronto",
        "role": "Data Analyst",
        "results_per_page": results_per_page,
        "max_pages": max_pages,
    }


class PaginationTests(unittest.TestCase):
    def test_multiple_pages_are_combined_and_urls_increment(self):
        request = RequestSequence([
            FakeResponse([api_job(1), api_job(2)]),
            FakeResponse([api_job(3)]),
        ])

        jobs, pages = extractor.fetch_all_jobs(
            config(), "app-id", "app-key", request
        )

        self.assertEqual([job["id"] for job in jobs], ["1", "2", "3"])
        self.assertEqual(pages, 2)
        self.assertTrue(request.urls[0].endswith("/search/1"))
        self.assertTrue(request.urls[1].endswith("/search/2"))

    def test_duplicate_ids_across_pages_are_deduplicated(self):
        normalized = [
            extractor.normalize_job(api_job(1)),
            extractor.normalize_job(api_job(2)),
            extractor.normalize_job(api_job(2)),
            extractor.normalize_job(api_job(3)),
        ]

        unique = extractor.deduplicate_jobs(normalized)

        self.assertEqual([job["job_id"] for job in unique], ["1", "2", "3"])

    def test_empty_later_page_stops_pagination(self):
        request = RequestSequence([
            FakeResponse([api_job(1), api_job(2)]),
            FakeResponse([]),
            FakeResponse([api_job(3)]),
        ])

        jobs, pages = extractor.fetch_all_jobs(
            config(), "app-id", "app-key", request
        )

        self.assertEqual(len(jobs), 2)
        self.assertEqual(pages, 2)
        self.assertEqual(len(request.urls), 2)

    def test_max_pages_is_respected(self):
        request = RequestSequence([
            FakeResponse([api_job(1), api_job(2)]),
            FakeResponse([api_job(3), api_job(4)]),
            FakeResponse([api_job(5), api_job(6)]),
        ])

        jobs, pages = extractor.fetch_all_jobs(
            config(max_pages=2), "app-id", "app-key", request
        )

        self.assertEqual(len(jobs), 4)
        self.assertEqual(pages, 2)
        self.assertEqual(len(request.urls), 2)

    def test_page_one_failure_fails_extraction(self):
        request = RequestSequence([FakeResponse(status_code=500)])

        with self.assertRaisesRegex(RuntimeError, "page 1 returned HTTP 500"):
            extractor.fetch_all_jobs(config(), "app-id", "app-key", request)

    def test_later_page_failure_does_not_return_partial_results(self):
        request = RequestSequence([
            FakeResponse([api_job(1), api_job(2)]),
            FakeResponse(status_code=503),
        ])

        with self.assertRaisesRegex(RuntimeError, "page 2 returned HTTP 503"):
            extractor.fetch_all_jobs(config(), "app-id", "app-key", request)

    def test_single_page_configuration(self):
        request = RequestSequence([
            FakeResponse([api_job(1), api_job(2)]),
            FakeResponse([api_job(3)]),
        ])

        jobs, pages = extractor.fetch_all_jobs(
            config(max_pages=1), "app-id", "app-key", request
        )

        self.assertEqual(len(jobs), 2)
        self.assertEqual(pages, 1)
        self.assertEqual(len(request.urls), 1)

    def test_structured_location_is_preserved_in_raw_schema(self):
        normalized = extractor.normalize_job(api_job(1))

        self.assertEqual(normalized["location"], "Toronto, Ontario")
        self.assertEqual(
            normalized["location_area"],
            ["Canada", "Ontario", "Toronto"],
        )


if __name__ == "__main__":
    unittest.main()
