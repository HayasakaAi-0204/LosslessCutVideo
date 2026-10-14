"""Main application window for Lossless Video Cutter.

CapCut-inspired layout:
- Top bar: Open video, video specs, and prominent Blue Export button.
- Center: High-FPS responsive video player with custom preview speed controls.
- Bottom: Full-featured Multi-Track Timeline with visual lanes, time ruler, waveforms, and track toggles.
- Save flow: Clicking "⚡ Xuất Video" opens native Windows Save As dialog at original folder with real-time timestamp.
- Default maximized window state.
"""

from datetime import datetime
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QUrl, QEvent
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeyEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QProgressBar,
    QFileDialog,
    QMessageBox,
    QFrame,
)

from src.core.config import validate_tools
from src.core.probe import probe_video_info
from src.core.cutter import (
    build_cut_command,
    format_timestamp,
)
from src.core.worker import (
    CutWorker,
    KeyframeWorker,
    AudioWaveformWorker,
    VideoThumbnailWorker,
)
from src.ui.player_widget import PlayerWidget
from src.ui.timeline_widget import TimelineWidget


class MainWindow(QMainWindow):
    """Main Application Window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lossless Video Cutter - Cắt Video 100% Nguyên Bản")
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self._current_video_path: Path | None = None
        self._video_info: dict = {}
        self._keyframes: list[float] = []
        self._worker: CutWorker | None = None
        self._kf_worker: KeyframeWorker | None = None
        self._audio_worker: AudioWaveformWorker | None = None
        self._thumb_worker: VideoThumbnailWorker | None = None
        self._last_drop_time: float = 0.0

        self._setup_ui()
        self._check_environment()

        # Start maximized by default
        self.showMaximized()

    def _setup_ui(self):
        central = QWidget(self)
        central.setAcceptDrops(True)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # ---------------------------------------------------------------------
        # 1. Top Bar: Open File + Info + Blue Export Button
        # ---------------------------------------------------------------------
        top_bar = QFrame()
        top_bar.setAcceptDrops(True)
        top_bar.setStyleSheet("""
            QFrame {
                background-color: #1e222b;
                border-radius: 6px;
                border: 1px solid #2c313c;
            }
        """)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 6, 10, 6)
        top_layout.setSpacing(12)

        # Left: Open File Button & Video metadata
        self.btn_open_file = QPushButton("📁 Mở Video...")
        self.btn_open_file.setStyleSheet("""
            QPushButton {
                background-color: #2c313c;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                padding: 7px 16px;
                border-radius: 4px;
                border: 1px solid #3d4452;
            }
            QPushButton:hover {
                background-color: #3d4452;
            }
        """)
        self.btn_open_file.clicked.connect(self._select_video_file)

        self.lbl_video_info = QLabel("Chưa chọn video (Kéo thả video vào bất kỳ đâu hoặc bấm 'Mở Video')")
        self.lbl_video_info.setStyleSheet("color: #8b949e; font-size: 13px;")

        top_layout.addWidget(self.btn_open_file)
        top_layout.addWidget(self.lbl_video_info, stretch=1)

        # Right: CapCut Blue Export Button & Cancel / Close Video Button
        self.btn_export = QPushButton("⚡ Xuất Video")
        self.btn_export.setStyleSheet("""
            QPushButton {
                background-color: #0084ff;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                padding: 7px 22px;
                border-radius: 5px;
                border: none;
            }
            QPushButton:hover {
                background-color: #0066cc;
            }
            QPushButton:disabled {
                background-color: #3a3f4b;
                color: #718096;
            }
        """)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._start_cut)

        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.setToolTip("Đóng video hiện tại và làm mới màn hình")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #3a3f4b;
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                padding: 7px 14px;
                border-radius: 5px;
                border: 1px solid #4a5160;
            }
            QPushButton:hover {
                background-color: #e74c3c;
                border-color: #c0392b;
            }
            QPushButton:disabled {
                background-color: #262930;
                color: #5c6370;
                border-color: #262930;
            }
        """)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._close_current_video)

        top_layout.addWidget(self.btn_export)
        top_layout.addWidget(self.btn_cancel)

        main_layout.addWidget(top_bar)

        # ---------------------------------------------------------------------
        # 2. Player Viewport
        # ---------------------------------------------------------------------
        self.player_widget = PlayerWidget(self)
        self.player_widget.file_dropped.connect(self._load_video)
        main_layout.addWidget(self.player_widget, stretch=1)

        # ---------------------------------------------------------------------
        # 3. CapCut Multi-Track Timeline
        # ---------------------------------------------------------------------
        self.timeline_widget = TimelineWidget(self)
        self.timeline_widget.setAcceptDrops(True)
        main_layout.addWidget(self.timeline_widget)

        # Connect Player & Timeline
        self.player_widget.position_changed.connect(self.timeline_widget.set_position)
        self.player_widget.duration_changed.connect(self.timeline_widget.set_duration)
        self.timeline_widget.seek_requested.connect(self.player_widget.seek)
        self.timeline_widget.tracks_changed.connect(self._on_timeline_tracks_changed)
        self.timeline_widget.in_point_changed.connect(
            lambda in_sec: self.player_widget.set_cut_range(in_sec, self.timeline_widget.get_out_point())
        )
        self.timeline_widget.out_point_changed.connect(
            lambda out_sec: self.player_widget.set_cut_range(self.timeline_widget.get_in_point(), out_sec)
        )

        # ---------------------------------------------------------------------
        # 4. Sleek Bottom Status Bar & Progress
        # ---------------------------------------------------------------------
        status_bar = QFrame()
        status_bar.setStyleSheet("background-color: #1a1d24; border-radius: 4px; padding: 2px;")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(8, 3, 8, 3)

        self.lbl_status = QLabel("Sẵn sàng.")
        self.lbl_status.setStyleSheet("color: #8b949e; font-size: 12px;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #22262f;
                border-radius: 6px;
                text-align: center;
                color: white;
                font-size: 9px;
            }
            QProgressBar::chunk {
                background-color: #0084ff;
                border-radius: 6px;
            }
        """)

        status_layout.addWidget(self.lbl_status, stretch=1)
        status_layout.addWidget(self.progress_bar)
        main_layout.addWidget(status_bar)

        # Enable drag-and-drop globally across all widgets in the window
        self._enable_global_drag_drop()

    def _check_environment(self):
        status = validate_tools()
        if not status["ffmpeg"] or not status["ffprobe"]:
            msg = (
                "Chưa phát hiện FFmpeg/FFprobe portable trong thư mục 'tools/'!\n\n"
                "Vui lòng đặt ffmpeg.exe và ffprobe.exe vào thư mục 'tools/' "
                "để ứng dụng có thể xử lý cắt video Lossless."
            )
            self.lbl_status.setText("⚠️ Thiếu công cụ FFmpeg trong thư mục tools/.")
            QMessageBox.warning(self, "Cảnh báo công cụ", msg)

    def _select_video_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file video cần cắt",
            "",
            "Video Files (*.mp4 *.mkv *.mov *.avi *.ts *.webm *.flv);;All Files (*.*)",
        )
        if file_path:
            self._load_video(Path(file_path))

    def _load_video(self, video_path: Path):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(200)

        self._current_video_path = video_path.resolve()
        self.lbl_status.setText(f"Đang phân tích: {video_path.name}...")
        self.timeline_widget.clear_preview_data()

        try:
            # 1. Fast metadata probe (instant < 50ms)
            self._video_info = probe_video_info(self._current_video_path)
            self._keyframes = []

            dur_sec = self._video_info.get("duration", 0.0)
            codec = self._video_info.get("video_codec", "N/A")
            width = self._video_info.get("width", 0)
            height = self._video_info.get("height", 0)
            fps = self._video_info.get("fps", 0.0)
            tracks = self._video_info.get("tracks", [])

            info_str = (
                f"🎬 {video_path.name} | {width}x{height} @ {fps}fps | "
                f"Codec: {codec.upper()} | {len(tracks)} Tracks | Tổng thời lượng: {format_timestamp(dur_sec)}"
            )
            self.lbl_video_info.setText(info_str)

            # 2. Load tracks into CapCut Multi-Track Timeline
            self.timeline_widget.set_tracks(tracks)
            self.timeline_widget.set_duration(int(dur_sec * 1000))

            # 3. Load video into player viewport and initialize preview boundaries
            self.player_widget.load_video(self._current_video_path, self._keyframes, fps=fps)
            self.player_widget.set_cut_range(0.0, dur_sec)
            self.player_widget.update_active_tracks(
                self.timeline_widget.get_selected_stream_indices(),
                tracks,
            )

            self.lbl_status.setText("Đã nạp video. Đang quét Keyframe trong nền...")

            # 4. Asynchronously scan keyframes, audio waveforms, and video thumbnails
            self._start_keyframe_scan()
            self._start_audio_waveform_scan()
            self._start_thumbnail_scan()

            # 5. Enable Export and Cancel/Close buttons
            self.btn_export.setEnabled(True)
            self.btn_cancel.setEnabled(True)

            # Re-apply global drag-drop recursively to newly added track widgets
            self._enable_global_drag_drop()

        except Exception as e:
            QMessageBox.critical(self, "Lỗi phân tích video", f"Không thể đọc video:\n{str(e)}")
            self.lbl_status.setText("Lỗi khi nạp video.")

    def _on_timeline_tracks_changed(self, active_indices: list[int]):
        """Callback when user toggles Giữ/Bỏ on any track on the timeline."""
        all_tracks = self._video_info.get("tracks", [])
        self.player_widget.update_active_tracks(active_indices, all_tracks)

    def _start_keyframe_scan(self):
        """Scan keyframes in a separate QThread to keep UI fully responsive."""
        if self._kf_worker and self._kf_worker.isRunning():
            self._kf_worker.cancel()
            self._kf_worker.wait()

        self._kf_worker = KeyframeWorker(self._current_video_path, parent=self)
        self._kf_worker.keyframes_ready.connect(self._on_keyframes_loaded)
        self._kf_worker.start()

    def _on_keyframes_loaded(self, keyframes: list[float]):
        """Callback when background keyframe scan completes."""
        self._keyframes = keyframes
        self.player_widget.set_keyframes(keyframes)
        self.lbl_status.setText(f"Sẵn sàng (Đã nhận diện {len(keyframes)} Keyframes).")

        current_info = self.lbl_video_info.text()
        if "Keyframes:" not in current_info:
            self.lbl_video_info.setText(f"{current_info} | Keyframes: {len(keyframes)}")

    def _start_audio_waveform_scan(self):
        """Extract real audio waveforms for all audio streams in background."""
        if self._audio_worker and self._audio_worker.isRunning():
            self._audio_worker.cancel()
            self._audio_worker.wait()

        audio_tracks = self._video_info.get("audio_tracks", [])
        if audio_tracks:
            self._audio_worker = AudioWaveformWorker(self._current_video_path, audio_tracks, parent=self)
            self._audio_worker.stream_waveform_ready.connect(self.timeline_widget.set_audio_waveform_stream)
            self._audio_worker.waveforms_ready.connect(self.timeline_widget.set_audio_waveforms)
            self._audio_worker.start()

    def _start_thumbnail_scan(self):
        """Extract video frame thumbnails for filmstrip timeline in background."""
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.cancel()
            self._thumb_worker.wait()

        dur_sec = self._video_info.get("duration", 0.0)
        if dur_sec > 0:
            self._thumb_worker = VideoThumbnailWorker(self._current_video_path, dur_sec, parent=self)
            self._thumb_worker.thumbnails_ready.connect(self.timeline_widget.set_video_thumbnails)
            self._thumb_worker.start()

    def closeEvent(self, event):
        """Ensure all background worker threads are cancelled when window is closed."""
        for w in [self._worker, self._kf_worker, self._thumb_worker, self._audio_worker]:
            if w and w.isRunning():
                w.cancel()
                w.wait(400)
        super().closeEvent(event)

    def _start_cut(self):
        if not self._current_video_path:
            QMessageBox.warning(self, "Chưa chọn file", "Vui lòng mở video trước khi cắt.")
            return

        in_sec = self.timeline_widget.get_in_point()
        out_sec = self.timeline_widget.get_out_point()
        snap = self.timeline_widget.is_snap_enabled()

        if out_sec <= in_sec:
            QMessageBox.warning(self, "Lỗi mốc thời gian", "Điểm kết thúc (Out) phải lớn hơn điểm bắt đầu (In).")
            return

        selected_streams = self.timeline_widget.get_selected_stream_indices()
        all_tracks = self._video_info.get("tracks", [])
        if all_tracks and not selected_streams:
            QMessageBox.warning(self, "Chưa chọn track", "Vui lòng giữ lại ít nhất 1 track trên timeline để xuất video!")
            return

        # 1. Sinh tên file mặc định dựa trên thời gian THỰC TẾ lúc người dùng ấn nút Xuất Video
        # Định dạng: "Tên video gốc + giờ + phút + giây + ngày + tháng + năm"
        now_str = datetime.now().strftime("%Hh%Mm%Ss_%d-%m-%Y")
        stem = self._current_video_path.stem
        suffix = self._current_video_path.suffix
        default_filename = f"{stem}_{now_str}{suffix}"

        # Thư mục mặc định chính là thư mục đang lưu file video gốc
        default_dir = self._current_video_path.parent
        suggested_path = default_dir / default_filename

        # 2. Hiện cửa sổ Save As chuẩn của Windows
        filter_str = f"Video File (*{suffix});;All Files (*.*)"
        save_path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu video đã cắt",
            str(suggested_path),
            filter_str,
        )

        # Nếu người dùng bấm Hủy / Cancel trong hộp thoại Save As
        if not save_path_str:
            return

        chosen_path = Path(save_path_str).resolve()

        # Bảo vệ video nguồn: Không cho phép ghi đè lên file video gốc
        if chosen_path == self._current_video_path:
            QMessageBox.warning(
                self,
                "Trùng file nguồn",
                "Không thể lưu đè lên file video gốc! Vui lòng đặt tên khác hoặc chọn thư mục khác.",
            )
            return

        track_ranges = self.timeline_widget.get_track_ranges()
        stream_types = {t.get("stream_index", 0): t.get("codec_type", "video") for t in all_tracks}

        try:
            cmd, eff_start, eff_end = build_cut_command(
                input_path=self._current_video_path,
                output_path=chosen_path,
                start_sec=in_sec,
                end_sec=out_sec,
                snap_keyframe=snap,
                keyframes=self._keyframes,
                selected_stream_indices=selected_streams if all_tracks else None,
                track_ranges=track_ranges,
                stream_types=stream_types,
            )
        except Exception as e:
            QMessageBox.critical(self, "Lỗi thiết lập lệnh", str(e))
            return

        cut_duration = eff_end - eff_start

        # UI state during cutting
        self.btn_export.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        cut_mode = self.timeline_widget.get_cut_mode()
        mode_label = "Từng Track (Smart Hybrid)" if cut_mode == "per_track" else "Đồng bộ"
        self.lbl_status.setText(
            f"Đang xuất [{mode_label}] từ {format_timestamp(eff_start)} đến {format_timestamp(eff_end)}..."
        )

        self._worker = CutWorker(cmd, str(chosen_path), cut_duration, parent=self)
        self._worker.progress_changed.connect(self.progress_bar.setValue)
        self._worker.status_message.connect(self.lbl_status.setText)
        self._worker.finished_success.connect(self._on_cut_success)
        self._worker.failed.connect(self._on_cut_failed)
        self._worker.start()

    def _close_current_video(self):
        """Unload current video, stop playback, cancel workers, and reset UI back to clean initial state."""
        # 1. Cancel any active background workers
        for w in [self._worker, self._kf_worker, self._thumb_worker, self._audio_worker]:
            if w and w.isRunning():
                w.cancel()
                w.wait(200)

        # 2. Reset video info & keyframes
        self._current_video_path = None
        self._video_info = {}
        self._keyframes = []

        # 3. Reset UI labels & status
        self.lbl_video_info.setText("Chưa chọn video (Kéo thả video vào bất kỳ đâu hoặc bấm 'Mở Video')")
        self.lbl_status.setText("Sẵn sàng.")
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)

        # 4. Disable Export and Cancel buttons
        self.btn_export.setEnabled(False)
        self.btn_cancel.setEnabled(False)

        # 5. Clear player viewport and timeline
        self.player_widget.clear_video()
        self.timeline_widget.clear_timeline()

        # 6. Re-ensure drag & drop is active everywhere
        self._enable_global_drag_drop()

    def _on_cut_success(self, output_path: str):
        self.btn_export.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(100)
        self.lbl_status.setText(f"Xuất hoàn tất: {Path(output_path).name}")

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Cắt Video Hoàn Tất!")
        msg_box.setText(
            f"Video đã được cắt thành công 100% Lossless!\n\n"
            f"File xuất ra: {output_path}"
        )
        btn_open_folder = msg_box.addButton("Mở thư mục chứa file", QMessageBox.ButtonRole.ActionRole)
        msg_box.addButton("Đóng", QMessageBox.ButtonRole.RejectRole)
        msg_box.exec()

        if msg_box.clickedButton() == btn_open_folder:
            folder_path = Path(output_path).parent
            if sys.platform == "win32":
                os.startfile(folder_path)

    def _on_cut_failed(self, error_msg: str):
        self.btn_export.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.lbl_status.setText("Cắt video thất bại.")
        QMessageBox.critical(self, "Lỗi khi cắt", error_msg)

    # Drag & Drop Support
    def _enable_global_drag_drop(self):
        """Recursively enable drag and drop across MainWindow and all child widgets."""
        self.setAcceptDrops(True)
        for w in self.findChildren(QWidget):
            w.setAcceptDrops(True)
            w.installEventFilter(self)

    def _extract_dropped_file(self, mime_data) -> Path | None:
        if not mime_data or not mime_data.hasUrls():
            return None
        video_exts = {".mp4", ".mkv", ".mov", ".avi", ".ts", ".webm", ".flv", ".m4v", ".wmv", ".m4a", ".mp3", ".wav"}
        valid_files = []
        for url in mime_data.urls():
            p = None
            local_p = url.toLocalFile()
            if local_p:
                p = Path(local_p).resolve()
            else:
                raw_path = url.path()
                if sys.platform == "win32" and raw_path.startswith("/"):
                    raw_path = raw_path[1:]
                if raw_path:
                    p = Path(raw_path).resolve()
            if p and p.is_file():
                if p.suffix.lower() in video_exts:
                    return p
                valid_files.append(p)
        return valid_files[0] if valid_files else None

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if event.mimeData() and event.mimeData().hasUrls():
                event.acceptProposedAction()
                self.lbl_status.setText("📂 Thả video vào bất kỳ đâu để mở ngay...")
                if watched is getattr(self.player_widget, "drop_overlay", None):
                    return False
                return True
        elif event.type() == QEvent.Type.DragLeave:
            if not self._current_video_path:
                self.lbl_status.setText("Sẵn sàng.")
            else:
                self.lbl_status.setText(f"Sẵn sàng (Đã nhận diện {len(self._keyframes)} Keyframes).")
            if watched is getattr(self.player_widget, "drop_overlay", None):
                return False
        elif event.type() == QEvent.Type.Drop:
            import time
            now = time.time()
            if now - self._last_drop_time < 0.5:
                event.acceptProposedAction()
                return True
            file_path = self._extract_dropped_file(event.mimeData())
            if file_path:
                self._last_drop_time = now
                event.acceptProposedAction()
                self._load_video(file_path)
                return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.lbl_status.setText("📂 Thả video vào bất kỳ đâu để mở ngay...")

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        import time
        now = time.time()
        if now - self._last_drop_time < 0.5:
            event.acceptProposedAction()
            return
        file_path = self._extract_dropped_file(event.mimeData())
        if file_path:
            self._last_drop_time = now
            event.acceptProposedAction()
            self._load_video(file_path)

    # Keyboard Shortcuts
    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.player_widget.play_pause()
        elif key == Qt.Key.Key_I:
            self.timeline_widget._set_in_current()
        elif key == Qt.Key.Key_O:
            self.timeline_widget._set_out_current()
        elif key == Qt.Key.Key_BracketLeft:
            self.player_widget.change_speed(-0.25)
        elif key == Qt.Key.Key_BracketRight:
            self.player_widget.change_speed(0.25)
        elif key == Qt.Key.Key_R:
            self.player_widget.reset_speed()
        else:
            super().keyPressEvent(event)
