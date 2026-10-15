"""Unit tests for robust drag-drop file path extraction and lightweight timeline performance."""

from pathlib import Path
import sys
import unittest
from urllib.parse import quote

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication

app = QApplication.instance()
if app is None:
    app = QApplication([])

from src.ui.main_window import MainWindow
from src.ui.timeline_widget import TimelineWidget


class TestDragDropAndPerf(unittest.TestCase):
    def setUp(self):
        self.main_window = MainWindow()

    def tearDown(self):
        self.main_window.close()

    def test_extract_dropped_file_with_parentheses_and_spaces(self):
        """Verify filenames like '(60-100)New Record.mp4' are correctly decoded from QUrl percent-encoding."""
        test_file = PROJECT_ROOT / "(60-100)New Record.mp4"
        test_file.touch(exist_ok=True)

        try:
            mime = QMimeData()
            # QUrl representation often percent-encodes '(' and ')' and spaces
            url = QUrl.fromLocalFile(str(test_file.resolve()))
            mime.setUrls([url])

            extracted = self.main_window._extract_dropped_file(mime)
            self.assertIsNotNone(extracted, "Should extract file even with parentheses and spaces")
            self.assertEqual(extracted.resolve(), test_file.resolve())
        finally:
            if test_file.exists():
                try:
                    test_file.unlink()
                except Exception:
                    pass

    def test_extract_dropped_file_from_text(self):
        """Verify plain text file paths are correctly decoded and recognized."""
        test_file = PROJECT_ROOT / "test_sample_video.mp4"
        test_file.touch(exist_ok=True)

        try:
            mime = QMimeData()
            mime.setText(str(test_file.resolve()))

            extracted = self.main_window._extract_dropped_file(mime)
            self.assertIsNotNone(extracted)
            self.assertEqual(extracted.resolve(), test_file.resolve())
        finally:
            if test_file.exists():
                try:
                    test_file.unlink()
                except Exception:
                    pass

    def test_timeline_thumbnails_disabled_for_instant_load(self):
        """Verify timeline widget does not cache thumbnail QPixmaps, maintaining zero CPU and memory footprint."""
        tl = TimelineWidget()
        tl.canvas.set_thumbnails([{"time_sec": 1.0, "image_path": "non_existent.jpg"}])
        self.assertEqual(len(tl.canvas._thumbnails), 0)

    def test_audio_export_button_text_switch(self):
        """Verify export button text switches dynamically between '⚡ Xuất Video' and '🎵 Xuất Âm Thanh'."""
        self.main_window._video_info = {
            "tracks": [
                {"stream_index": 0, "codec_type": "video", "codec_name": "av1"},
                {"stream_index": 1, "codec_type": "audio", "codec_name": "aac"},
            ]
        }
        # When both video and audio active -> Xuất Video
        self.main_window._on_timeline_tracks_changed([0, 1])
        self.assertEqual(self.main_window.btn_export.text(), "⚡ Xuất Video")

        # When only audio active (video dropped) -> Xuất Âm Thanh
        self.main_window._on_timeline_tracks_changed([1])
        self.assertEqual(self.main_window.btn_export.text(), "🎵 Xuất Âm Thanh")

        # When video restored -> Xuất Video
        self.main_window._on_timeline_tracks_changed([0])
        self.assertEqual(self.main_window.btn_export.text(), "⚡ Xuất Video")


if __name__ == "__main__":
    unittest.main()

