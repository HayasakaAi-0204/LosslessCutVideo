"""Unit tests for config module."""

from pathlib import Path
import unittest

from src.core.config import get_project_root, get_tools_dir, get_ffmpeg_path, get_ffprobe_path, validate_tools


class TestConfig(unittest.TestCase):
    def test_project_root(self):
        root = get_project_root()
        self.assertTrue(root.exists())
        self.assertTrue((root / "GEMINI.md").exists())

    def test_tools_dir(self):
        tools = get_tools_dir()
        self.assertTrue(tools.exists())
        self.assertEqual(tools.name, "tools")

    def test_tool_paths(self):
        ffmpeg_p = get_ffmpeg_path()
        ffprobe_p = get_ffprobe_path()
        self.assertIsInstance(ffmpeg_p, Path)
        self.assertIsInstance(ffprobe_p, Path)

    def test_validate_tools_returns_dict(self):
        status = validate_tools()
        self.assertIn("ffmpeg", status)
        self.assertIn("ffprobe", status)
        self.assertIsInstance(status["ffmpeg"], bool)
        self.assertIsInstance(status["ffprobe"], bool)


if __name__ == "__main__":
    unittest.main()

