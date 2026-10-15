"""Unit tests for tool_downloader module."""

from pathlib import Path
import tempfile
import unittest

from src.core.tool_downloader import acquire_tools_from_system, download_and_extract_tools


class TestToolDownloader(unittest.TestCase):
    def test_download_and_extract_already_present(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir)
            ffmpeg = target / "ffmpeg.exe"
            ffprobe = target / "ffprobe.exe"
            # Write 2MB dummy files
            ffmpeg.write_bytes(b"\x00" * (2 * 1024 * 1024))
            ffprobe.write_bytes(b"\x00" * (2 * 1024 * 1024))

            res = download_and_extract_tools(target)
            self.assertTrue(res)

    def test_cancel_check(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir)
            # Immediate cancel
            res = download_and_extract_tools(target, cancel_check=lambda: True)
            self.assertFalse(res)


if __name__ == "__main__":
    unittest.main()

