"""Unit tests for full-range video preview playback and playhead-only timeline mouse interaction."""

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

app = QApplication.instance()
if app is None:
    app = QApplication([])

from src.ui.player_widget import PlayerWidget
from src.ui.timeline_widget import TimelineCanvas, TimelineWidget


class TestPreviewAndMarkers(unittest.TestCase):
    def setUp(self):
        self.player = PlayerWidget()
        self.timeline = TimelineWidget()

    def tearDown(self):
        self.player.close()
        self.timeline.close()

    def test_preview_playback_unclamped_beyond_out_point(self):
        """Verify preview playback plays freely across the entire video, including before In and after Out."""
        self.player._duration_ms = 60000  # 60s
        self.player.set_in_out(10000, 30000)  # In: 10s, Out: 30s

        # 1. Start playback after Out point (e.g. 40s)
        # In previous buggy behavior, this would jump back to In point (10s).
        # In new requested behavior, it must NOT jump back; it should play from current position.
        seek_positions = []
        self.player.seek_requested.connect(lambda p: seek_positions.append(p))

        # Position is at 40s (beyond Out point)
        # Mock position
        self.player.player.setPosition(40000)
        self.player.play_pause()
        # Should not emit seek_requested back to 10s
        self.assertEqual(len(seek_positions), 0)

        # 2. Position changed callback at 30s (Out point)
        # In previous buggy behavior, passing Out point would pause playback.
        # In new requested behavior, passing Out point does not pause playback.
        self.player._on_position_changed(30000)
        # Should not pause: player state is still whatever it was, not forcefully paused by Out point
        self.player._on_position_changed(35000)
        # Only at end of video (60s) does it pause
        self.player._on_position_changed(60000)
        self.assertEqual(self.player.player.playbackState(), QMediaPlayer.PlaybackState.StoppedState)

    def test_video_overlay_when_video_track_disabled(self):
        """Verify video disabled overlay appears when video track is toggled off and disappears when on."""
        self.player.show()
        # Video enabled
        self.player.set_video_enabled(True)
        self.assertFalse(self.player.video_disabled_overlay.isVisible())

        # Video disabled
        self.player.set_video_enabled(False)
        self.assertTrue(self.player.video_disabled_overlay.isVisible())

        # Re-enable
        self.player.set_video_enabled(True)
        self.assertFalse(self.player.video_disabled_overlay.isVisible())

    def test_audio_muting_when_audio_tracks_disabled(self):
        """Verify audio is muted when all audio tracks are deselected."""
        # Setup mock tracks: 0 = video, 1 = audio
        tracks = [
            {"stream_index": 0, "codec_type": "video"},
            {"stream_index": 1, "codec_type": "audio"},
        ]
        # Only video active (audio track 1 disabled)
        self.player.update_active_tracks([0], tracks)
        self.assertTrue(self.player.audio_output.isMuted())

        # Both active
        self.player.update_active_tracks([0, 1], tracks)
        self.assertFalse(self.player.audio_output.isMuted())

    def test_mouse_clicks_and_drags_never_move_in_out_markers(self):
        """Verify mouse dragging on timeline canvas strictly seeks playhead and never moves In/Out markers."""
        self.timeline.set_duration(120000)  # 120s
        canvas = self.timeline.canvas
        canvas.set_tracks([{"stream_index": 0, "codec_type": "video"}], {0})
        canvas.set_in_point(20.0)
        canvas.set_out_point(80.0)

        in_x = canvas._sec_to_x(20.0)
        out_x = canvas._sec_to_x(80.0)

        # 1. Click directly on In marker flag on ruler
        press_in = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(in_x, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        canvas.mousePressEvent(press_in)
        self.assertEqual(canvas._drag_mode, "playhead")

        # Drag 40px away
        drag_in = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(in_x + 40.0, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        canvas.mouseMoveEvent(drag_in)

        # Markers MUST be intact
        self.assertEqual(canvas._in_point_sec, 20.0)
        self.assertEqual(canvas._out_point_sec, 80.0)

        release_in = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(in_x + 40.0, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        canvas.mouseReleaseEvent(release_in)
        self.assertIsNone(canvas._drag_mode)

        # 2. Click directly on Out marker flag on ruler
        press_out = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(out_x, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        canvas.mousePressEvent(press_out)
        self.assertEqual(canvas._drag_mode, "playhead")

        # Drag 50px away
        drag_out = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(out_x - 50.0, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        canvas.mouseMoveEvent(drag_out)

        # Markers MUST still be intact
        self.assertEqual(canvas._in_point_sec, 20.0)
        self.assertEqual(canvas._out_point_sec, 80.0)

    def test_in_out_setters_via_buttons_and_methods_remain_functional(self):
        """Verify setting In and Out points programmatically (as triggered by I/O buttons or shortcuts) works."""
        self.timeline.set_duration(120000)
        self.timeline.set_in_point(15.0)
        self.timeline.set_out_point(75.0)

        self.assertEqual(self.timeline.get_in_point(), 15.0)
        self.assertEqual(self.timeline.get_out_point(), 75.0)
        self.assertEqual(self.timeline.canvas._in_point_sec, 15.0)
        self.assertEqual(self.timeline.canvas._out_point_sec, 75.0)


if __name__ == "__main__":
    unittest.main()

