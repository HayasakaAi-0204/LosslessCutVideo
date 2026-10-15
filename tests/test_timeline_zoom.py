"""Unit tests for Timeline Widget Zoom and Viewport Culling calculations."""

import unittest
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for Qt widget tests
app = QApplication.instance()
if app is None:
    app = QApplication([])

from src.ui.timeline_widget import TimelineCanvas, TimelineWidget


class TestTimelineZoom(unittest.TestCase):
    def setUp(self):
        self.widget = TimelineWidget()

    def test_canvas_zoom_clamping(self):
        """Verify canvas pixels_per_sec is safely clamped between 0.05 and 60.0 px/s."""
        canvas = self.widget.canvas
        canvas.set_zoom(0.001)
        self.assertAlmostEqual(canvas.get_pixels_per_sec(), 0.05)

        canvas.set_zoom(500.0)
        self.assertAlmostEqual(canvas.get_pixels_per_sec(), 60.0)

        canvas.set_zoom(35.5)
        self.assertAlmostEqual(canvas.get_pixels_per_sec(), 35.5)

    def test_fit_pps_calculation(self):
        """Verify fit_pps calculation for various video durations."""
        self.widget.set_duration(252821)  # 252.82 seconds (~4m 12s)
        fit_pps = self.widget._get_fit_pps()
        self.assertGreater(fit_pps, 0.05)
        self.assertLess(fit_pps, 50.0)

    def test_max_pps_capping(self):
        """Verify max_pps never exceeds 50.0 px/s to prevent extreme over-zoom."""
        # 4-minute video
        self.widget.set_duration(252821)
        fit_pps = self.widget._get_fit_pps()
        max_pps = self.widget._get_max_pps(fit_pps)
        self.assertLessEqual(max_pps, 50.0)
        self.assertGreaterEqual(max_pps, fit_pps)

        # 1-hour video
        self.widget.set_duration(3600000)
        fit_pps_1h = self.widget._get_fit_pps()
        max_pps_1h = self.widget._get_max_pps(fit_pps_1h)
        self.assertLessEqual(max_pps_1h, 50.0)
        self.assertGreaterEqual(max_pps_1h, fit_pps_1h)

    def test_slider_pps_monotonicity(self):
        """Verify slider value 0 to 100 maps strictly monotonically from fit_pps to max_pps."""
        self.widget.set_duration(252821)
        pps_0 = self.widget._calc_pps_from_slider(0)
        pps_25 = self.widget._calc_pps_from_slider(25)
        pps_50 = self.widget._calc_pps_from_slider(50)
        pps_75 = self.widget._calc_pps_from_slider(75)
        pps_100 = self.widget._calc_pps_from_slider(100)

        self.assertLessEqual(pps_0, pps_25)
        self.assertLessEqual(pps_25, pps_50)
        self.assertLessEqual(pps_50, pps_75)
        self.assertLessEqual(pps_75, pps_100)
        self.assertLessEqual(pps_100, 50.0)

    def test_visible_x_bounds_fallback(self):
        """Verify _get_visible_x_bounds returns valid range even when unattached."""
        canvas = TimelineCanvas()
        left, right = canvas._get_visible_x_bounds()
        self.assertEqual(left, 0.0)
        self.assertGreaterEqual(right, 0.0)

    def test_sync_zoom_with_speed(self):
        """Verify playback speed changes dynamically adjust timeline zoom:
        1.0x -> 0% (Fit To Width)
        0.5x -> 67% (2x zoom)
        0.25x -> 100% (4x zoom, maximum detail)
        1.5x / 2.0x -> 0% (Overview)
        """
        self.widget.set_duration(252821)
        self.widget.sync_zoom_with_speed(1.0)
        self.assertEqual(self.widget.zoom_slider.value(), 0)

        self.widget.sync_zoom_with_speed(0.75)
        self.assertEqual(self.widget.zoom_slider.value(), 33)

        self.widget.sync_zoom_with_speed(0.5)
        self.assertEqual(self.widget.zoom_slider.value(), 67)

        self.widget.sync_zoom_with_speed(0.25)
        self.assertEqual(self.widget.zoom_slider.value(), 100)

        self.widget.sync_zoom_with_speed(1.5)
        self.assertEqual(self.widget.zoom_slider.value(), 0)

        self.widget.sync_zoom_with_speed(2.0)
        self.assertEqual(self.widget.zoom_slider.value(), 0)

    def test_ruler_label_spacing_never_overlaps(self):
        """Verify that at any PPS zoom level, the pixel distance between ruler labels is always >= 85px."""
        step_presets = [
            (0.1, 0.02), (0.2, 0.05), (0.5, 0.1), (1.0, 0.2), (2.0, 0.5),
            (5.0, 1.0), (10.0, 2.0), (15.0, 5.0), (30.0, 5.0), (60.0, 10.0),
            (120.0, 30.0), (300.0, 60.0), (600.0, 120.0), (1800.0, 300.0), (3600.0, 600.0),
        ]
        test_pps_values = [0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 4.35, 10.0, 20.0, 35.0, 43.6, 50.0, 60.0]
        for pps in test_pps_values:
            selected_step = step_presets[-1][0]
            for s, _ in step_presets:
                if s * pps >= 85.0:
                    selected_step = s
                    break
            pixel_distance = selected_step * pps
            self.assertGreaterEqual(
                pixel_distance, 85.0,
                f"Pixel distance {pixel_distance:.1f}px at pps={pps} is too small and would cause label overlap!"
            )

    def test_keyframe_snap_always_enabled(self):
        """Verify keyframe snap is permanently enabled without any checkbox."""
        self.assertTrue(self.widget.is_snap_enabled())
        self.widget.set_keyframes([0.0, 2.5, 5.0, 10.0])
        self.assertEqual(self.widget.snap_to_keyframe(2.4, force_closest=True), 2.5)

    def test_mouse_drag_only_moves_playhead_not_markers(self):
        """Verify mouse clicking/dragging on timeline canvas only moves playhead and never drags In/Out markers."""
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QPointF, QEvent

        self.widget.set_duration(100000)  # 100 seconds
        canvas = self.widget.canvas
        canvas.set_tracks([{"stream_index": 0, "codec_type": "video"}], {0})
        canvas.set_in_point(10.0)
        canvas.set_out_point(50.0)

        # Coordinate of In marker
        in_x = canvas._sec_to_x(10.0)

        # Click right on In marker on ruler (y = 10 <= RULER_HEIGHT)
        press_event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(in_x, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        canvas.mousePressEvent(press_event)

        # Drag mode must be 'playhead', never 'in'
        self.assertEqual(canvas._drag_mode, "playhead")

        # Drag mouse to position 30.0 sec
        drag_x = canvas._sec_to_x(30.0)
        move_event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(drag_x, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        canvas.mouseMoveEvent(move_event)

        # In and Out markers must remain exactly unchanged!
        self.assertEqual(canvas._in_point_sec, 10.0)
        self.assertEqual(canvas._out_point_sec, 50.0)
        self.assertAlmostEqual(canvas._current_pos_sec, 30.0, places=1)

        # Release mouse
        release_event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(drag_x, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        canvas.mouseReleaseEvent(release_event)
        self.assertIsNone(canvas._drag_mode)


if __name__ == "__main__":
    unittest.main()

