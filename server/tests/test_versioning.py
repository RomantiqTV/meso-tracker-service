import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.versioning import compare_versions, is_older  # noqa: E402


class CompareVersionsTests(unittest.TestCase):
    def test_numeric_not_lexical(self):
        self.assertEqual(compare_versions("1.2.10", "1.2.9"), 1)         # "10" < "9" lexically, but not numerically
        self.assertEqual(compare_versions("1.2.9", "1.2.10"), -1)

    def test_equal(self):
        self.assertEqual(compare_versions("1.2.3", "1.2.3"), 0)

    def test_missing_trailing_parts_are_zero(self):
        self.assertEqual(compare_versions("1.2", "1.2.0"), 0)
        self.assertEqual(compare_versions("1.2.1", "1.2"), 1)

    def test_different_lengths(self):
        self.assertEqual(compare_versions("2.0", "1.9.9"), 1)


class IsOlderTests(unittest.TestCase):
    def test_older_is_true(self):
        self.assertTrue(is_older("1.0.0", "1.1.0"))

    def test_same_or_newer_is_false(self):
        self.assertFalse(is_older("1.1.0", "1.1.0"))
        self.assertFalse(is_older("1.2.0", "1.1.0"))

    def test_empty_either_side_never_blocks(self):
        self.assertFalse(is_older("", "1.1.0"))
        self.assertFalse(is_older("1.0.0", ""))
        self.assertFalse(is_older("", ""))


if __name__ == "__main__":
    unittest.main()
