import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from clean_jobs import normalize_job_location  # noqa: E402


CONFIG = {"country": "Canada", "location": "Toronto"}


class TorontoLocationTests(unittest.TestCase):
    def assert_toronto(self, display_name, area=None):
        result = normalize_job_location(
            {"location": display_name, "location_area": area or []},
            CONFIG,
        )
        self.assertEqual(
            result,
            {"city": "Toronto", "province": "Ontario", "country": "Canada"},
        )

    def test_toronto_display_name(self):
        self.assert_toronto("Toronto, Ontario")

    def test_north_york_display_name(self):
        self.assert_toronto("North York, Toronto")

    def test_etobicoke_display_name(self):
        self.assert_toronto("Etobicoke, Toronto")

    def test_city_of_toronto_sublocation(self):
        self.assert_toronto("Toronto Dominion Centre, City of Toronto")

    def test_structured_toronto_hierarchy_takes_precedence(self):
        self.assert_toronto(
            "North York, Ontario",
            ["Canada", "Ontario", "Toronto", "North York"],
        )

    def test_unrelated_municipality_is_not_normalized_as_toronto(self):
        result = normalize_job_location(
            {
                "location": "Markham, Ontario",
                "location_area": ["Canada", "Ontario", "York Region", "Markham"],
            },
            CONFIG,
        )

        self.assertEqual(result["city"], "Markham")
        self.assertNotEqual(result["city"], "Toronto")


if __name__ == "__main__":
    unittest.main()
