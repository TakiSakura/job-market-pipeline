import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from pipeline_config import get_auto_transform  # noqa: E402


class AutoTransformConfigTests(unittest.TestCase):
    def test_auto_transform_defaults_to_false(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(get_auto_transform())

    def test_supported_true_values_are_case_insensitive(self):
        for value in ("true", "TRUE", "1", "yes", "YeS"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"AUTO_TRANSFORM": value}):
                    self.assertTrue(get_auto_transform())


if __name__ == "__main__":
    unittest.main()
