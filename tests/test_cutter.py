"""Unit tests for cutter module."""

from pathlib import Path
import unittest

from src.core.cutter import (
    format_timestamp,
    find_nearest_keyframe,
    generate_default_output_name,
    build_cut_command,
)


class TestCutter(unittest.TestCase):
    def test_format_timestamp(self):
        self.assertEqual(format_timestamp(0.0), "00:00:00.000")
        self.assertEqual(format_timestamp(65.5), "00:01:05.500")
        self.assertEqual(format_timestamp(3661.123), "01:01:01.123")

    def test_find_nearest_keyframe_prev(self):
        keyframes = [0.0, 2.0, 4.0, 6.0, 8.0]
        self.assertEqual(find_nearest_keyframe(3.5, keyframes, mode="prev"), 2.0)
        self.assertEqual(find_nearest_keyframe(4.0, keyframes, mode="prev"), 4.0)
        self.assertEqual(find_nearest_keyframe(0.5, keyframes, mode="prev"), 0.0)

    def test_find_nearest_keyframe_closest(self):
        keyframes = [0.0, 2.0, 4.0, 6.0]
        self.assertEqual(find_nearest_keyframe(3.8, keyframes, mode="closest"), 4.0)
        self.assertEqual(find_nearest_keyframe(2.3, keyframes, mode="closest"), 2.0)

    def test_build_cut_command_validation(self):
        # Validation: start >= end should fail
        with self.assertRaises(ValueError):
            build_cut_command(
                input_path=Path(__file__),
                output_path=Path(__file__).parent / "output.mp4",
                start_sec=10.0,
                end_sec=5.0,
            )

        # Validation: same path should fail (protect source)
        with self.assertRaises(ValueError):
            build_cut_command(
                input_path=Path(__file__),
                output_path=Path(__file__),
                start_sec=0.0,
                end_sec=10.0,
            )

    def test_build_cut_command_stream_copy_flags(self):
        dummy_in = Path(__file__)  # Existing file
        dummy_out = Path(__file__).parent / "dummy_out.mp4"
        keyframes = [0.0, 5.0, 10.0]

        cmd, start, end = build_cut_command(
            input_path=dummy_in,
            output_path=dummy_out,
            start_sec=6.2,
            end_sec=15.0,
            snap_keyframe=True,
            keyframes=keyframes,
        )

        self.assertEqual(start, 5.0)
        self.assertEqual(end, 15.0)
        self.assertIn("-c", cmd)
        self.assertIn("copy", cmd)
        self.assertIn("-map", cmd)
        self.assertIn("0", cmd)
        self.assertIn("-avoid_negative_ts", cmd)
        self.assertIn("make_zero", cmd)

    def test_build_cut_command_selected_stream_indices(self):
        dummy_in = Path(__file__)
        dummy_out = Path(__file__).parent / "dummy_out.mp4"

        cmd, start, end = build_cut_command(
            input_path=dummy_in,
            output_path=dummy_out,
            start_sec=1.0,
            end_sec=5.0,
            selected_stream_indices=[0, 1, 2],
        )

        self.assertIn("-map", cmd)
        self.assertIn("0:0", cmd)
        self.assertIn("0:1", cmd)
        self.assertIn("0:2", cmd)

    def test_build_cut_command_per_track_matching(self):
        dummy_in = Path(__file__)
        dummy_out = Path(__file__).parent / "dummy_out.mp4"
        # Video: 10.0 to 40.0; Audio #1 (stream 1): 10.0 to 40.0 (matching)
        ranges = {0: (10.0, 40.0), 1: (10.0, 40.0)}
        cmd, start, end = build_cut_command(
            input_path=dummy_in,
            output_path=dummy_out,
            start_sec=10.0,
            end_sec=40.0,
            selected_stream_indices=[0, 1],
            track_ranges=ranges,
        )
        self.assertEqual(start, 10.0)
        self.assertEqual(end, 40.0)
        self.assertIn("-c", cmd)
        self.assertIn("copy", cmd)

    def test_build_cut_command_per_track_hybrid_delay(self):
        dummy_in = Path(__file__)
        dummy_out = Path(__file__).parent / "dummy_out.mp4"
        # Video: 10.0 to 40.0; Audio #1 (stream 1): 15.0 to 30.0 (offset by 5s)
        ranges = {0: (10.0, 40.0), 1: (15.0, 30.0)}
        cmd, start, end = build_cut_command(
            input_path=dummy_in,
            output_path=dummy_out,
            start_sec=10.0,
            end_sec=40.0,
            selected_stream_indices=[0, 1],
            track_ranges=ranges,
            cut_mode="per_track",
        )
        self.assertEqual(start, 10.0)
        self.assertEqual(end, 40.0)
        # Check that video is stream-copied
        self.assertIn("-c:v", cmd)
        self.assertIn("copy", cmd)
        # Check that audio filter with adelay is constructed
        cmd_str = " ".join(cmd)
        self.assertIn("adelay", cmd_str)
        self.assertIn("5000:all=1", cmd_str)
        self.assertIn("320k", cmd_str)

    def test_build_cut_command_per_track_hybrid_with_subtitles(self):
        dummy_in = Path(__file__)
        dummy_out = Path(__file__).parent / "dummy_out.mp4"
        # Stream 0: Video, Stream 1: Audio (offset), Stream 2: Subtitle
        ranges = {0: (10.0, 40.0), 1: (15.0, 30.0), 2: (10.0, 40.0)}
        types = {0: "video", 1: "audio", 2: "subtitle"}
        cmd, start, end = build_cut_command(
            input_path=dummy_in,
            output_path=dummy_out,
            start_sec=10.0,
            end_sec=40.0,
            selected_stream_indices=[0, 1, 2],
            track_ranges=ranges,
            stream_types=types,
            cut_mode="per_track",
        )
        self.assertEqual(start, 10.0)
        self.assertEqual(end, 40.0)
        # Check that video is stream-copied
        self.assertIn("-c:v", cmd)
        self.assertIn("copy", cmd)
        # Check that subtitle is stream-copied and not sent to audio filter
        self.assertIn("-c:s", cmd)
        self.assertIn("copy", cmd)
        self.assertIn("0:2", cmd)
        # Verify subtitle stream 0:2 is not in filter_complex
        cmd_str = " ".join(cmd)
        self.assertNotIn("[0:2]atrim", cmd_str)

    def test_build_cut_command_global_cut_never_triggers_hybrid_even_with_snap(self):
        dummy_in = Path(__file__)
        dummy_out = Path(__file__).parent / "dummy_out.mp4"
        # In global cut mode, user sets In at 3.5, but keyframe snaps to 0.0.
        # track_ranges has (3.5, 10.0) for audio streams.
        # It must NOT trigger hybrid re-encoding or adelay!
        ranges = {0: (3.5, 10.0), 1: (3.5, 10.0), 2: (3.5, 10.0)}
        types = {0: "video", 1: "audio", 2: "audio"}
        keyframes = [0.0, 5.0, 10.0]
        cmd, start, end = build_cut_command(
            input_path=dummy_in,
            output_path=dummy_out,
            start_sec=3.5,
            end_sec=10.0,
            snap_keyframe=True,
            keyframes=keyframes,
            selected_stream_indices=[0, 1, 2],
            track_ranges=ranges,
            stream_types=types,
            cut_mode="global",
            snap_mode="closest",
        )
        # Closest keyframe to 3.5 is 5.0
        self.assertEqual(start, 5.0)
        self.assertEqual(end, 10.0)
        self.assertIn("-c", cmd)
        self.assertIn("copy", cmd)
        cmd_str = " ".join(cmd)
        self.assertNotIn("adelay", cmd_str)
        self.assertNotIn("-filter_complex", cmd_str)


    def test_generate_default_output_name(self):
        dummy_in = Path(__file__)
        out_path = generate_default_output_name(dummy_in)
        self.assertEqual(out_path.suffix, dummy_in.suffix)
        self.assertTrue(out_path.stem.startswith(dummy_in.stem))
        # Checks that it contains 'h', 'm', 's', and '-' for date
        self.assertIn("h", out_path.stem)
        self.assertIn("m", out_path.stem)
        self.assertIn("s", out_path.stem)
        self.assertIn("-", out_path.stem)


if __name__ == "__main__":
    unittest.main()

