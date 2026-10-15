"""Unit tests for verifying unified dark theme button styling and dimensions."""

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

from src.ui.main_window import MainWindow
from src.ui.player_widget import PlayerWidget
from src.ui.timeline_widget import TimelineWidget
from src.ui.styles import (
    UNIFIED_BUTTON_STYLE,
    UNIFIED_ICON_BUTTON_STYLE,
    BUTTON_SET_IN_STYLE,
    BUTTON_SET_OUT_STYLE,
    BUTTON_CANCEL_STYLE,
    BUTTON_EXPORT_STYLE,
)


class TestUIButtonStyles(unittest.TestCase):
    def setUp(self):
        self.main_window = MainWindow()

    def tearDown(self):
        self.main_window.close()

    def test_top_bar_button_styles_and_heights(self):
        """Verify top bar buttons have unified 32px height and consistent styling."""
        btn_open = self.main_window.btn_open_file
        btn_export = self.main_window.btn_export
        btn_cancel = self.main_window.btn_cancel

        self.assertEqual(btn_open.maximumHeight(), 32)
        self.assertEqual(btn_open.minimumHeight(), 32)
        self.assertEqual(btn_export.maximumHeight(), 32)
        self.assertEqual(btn_export.minimumHeight(), 32)
        self.assertEqual(btn_cancel.maximumHeight(), 32)
        self.assertEqual(btn_cancel.minimumHeight(), 32)

        self.assertEqual(btn_open.styleSheet(), UNIFIED_BUTTON_STYLE)
        self.assertEqual(btn_export.styleSheet(), BUTTON_EXPORT_STYLE)
        self.assertEqual(btn_cancel.styleSheet(), BUTTON_CANCEL_STYLE)

    def test_player_controls_button_dimensions(self):
        """Verify player action buttons share uniform 30px height and steppers 28x28px."""
        player = self.main_window.player_widget

        # 30px height action buttons
        action_buttons = [
            player.btn_prev_kf,
            player.btn_step_back,
            player.btn_play_pause,
            player.btn_step_forward,
            player.btn_next_kf,
            player.btn_snapshot,
            player.btn_rotate,
        ]
        for btn in action_buttons:
            self.assertEqual(btn.maximumHeight(), 30, f"{btn.text()} height != 30")
            self.assertEqual(btn.minimumHeight(), 30, f"{btn.text()} height != 30")

        # 28x28 icon stepper buttons
        self.assertEqual(player.btn_speed_down.width(), 28)
        self.assertEqual(player.btn_speed_down.height(), 28)
        self.assertEqual(player.btn_speed_up.width(), 28)
        self.assertEqual(player.btn_speed_up.height(), 28)
        self.assertEqual(player.combo_speed.height(), 28)

    def test_timeline_toolbar_button_dimensions(self):
        """Verify timeline toolbar buttons share uniform 28px height."""
        timeline = self.main_window.timeline_widget

        self.assertEqual(timeline.btn_set_in.maximumHeight(), 28)
        self.assertEqual(timeline.btn_set_in.minimumHeight(), 28)
        self.assertEqual(timeline.btn_set_out.maximumHeight(), 28)
        self.assertEqual(timeline.btn_set_out.minimumHeight(), 28)
        self.assertEqual(timeline.btn_zoom_fit.maximumHeight(), 28)
        self.assertEqual(timeline.btn_zoom_fit.minimumHeight(), 28)

        self.assertEqual(timeline.btn_zoom_out.width(), 28)
        self.assertEqual(timeline.btn_zoom_out.height(), 28)
        self.assertEqual(timeline.btn_zoom_in.width(), 28)
        self.assertEqual(timeline.btn_zoom_in.height(), 28)

        self.assertEqual(timeline.btn_set_in.styleSheet(), BUTTON_SET_IN_STYLE)
        self.assertEqual(timeline.btn_set_out.styleSheet(), BUTTON_SET_OUT_STYLE)
        self.assertEqual(timeline.btn_zoom_fit.styleSheet(), UNIFIED_BUTTON_STYLE)
        self.assertEqual(timeline.btn_zoom_out.styleSheet(), UNIFIED_ICON_BUTTON_STYLE)
        self.assertEqual(timeline.btn_zoom_in.styleSheet(), UNIFIED_ICON_BUTTON_STYLE)


if __name__ == "__main__":
    unittest.main()

