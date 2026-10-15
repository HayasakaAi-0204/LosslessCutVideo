"""Unit tests for simplified player speed controls (0.25x to 2.00x)."""

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ui.player_widget import SPEED_PRESETS


class TestPlayerSpeed(unittest.TestCase):
    def test_speed_presets_range(self):
        """Verify SPEED_PRESETS starts at 0.25x and ends at 2.0x with 0.25 step."""
        self.assertEqual(SPEED_PRESETS[0], 0.25)
        self.assertEqual(SPEED_PRESETS[-1], 2.0)
        self.assertIn(1.0, SPEED_PRESETS)
        expected = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
        self.assertEqual(SPEED_PRESETS, expected)


if __name__ == "__main__":
    unittest.main()

