"""Unit tests for frame snapshot feature (UI controls, naming, and command construction)."""

from pathlib import Path
import sys
import unittest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

app = QApplication.instance()
if app is None:
    app = QApplication([])

from src.core.cutter import generate_snapshot_output_name, build_snapshot_command
from src.core.worker import SnapshotWorker
from src.ui.player_widget import PlayerWidget
from src.ui.main_window import MainWindow


class TestSnapshotFeature(unittest.TestCase):
    def test_generate_snapshot_output_name_formatting(self):
        """Verify snapshot file names are properly formatted with minutes, seconds, and milliseconds."""
        dummy_video = PROJECT_ROOT / "test_sample.mp4"
        # 65.420s -> 01m05s420ms
        out_path = generate_snapshot_output_name(dummy_video, 65.420, extension=".png")
        self.assertEqual(out_path.suffix, ".png")
        self.assertIn("01m05s420ms", out_path.name)
        self.assertIn("test_sample_snapshot_", out_path.name)

    def test_generate_snapshot_output_name_zero_and_large(self):
        """Verify boundary timestamps like 0.0s and 3661.123s."""
        dummy_video = PROJECT_ROOT / "my_movie.mkv"
        out_zero = generate_snapshot_output_name(dummy_video, 0.0)
        self.assertIn("00m00s000ms", out_zero.name)

        # 3661.123s = 61 mins, 1 sec, 123 ms
        out_large = generate_snapshot_output_name(dummy_video, 3661.123)
        self.assertIn("61m01s123ms", out_large.name)

    def test_build_snapshot_command_short_timestamp(self):
        """Verify FFmpeg command when timestamp <= 5.0 seconds."""
        dummy_in = Path(__file__)
        dummy_out = Path(__file__).parent / "snap_out.png"
        cmd = build_snapshot_command(dummy_in, dummy_out, 3.25)

        cmd_str = " ".join(cmd)
        self.assertIn("-ss 3.250", cmd_str)
        self.assertIn(f"-i {dummy_in}", cmd_str)
        self.assertIn("-frames:v 1", cmd_str)
        self.assertIn("-q:v 2", cmd_str)
        self.assertEqual(cmd[-1], str(dummy_out))

    def test_build_snapshot_command_two_stage_seek(self):
        """Verify two-stage fast+fine seek optimization for timestamps > 5.0s."""
        dummy_in = Path(__file__)
        dummy_out = Path(__file__).parent / "snap_out.png"
        cmd = build_snapshot_command(dummy_in, dummy_out, 45.8)

        cmd_str = " ".join(cmd)
        # Fast seek to 45.8 - 3.0 = 42.8 before -i
        self.assertIn("-ss 42.800", cmd_str)
        self.assertIn(f"-i {dummy_in}", cmd_str)
        # Accurate fine seek 3.000 after -i
        self.assertIn("-ss 3.000", cmd_str)
        self.assertIn("-frames:v 1", cmd_str)

    def test_player_widget_snapshot_button_lifecycle(self):
        """Verify player snapshot button enable/disable lifecycle."""
        player = PlayerWidget()
        # Initially disabled before video load
        self.assertFalse(player.btn_snapshot.isEnabled())

        # Clicking emits signal
        emitted = []
        player.snapshot_requested.connect(lambda: emitted.append(True))
        player.btn_snapshot.click()
        self.assertEqual(len(emitted), 1)

        # Video disabled (e.g. video track unchecked) disables snapshot button
        player.set_video_enabled(False)
        self.assertFalse(player.btn_snapshot.isEnabled())
        self.assertFalse(player.is_video_enabled())

        # Re-enabling video re-enables snapshot button if video is loaded
        player.set_video_enabled(True)
        self.assertTrue(player.is_video_enabled())

        player.close()

    def test_main_window_snapshot_shortcut_handling(self):
        """Verify MainWindow initializes snapshot worker and handles no-video gracefully."""
        win = MainWindow()
        self.assertIsNone(win._snapshot_worker)

        # If no video is loaded, _take_snapshot does not throw and safely exits
        win._take_snapshot()
        self.assertIsNone(win._snapshot_worker)

        win.close()


if __name__ == "__main__":
    unittest.main()

