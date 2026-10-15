"""Unit tests for system stability and anti-crash protections."""

import os
import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main import apply_system_stability_protections, setup_exception_handler


class TestSystemStability(unittest.TestCase):
    def test_apply_system_stability_protections(self):
        """Verify environment variables and multimedia backend configuration."""
        apply_system_stability_protections()

        # Check required anti-hook & stability environment variables
        expected_keys = [
            "NV_DISABLE_OVERLAY",
            "DISABLE_NV_OVERLAY",
            "GFE_DISABLE_OVERLAY",
            "SP_DISABLE_OVERLAY",
            "DISABLE_OVERLAYS",
            "DISCORD_NO_HOOK",
            "DISABLE_DISCORD_HOOK",
            "OBS_DISABLE_HOOK",
            "RTSS_DISABLE_HOOK",
            "QT_MEDIA_BACKEND",
        ]
        for key in expected_keys:
            self.assertIn(key, os.environ, f"Missing stability env var: {key}")
            self.assertTrue(len(os.environ[key]) > 0)

        # Enforces cross-platform FFmpeg backend for universal codec support (AV1, HEVC, etc.)
        self.assertEqual(os.environ["QT_MEDIA_BACKEND"], "ffmpeg")
        # Enforces software decoding fallback to prevent D3D11VA black screens
        self.assertIn("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", os.environ)
        self.assertEqual(os.environ["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"], "")

    def test_setup_exception_handler(self):
        """Verify global exception hook installation."""
        orig_hook = sys.excepthook
        try:
            setup_exception_handler()
            self.assertIsNotNone(sys.excepthook)
            self.assertNotEqual(sys.excepthook, sys.__excepthook__)
        finally:
            sys.excepthook = orig_hook


if __name__ == "__main__":
    unittest.main()
