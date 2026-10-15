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

from PySide6.QtCore import Qt, QUrl, QEvent, QThread, Signal
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
    QProgressDialog,
    QFrame,
)

from src.core.config import validate_tools, get_tools_dir
from src.core.probe import probe_video_info
from src.core.cutter import (
    build_cut_command,
    format_timestamp,
    generate_snapshot_output_name,
    build_snapshot_command,
)
from src.core.worker import (
    CutWorker,
    KeyframeWorker,
    AudioWaveformWorker,
    SnapshotWorker,
)
from src.ui.player_widget import PlayerWidget
from src.ui.timeline_widget import TimelineWidget
from src.ui.styles import (
    GLOBAL_APP_QSS,
    UNIFIED_BUTTON_STYLE,
    BUTTON_CANCEL_STYLE,
    BUTTON_EXPORT_STYLE,
)


class ToolDownloaderWorker(QThread):
    """Background worker to download and unpack portable FFmpeg & FFprobe."""

    progress_changed = Signal(int, str)
    finished_result = Signal(bool, str)

    def __init__(self, target_dir: Path, parent=None):
        super().__init__(parent)
        self.target_dir = target_dir
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        from src.core.tool_downloader import download_and_extract_tools

        success = download_and_extract_tools(
            self.target_dir,
            progress_callback=lambda p, s: self.progress_changed.emit(p, s),
            cancel_check=lambda: self._is_cancelled,
        )
        if success:
            self.finished_result.emit(True, "Đã cài đặt thành công FFmpeg và FFprobe!")
        else:
            self.finished_result.emit(False, "Tải không thành công hoặc thao tác đã bị hủy.")



