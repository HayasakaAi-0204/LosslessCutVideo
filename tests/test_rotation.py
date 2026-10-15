"""Unit tests for lossless video rotation metadata and snapshot transpose filtering."""

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

app = QApplication.instance()
if app is None:
    app = QApplication([])

from src.core.cutter import build_cut_command, build_snapshot_command
from src.core.probe import parse_ffprobe_json
from src.ui.player_widget import PlayerWidget


class TestLosslessRotation(unittest.TestCase):
    def test_build_cut_command_rotation_metadata(self):
        """Verify build_cut_command adds -metadata:s:v:0 rotate=X for supported containers."""
        dummy_in = Path(__file__)
        dummy_out = Path(__file__).parent / "rot_out.mp4"

        # 90 degrees
        cmd90, _, _ = build_cut_command(
            input_path=dummy_in,
            output_path=dummy_out,
            start_sec=0.0,
            end_sec=5.0,
            rotation=90,
            selected_stream_indices=[0, 1],
        )
        cmd_str90 = " ".join(cmd90)
        self.assertIn("-metadata:s:v:0 rotate=90", cmd_str90)
        self.assertIn("-c copy", cmd_str90)

        # 180 degrees
        cmd180, _, _ = build_cut_command(
            input_path=dummy_in,
            output_path=dummy_out,
            start_sec=0.0,
            end_sec=5.0,
            rotation=180,
            selected_stream_indices=[0, 1],
        )
        cmd_str180 = " ".join(cmd180)
        self.assertIn("-metadata:s:v:0 rotate=180", cmd_str180)

        # None / 0 degrees
        cmd_none, _, _ = build_cut_command(
            input_path=dummy_in,
            output_path=dummy_out,
            start_sec=0.0,
            end_sec=5.0,
            rotation=None,
            selected_stream_indices=[0, 1],
        )
        self.assertNotIn("-metadata:s:v:0", " ".join(cmd_none))

    def test_build_cut_command_rotation_audio_only_ignored(self):
        """Verify rotation metadata is not added when only audio streams are exported."""
        dummy_in = Path(__file__)
        dummy_out = Path(__file__).parent / "audio_out.m4a"

        cmd, _, _ = build_cut_command(
            input_path=dummy_in,
            output_path=dummy_out,
            start_sec=0.0,
            end_sec=5.0,
            rotation=90,
            selected_stream_indices=[1],
            stream_types={1: "audio"},
        )
        self.assertNotIn("rotate=", " ".join(cmd))

    def test_build_snapshot_command_rotation_filters(self):
        """Verify build_snapshot_command applies proper transpose filters for rotation angles."""
        dummy_in = Path(__file__)
        dummy_out = Path(__file__).parent / "snap.png"

        # 0 deg: no filter
        cmd0 = build_snapshot_command(dummy_in, dummy_out, 2.0, rotation=0)
        self.assertNotIn("-vf", cmd0)

        # 90 deg: transpose=1 (90 CW)
        cmd90 = build_snapshot_command(dummy_in, dummy_out, 2.0, rotation=90)
        self.assertIn("-vf", cmd90)
        self.assertIn("transpose=1", cmd90)

        # 180 deg: hflip,vflip
        cmd180 = build_snapshot_command(dummy_in, dummy_out, 2.0, rotation=180)
        self.assertIn("-vf", cmd180)
        self.assertIn("hflip,vflip", cmd180)

        # 270 deg: transpose=2 (90 CCW)
        cmd270 = build_snapshot_command(dummy_in, dummy_out, 2.0, rotation=270)
        self.assertIn("-vf", cmd270)
        self.assertIn("transpose=2", cmd270)

    def test_probe_extracts_rotation_metadata(self):
        """Verify parse_ffprobe_json extracts rotation from video stream tags or side data."""
        mock_json_with_tag = """{
            "format": {"duration": "10.0", "size": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "tags": {"rotate": "90"}
                }
            ]
        }"""
        info = parse_ffprobe_json(mock_json_with_tag)
        self.assertEqual(info.get("rotation"), 90)

        mock_json_side_data = """{
            "format": {"duration": "10.0", "size": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 3840,
                    "height": 2160,
                    "side_data_list": [
                        {"side_data_type": "Display Matrix", "rotation": -90}
                    ]
                }
            ]
        }"""
        info2 = parse_ffprobe_json(mock_json_side_data)
        # -90 % 360 == 270
        self.assertEqual(info2.get("rotation"), 270)

    def test_player_widget_rotation_cycle(self):
        """Verify PlayerWidget rotation cycle 0 -> 90 -> 180 -> 270 -> 0."""
        player = PlayerWidget()
        self.assertEqual(player.get_rotation(), 0)

        rotations = []
        player.rotation_changed.connect(lambda r: rotations.append(r))

        player.rotate_90()
        self.assertEqual(player.get_rotation(), 90)
        self.assertEqual(player.btn_rotate.text(), "⟳ Xoay: 90°")

        player.rotate_90()
        self.assertEqual(player.get_rotation(), 180)

        player.rotate_90()
        self.assertEqual(player.get_rotation(), 270)

        player.rotate_90()
        self.assertEqual(player.get_rotation(), 0)
        self.assertEqual(player.btn_rotate.text(), "⟳ Xoay: 0°")

        self.assertEqual(rotations, [90, 180, 270, 0])

        # Test initial rotation setup
        player.set_initial_rotation(90)
        self.assertEqual(player.get_rotation(), 90)

        player.clear_video()
        self.assertEqual(player.get_rotation(), 0)
        self.assertFalse(player.btn_rotate.isEnabled())

        player.close()


if __name__ == "__main__":
    unittest.main()

