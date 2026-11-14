import unittest

from malenia.resources import GIB, classify_memory


class ResourceClassificationTests(unittest.TestCase):
    def test_emergency_for_very_low_available_memory(self):
        self.assertEqual(classify_memory(16 * GIB, int(1.5 * GIB)), ("emergency", 1))

    def test_economy_for_low_available_memory(self):
        self.assertEqual(classify_memory(16 * GIB, 3 * GIB), ("economy", 1))

    def test_normal_for_healthy_available_memory(self):
        self.assertEqual(classify_memory(16 * GIB, 8 * GIB), ("normal", 2))

    def test_unknown_memory_is_conservative(self):
        self.assertEqual(classify_memory(0, 0), ("economy", 1))


if __name__ == "__main__":
    unittest.main()
