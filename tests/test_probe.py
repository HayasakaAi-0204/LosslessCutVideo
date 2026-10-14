"""Unit tests for probe module."""

import unittest
from src.core.probe import parse_ffprobe_json, parse_keyframe_csv


class TestProbe(unittest.TestCase):
    def test_parse_ffprobe_json(self):
        sample_json = """{
            "format": {
                "duration": "125.500000",
                "size": "10485760",
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2"
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "60/1"
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac"
                }
            ]
        }"""
        info = parse_ffprobe_json(sample_json)
        self.assertEqual(info["duration"], 125.5)
        self.assertEqual(info["size"], 10485760)
        self.assertEqual(info["video_codec"], "h264")
        self.assertEqual(info["width"], 1920)
        self.assertEqual(info["height"], 1080)
        self.assertEqual(info["fps"], 60.0)
        self.assertEqual(info["audio_tracks_count"], 1)
        self.assertEqual(info["audio_codecs"], ["aac"])
        self.assertEqual(len(info["audio_tracks"]), 1)
        self.assertEqual(info["audio_tracks"][0]["codec"], "aac")
        self.assertEqual(len(info["tracks"]), 2)
        self.assertEqual(info["tracks"][0]["codec_type"], "video")
        self.assertEqual(info["tracks"][1]["codec_type"], "audio")

    def test_parse_keyframe_csv(self):
        sample_csv = """0.000000,1
0.033333,0
0.066666,0
1.000000,1
1.033333,0
2.500000,1"""
        keyframes = parse_keyframe_csv(sample_csv)
        self.assertEqual(keyframes, [0.0, 1.0, 2.5])

    def test_parse_keyframe_csv_single_column(self):
        sample_csv = """0.0000
1.0000
2.5000"""
        keyframes = parse_keyframe_csv(sample_csv)
        self.assertEqual(keyframes, [0.0, 1.0, 2.5])

    def test_parse_keyframe_csv_zero_entry(self):
        sample_csv = """0
1.0000
2.5000"""
        keyframes = parse_keyframe_csv(sample_csv)
        self.assertEqual(keyframes, [0.0, 1.0, 2.5])

    def test_parse_ffprobe_json_na_duration(self):
        sample_json = """{
            "format": {
                "duration": "N/A",
                "size": "N/A",
                "format_name": "mpegts"
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "duration": "N/A"
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "duration": "45.200000"
                }
            ]
        }"""
        info = parse_ffprobe_json(sample_json)
        # Should fallback to audio stream duration 45.2 without crashing
        self.assertEqual(info["duration"], 45.2)
        self.assertEqual(info["size"], 0)


if __name__ == "__main__":
    unittest.main()

