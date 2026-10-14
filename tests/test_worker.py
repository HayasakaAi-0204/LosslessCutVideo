"""Unit tests for worker module parsing logic."""

import unittest
from src.core.worker import parse_time_to_seconds, parse_ffmpeg_progress


class TestWorker(unittest.TestCase):
    def test_parse_time_to_seconds(self):
        self.assertEqual(parse_time_to_seconds("00:00:10.50"), 10.5)
        self.assertEqual(parse_time_to_seconds("00:01:30.00"), 90.0)
        self.assertEqual(parse_time_to_seconds("01:00:00.00"), 3600.0)

    def test_parse_ffmpeg_progress(self):
        line = "frame=  120 fps=0.0 q=-1.0 size=    1024kB time=00:00:05.00 bitrate=1677.7kbits/s speed=9.98x"
        pct = parse_ffmpeg_progress(line, total_duration=10.0)
        self.assertEqual(pct, 50.0)

    def test_parse_ffmpeg_progress_invalid(self):
        line = "Opening an input file: test.mp4"
        self.assertIsNone(parse_ffmpeg_progress(line, total_duration=10.0))


if __name__ == "__main__":
    unittest.main()