class MainWindow(QMainWindow):
    """Main Application Window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lossless Video Cutter - Cắt Video 100% Nguyên Bản")
        self.setStyleSheet(GLOBAL_APP_QSS)

        from src.core.config import get_app_icon_path
        icon_path = get_app_icon_path()
        if icon_path and icon_path.is_file():
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(icon_path)))

        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self._current_video_path: Path | None = None
        self._video_info: dict = {}
        self._keyframes: list[float] = []
        self._worker: CutWorker | None = None
        self._kf_worker: KeyframeWorker | None = None
        self._audio_worker: AudioWaveformWorker | None = None
        self._tool_worker: ToolDownloaderWorker | None = None
        self._snapshot_worker: SnapshotWorker | None = None
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
        self.btn_open_file.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_open_file.setFixedHeight(32)
        self.btn_open_file.clicked.connect(self._select_video_file)

        self.lbl_video_info = QLabel("Chưa chọn video (Kéo thả video vào bất kỳ đâu hoặc bấm 'Mở Video')")
        self.lbl_video_info.setStyleSheet("color: #8b949e; font-size: 13px;")

        top_layout.addWidget(self.btn_open_file)
        top_layout.addWidget(self.lbl_video_info, stretch=1)

        # Right: CapCut Blue Export Button & Cancel / Close Video Button
        self.btn_export = QPushButton("⚡ Xuất Video")
        self.btn_export.setStyleSheet(BUTTON_EXPORT_STYLE)
        self.btn_export.setFixedHeight(32)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._start_cut)

        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.setToolTip("Đóng video hiện tại và làm mới màn hình")
        self.btn_cancel.setStyleSheet(BUTTON_CANCEL_STYLE)
        self.btn_cancel.setFixedHeight(32)
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
        self.timeline_widget.track_selected.connect(self._on_timeline_track_selected)
        self.timeline_widget.in_point_changed.connect(
            lambda in_sec: self.player_widget.set_cut_range(in_sec, self.timeline_widget.get_out_point())
        )
        self.timeline_widget.out_point_changed.connect(
            lambda out_sec: self.player_widget.set_cut_range(self.timeline_widget.get_in_point(), out_sec)
        )
        self.player_widget.speed_changed.connect(self.timeline_widget.sync_zoom_with_speed)
        self.player_widget.snapshot_requested.connect(self._take_snapshot)
        self.player_widget.rotation_changed.connect(self._on_rotation_changed)

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
            self.lbl_status.setText("⚠️ Chưa có công cụ FFmpeg trong thư mục tools/.")

            box = QMessageBox(self)
            box.setWindowTitle("Thiếu công cụ FFmpeg / FFprobe")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(
                "Chưa phát hiện FFmpeg/FFprobe portable trong thư mục 'tools/'!\n\n"
                "Ứng dụng cần FFmpeg và FFprobe để cắt video Lossless nguyên bản.\n"
                "Bạn có muốn ứng dụng tự động tải bản portable chính thức về không?"
            )
            btn_download = box.addButton("⚡ Tải tự động ngay", QMessageBox.ButtonRole.AcceptRole)
            btn_open_folder = box.addButton("📁 Mở thư mục tools", QMessageBox.ButtonRole.ActionRole)
            btn_close = box.addButton("Đóng", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_download)
            box.exec()

            if box.clickedButton() == btn_download:
                self._start_tool_download()
            elif box.clickedButton() == btn_open_folder:
                tools_dir = get_tools_dir()
                tools_dir.mkdir(parents=True, exist_ok=True)
                if sys.platform == "win32":
                    os.startfile(str(tools_dir))

    def _start_tool_download(self):
        tools_dir = get_tools_dir()
        progress_dialog = QProgressDialog("Đang chuẩn bị tải FFmpeg portable...", "Hủy", 0, 100, self)
        progress_dialog.setWindowTitle("Tải FFmpeg & FFprobe Portable")
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setAutoClose(True)
        progress_dialog.setAutoReset(False)
        progress_dialog.setMinimumWidth(480)

        self._tool_worker = ToolDownloaderWorker(tools_dir, parent=self)

        def on_progress(percent: int, text: str):
            progress_dialog.setValue(percent)
            progress_dialog.setLabelText(text)

        def on_finished(success: bool, msg: str):
            progress_dialog.close()
            if success:
                self.lbl_status.setText("✅ Đã sẵn sàng FFmpeg & FFprobe portable.")
                QMessageBox.information(
                    self,
                    "Cài đặt hoàn tất",
                    "Đã tải và giải nén thành công FFmpeg & FFprobe portable vào thư mục tools!\n"
                    "Bây giờ bạn có thể mở và cắt video Lossless bình thường."
                )
            else:
                self.lbl_status.setText("⚠️ Tải FFmpeg thất bại hoặc bị hủy.")
                QMessageBox.warning(
                    self,
                    "Tải thất bại",
                    f"{msg}\n\nVui lòng kiểm tra kết nối mạng hoặc copy thủ công ffmpeg.exe & ffprobe.exe vào thư mục 'tools/'."
                )

        self._tool_worker.progress_changed.connect(on_progress)
        self._tool_worker.finished_result.connect(on_finished)
        progress_dialog.canceled.connect(self._tool_worker.cancel)

        self._tool_worker.start()
        progress_dialog.exec()

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
            init_rot = int(self._video_info.get("rotation", 0))
            self.player_widget.set_initial_rotation(init_rot)
            self.player_widget.update_active_tracks(
                self.timeline_widget.get_selected_stream_indices(),
                tracks,
            )

            self.lbl_status.setText("Đã nạp video. Đang quét Keyframe trong nền...")

            # 4. Asynchronously scan keyframes and audio waveforms in background (zero lag, no thumbnail decode)
            self._start_keyframe_scan()
            self._start_audio_waveform_scan()

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

        # Dynamic Button Text: Switch between "⚡ Xuất Video" and "🎵 Xuất Âm Thanh"
        video_streams = [t for t in all_tracks if t.get("codec_type") == "video"]
        has_video = any(t.get("stream_index") in active_indices for t in video_streams) if video_streams else True
        if not has_video and any(t.get("codec_type") == "audio" and t.get("stream_index") in active_indices for t in all_tracks):
            self.btn_export.setText("🎵 Xuất Âm Thanh")
        else:
            self.btn_export.setText("⚡ Xuất Video")

    def _on_timeline_track_selected(self, stream_index: int):
        """Callback when user clicks/selects a track on the timeline."""
        all_tracks = self._video_info.get("tracks", [])
        self.player_widget.set_active_audio_stream(stream_index, all_tracks)

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
        self.timeline_widget.set_keyframes(keyframes)
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

    def closeEvent(self, event):
        """Ensure all background worker threads are cancelled and media player detached when window is closed."""
        # 1. Safely stop player and detach Direct3D video surface to prevent GPU driver hang on exit
        try:
            self.player_widget.clear_video()
            self.player_widget.player.setVideoOutput(None)
        except Exception:
            pass

        # 2. Cancel all active background workers
        for w in [self._worker, self._kf_worker, self._audio_worker, self._tool_worker, self._snapshot_worker]:
            if w and w.isRunning():
                w.cancel()
                w.wait(100)
        super().closeEvent(event)

    def _start_cut(self):
        if not self._current_video_path:
            QMessageBox.warning(self, "Chưa chọn file", "Vui lòng mở video trước khi cắt.")
            return

        snap = self.timeline_widget.is_snap_enabled()
        cut_mode = self.timeline_widget.get_cut_mode()

        # 1. Đảm bảo luồng quét Keyframe hoàn tất trước khi lấy mốc cắt nếu đang bật Bám Keyframe
        if snap and (not self._keyframes) and self._kf_worker and self._kf_worker.isRunning():
            self.lbl_status.setText("Đang hoàn tất quét Keyframe để bám chuẩn xác...")
            self._kf_worker.wait(4000)

        selected_streams = self.timeline_widget.get_selected_stream_indices()
        all_tracks = self._video_info.get("tracks", [])
        if all_tracks and not selected_streams:
            QMessageBox.warning(self, "Chưa chọn track", "Vui lòng giữ lại ít nhất 1 track trên timeline để xuất!")
            return

        selected_tracks = [t for t in all_tracks if t.get("stream_index") in selected_streams]
        has_video = any(t.get("codec_type") == "video" for t in selected_tracks) if all_tracks else True
        selected_audio = [t for t in selected_tracks if t.get("codec_type") == "audio"]

        # If only audio tracks are selected (no video), audio can cut exactly without video keyframe snapping
        if not has_video:
            snap = False

        # 1. Đảm bảo luồng quét Keyframe hoàn tất trước khi lấy mốc cắt nếu đang bật Bám Keyframe
        if snap and (not self._keyframes) and self._kf_worker and self._kf_worker.isRunning():
            self.lbl_status.setText("Đang hoàn tất quét Keyframe để bám chuẩn xác...")
            self._kf_worker.wait(4000)

        in_sec = self.timeline_widget.get_in_point()
        out_sec = self.timeline_widget.get_out_point()
        if snap and self._keyframes:
            in_sec = self.timeline_widget.snap_to_keyframe(in_sec, force_closest=True)
            out_sec = self.timeline_widget.snap_to_keyframe(out_sec, force_closest=True)
            if out_sec <= in_sec:
                next_kfs = [k for k in self._keyframes if k > in_sec]
                out_sec = next_kfs[0] if next_kfs else self.timeline_widget.get_duration()
            self.timeline_widget.set_in_point(in_sec)
            self.timeline_widget.set_out_point(out_sec)

        if out_sec <= in_sec:
            QMessageBox.warning(self, "Lỗi mốc thời gian", "Điểm kết thúc (Out) phải lớn hơn điểm bắt đầu (In).")
            return

        # 3. Sinh tên file mặc định & Tự động đổi định dạng file audio phù hợp khi bỏ hết video
        now_str = datetime.now().strftime("%Hh%Mm%Ss_%d-%m-%Y")
        stem = self._current_video_path.stem

        AUDIO_CODEC_EXT_MAP = {
            "aac": ".m4a",
            "alac": ".m4a",
            "mp3": ".mp3",
            "opus": ".opus",
            "flac": ".flac",
            "vorbis": ".ogg",
            "ac3": ".ac3",
            "eac3": ".eac3",
            "wav": ".wav",
            "pcm_s16le": ".wav",
            "pcm_s24le": ".wav",
            "pcm_s32le": ".wav",
        }

        if not has_video and selected_audio:
            first_codec = selected_audio[0].get("codec_name", "").lower()
            if len(selected_audio) > 1 and first_codec == "mp3":
                target_ext = ".mka"
            else:
                target_ext = AUDIO_CODEC_EXT_MAP.get(
                    first_codec,
                    ".m4a" if self._current_video_path.suffix.lower() == ".mp4" else ".mka",
                )
            dialog_title = f"Lưu file âm thanh [{first_codec.upper()} Lossless]"
            if target_ext == ".m4a":
                filter_str = "M4A Audio (*.m4a);;AAC Audio (*.aac);;All Files (*.*)"
            elif target_ext == ".mka":
                filter_str = "Matroska Audio (*.mka);;All Files (*.*)"
            else:
                filter_str = f"Audio File (*{target_ext});;All Files (*.*)"
            export_type_label = f"100% Lossless Audio ({first_codec.upper()})"
        else:
            target_ext = self._current_video_path.suffix
            dialog_title = "Lưu video đã cắt"
            filter_str = f"Video File (*{target_ext});;All Files (*.*)"
            export_type_label = "100% Lossless Stream Copy"

        default_filename = f"{stem}_{now_str}{target_ext}"
        default_dir = self._current_video_path.parent
        suggested_path = default_dir / default_filename

        # 4. Hiện cửa sổ Save As chuẩn của Windows
        save_path_str, _ = QFileDialog.getSaveFileName(
            self,
            dialog_title,
            str(suggested_path),
            filter_str,
        )

        # Nếu người dùng bấm Hủy / Cancel trong hộp thoại Save As
        if not save_path_str:
            return

        chosen_path = Path(save_path_str).resolve()
        if not chosen_path.suffix:
            chosen_path = chosen_path.with_suffix(target_ext)

        # Bảo vệ video nguồn: Không cho phép ghi đè lên file video gốc
        if chosen_path == self._current_video_path:
            QMessageBox.warning(
                self,
                "Trùng file nguồn",
                "Không thể lưu đè lên file video gốc! Vui lòng đặt tên khác hoặc chọn thư mục khác.",
            )
            return

        try:
            cmd, eff_start, eff_end = build_cut_command(
                input_path=self._current_video_path,
                output_path=chosen_path,
                start_sec=in_sec,
                end_sec=out_sec,
                snap_keyframe=snap,
                keyframes=self._keyframes,
                selected_stream_indices=selected_streams if all_tracks else None,
                snap_mode="closest",
                rotation=self.player_widget.get_rotation(),
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
        self.lbl_status.setText(
            f"Đang xuất [{export_type_label}]: {format_timestamp(eff_start)} -> {format_timestamp(eff_end)} ({cut_duration:.2f}s)..."
        )

        self._worker = CutWorker(cmd, str(chosen_path), cut_duration, parent=self)
        self._worker.progress_changed.connect(lambda val: self.progress_bar.setValue(int(round(val))))
        self._worker.status_message.connect(self.lbl_status.setText)
        self._worker.finished_success.connect(self._on_cut_success)
        self._worker.failed.connect(self._on_cut_failed)
        self._worker.start()

    def _close_current_video(self):
        """Unload current video, stop playback, cancel workers, and reset UI back to clean initial state."""
        # 1. Cancel any active background workers
        for w in [self._worker, self._kf_worker, self._audio_worker, self._snapshot_worker]:
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

        # 4. Disable Export and Cancel buttons, reset button label
        self.btn_export.setText("⚡ Xuất Video")
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
        msg_box.setWindowTitle("Xuất File Hoàn Tất!")
        msg_box.setText(
            f"File đã được xuất thành công 100% Lossless!\n\n"
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
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        if "hủy" in error_msg.lower():
            self.lbl_status.setText("Đã hủy xuất video theo yêu cầu.")
            QMessageBox.information(self, "Đã hủy xuất video", error_msg)
        else:
            self.lbl_status.setText("Cắt video thất bại.")
            QMessageBox.critical(self, "Lỗi khi cắt", error_msg)

    def _take_snapshot(self):
        """Extract current video frame snapshot at native resolution using FFmpeg."""
        if not self._current_video_path:
            return

        if not self.player_widget.is_video_enabled():
            self.lbl_status.setText("⚠️ Không thể chụp ảnh: Track video đang bị tắt.")
            return

        if self._snapshot_worker and self._snapshot_worker.isRunning():
            self.lbl_status.setText("Đang xử lý bức ảnh trước, vui lòng chờ trong giây lát...")
            return

        cur_ms = self.player_widget.player.position()
        cur_sec = max(0.0, cur_ms / 1000.0)

        try:
            out_path = generate_snapshot_output_name(self._current_video_path, cur_sec, extension=".png")
            rot = self.player_widget.get_rotation()
            cmd = build_snapshot_command(self._current_video_path, out_path, cur_sec, rotation=rot)
        except Exception as e:
            self.lbl_status.setText(f"Lỗi thiết lập chụp ảnh: {str(e)}")
            return

        self.lbl_status.setText(f"📸 Đang chụp ảnh tại {format_timestamp(cur_sec)}...")
        self._snapshot_worker = SnapshotWorker(cmd, out_path, cur_sec, parent=self)
        self._snapshot_worker.finished_success.connect(self._on_snapshot_success)
        self._snapshot_worker.failed.connect(self._on_snapshot_failed)
        self._snapshot_worker.start()

    def _on_rotation_changed(self, rot: int):
        label_map = {0: "0° (Gốc)", 90: "90° (Dọc)", 180: "180° (Lộn ngược)", 270: "270° (Dọc ngược)"}
        lbl = label_map.get(rot % 360, f"{rot}°")
        self.lbl_status.setText(f"⟳ Đã chọn góc xoay: {lbl} (Áp dụng khi xuất video & chụp ảnh)")

    def _on_snapshot_success(self, output_path: str, time_sec: float):
        p = Path(output_path)
        clip_note = ""
        try:
            from PySide6.QtGui import QGuiApplication, QImage
            img = QImage(str(p))
            if not img.isNull():
                QGuiApplication.clipboard().setImage(img)
                clip_note = " (Đã chép vào Clipboard)"
        except Exception:
            pass

        self.lbl_status.setText(f"📸 Đã lưu ảnh: {p.name} [{format_timestamp(time_sec)}]{clip_note}")

    def _on_snapshot_failed(self, error_msg: str):
        self.lbl_status.setText(f"Lỗi khi chụp ảnh: {error_msg}")

    # Drag & Drop Support
    def _enable_global_drag_drop(self):
        """Recursively enable drag and drop across MainWindow and all child widgets."""
        self.setAcceptDrops(True)
        for w in self.findChildren(QWidget):
            w.setAcceptDrops(True)
            w.installEventFilter(self)

    def _extract_dropped_file(self, mime_data) -> Path | None:
        if not mime_data:
            return None
        from urllib.parse import unquote
        video_exts = {".mp4", ".mkv", ".mov", ".avi", ".ts", ".webm", ".flv", ".m4v", ".wmv", ".m4a", ".mp3", ".wav"}
        valid_files = []

        # 1. Check QUrl items
        if mime_data.hasUrls():
            for url in mime_data.urls():
                candidate_paths = []
                local_p = url.toLocalFile()
                if local_p:
                    candidate_paths.append(local_p)
                    candidate_paths.append(unquote(local_p))

                raw_path = url.path()
                if raw_path:
                    raw_unquoted = unquote(raw_path)
                    if sys.platform == "win32" and raw_unquoted.startswith("/"):
                        raw_unquoted = raw_unquoted[1:]
                    candidate_paths.append(raw_unquoted)
                    if sys.platform == "win32" and raw_path.startswith("/"):
                        candidate_paths.append(raw_path[1:])

                for c_path in candidate_paths:
                    try:
                        p = Path(c_path).resolve()
                        if p.is_file():
                            if p.suffix.lower() in video_exts:
                                return p
                            valid_files.append(p)
                    except Exception:
                        pass

        # 2. Check plain text fallback (e.g. copied file paths from Explorer)
        if mime_data.hasText():
            text = mime_data.text().strip().strip('"').strip("'")
            for line in text.splitlines():
                clean_line = unquote(line.strip().strip('"').strip("'"))
                if clean_line.startswith("file:///"):
                    clean_line = clean_line[8:]
                    if sys.platform == "win32" and clean_line.startswith("/"):
                        clean_line = clean_line[1:]
                try:
                    p = Path(clean_line).resolve()
                    if p.is_file():
                        if p.suffix.lower() in video_exts:
                            return p
                        valid_files.append(p)
                except Exception:
                    pass

        return valid_files[0] if valid_files else None

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if event.mimeData() and (event.mimeData().hasUrls() or event.mimeData().hasText()):
                event.acceptProposedAction()
                self.lbl_status.setText("📂 Thả video vào bất kỳ đâu để mở ngay...")
                return True
        elif event.type() == QEvent.Type.DragLeave:
            if not self._current_video_path:
                self.lbl_status.setText("Sẵn sàng.")
            else:
                self.lbl_status.setText(f"Sẵn sàng (Đã nhận diện {len(self._keyframes)} Keyframes).")
            return False
        elif event.type() == QEvent.Type.Drop:
            event.acceptProposedAction()
            import time
            now = time.time()
            if now - self._last_drop_time < 0.5:
                return True
            file_path = self._extract_dropped_file(event.mimeData())
            if file_path:
                self._last_drop_time = now
                self._load_video(file_path)
            return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData() and (event.mimeData().hasUrls() or event.mimeData().hasText()):
            event.acceptProposedAction()
            self.lbl_status.setText("📂 Thả video vào bất kỳ đâu để mở ngay...")

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData() and (event.mimeData().hasUrls() or event.mimeData().hasText()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        event.acceptProposedAction()
        import time
        now = time.time()
        if now - self._last_drop_time < 0.5:
            return
        file_path = self._extract_dropped_file(event.mimeData())
        if file_path:
            self._last_drop_time = now
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
        elif key == Qt.Key.Key_R and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.player_widget.rotate_90()
        elif key == Qt.Key.Key_R:
            self.player_widget.reset_speed()
        elif key == Qt.Key.Key_C or (key == Qt.Key.Key_S and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._take_snapshot()
        else:
            super().keyPressEvent(event)
