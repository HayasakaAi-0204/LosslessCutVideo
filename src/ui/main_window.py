"""Cửa sổ ứng dụng chính cho Lossless Video Cutter.

Bố cục lấy cảm hứng từ CapCut:
- Thanh trên cùng: Mở video, thông số kỹ thuật video và nút Xuất Video màu xanh dương nổi bật.
- Khu vực trung tâm: Trình phát video phản hồi nhanh, FPS cao với các tùy chọn tốc độ phát tùy chỉnh.
- Khu vực dưới cùng: Timeline đa track đầy đủ tính năng với các lane trực quan, thước đo thời gian, dạng sóng và công tắc bật/tắt track.
- Luồng lưu tệp: Nhấp "⚡ Xuất Video" mở hộp thoại Lưu tệp chuẩn của Windows tại thư mục gốc kèm dấu thời gian thời gian thực.
- Mặc định mở ở trạng thái phóng to tối đa màn hình.
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
    QSplitter,
)

from src.core.config import validate_tools, get_tools_dir
from src.core.probe import probe_video_info
from src.core.cutter import (
    build_cut_command,
    format_timestamp,
    generate_snapshot_output_name,
    build_snapshot_command,
)
from src.core.history import HistoryManager, EditState
from src.core.smart_cutter import analyze_smart_cut_plan
from src.core.worker import (
    CutWorker,
    SmartCutWorker,
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
    """Tiến trình ngầm để tải và giải nén FFmpeg & FFprobe portable."""

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
    """Cửa sổ ứng dụng chính."""

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
        self._history = HistoryManager(max_depth=50)
        self._last_committed_state: EditState | None = None

        self._setup_ui()
        self._check_environment()

        # Mặc định mở ở trạng thái phóng to tối đa màn hình
        self.showMaximized()

    def _setup_ui(self):
        central = QWidget(self)
        central.setAcceptDrops(True)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # ---------------------------------------------------------------------
        # 1. Thanh trên cùng: Mở file + Thông tin + Nút Xuất Video xanh dương
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

        # Bên trái: Nút mở file & Thông tin video/audio
        self.btn_open_file = QPushButton("📁 Mở File...")
        self.btn_open_file.setToolTip("Mở file video hoặc âm thanh cần cắt (Phím tắt Ctrl+O)")
        self.btn_open_file.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_open_file.setFixedHeight(32)
        self.btn_open_file.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_open_file.clicked.connect(self._select_video_file)

        self.lbl_video_info = QLabel("")
        self.lbl_video_info.setStyleSheet("color: #8b949e; font-size: 13px;")

        top_layout.addWidget(self.btn_open_file)
        top_layout.addWidget(self.lbl_video_info, stretch=1)

        # Bên phải: Nút Hoàn tác/Làm lại, Phím tắt, Dung lượng ước tính, Nút Xuất Video xanh dương & Nút Hủy / Đóng video
        self.btn_undo = QPushButton("↶ Hoàn tác")
        self.btn_undo.setToolTip("Hoàn tác thao tác chỉnh sửa trước đó (Phím tắt Ctrl+Z)")
        self.btn_undo.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_undo.setFixedHeight(32)
        self.btn_undo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_undo.setEnabled(False)
        self.btn_undo.clicked.connect(self._undo)

        self.btn_redo = QPushButton("↷ Làm lại")
        self.btn_redo.setToolTip("Làm lại thao tác vừa hoàn tác (Phím tắt Ctrl+Y hoặc Ctrl+Shift+Z)")
        self.btn_redo.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_redo.setFixedHeight(32)
        self.btn_redo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_redo.setEnabled(False)
        self.btn_redo.clicked.connect(self._redo)

        self.btn_shortcuts = QPushButton("⌨️ Phím tắt (F1)")
        self.btn_shortcuts.setToolTip("Xem danh sách phím tắt hữu ích (Phím F1 hoặc ?)")
        self.btn_shortcuts.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_shortcuts.setFixedHeight(32)
        self.btn_shortcuts.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_shortcuts.clicked.connect(self._show_shortcuts_dialog)

        self.lbl_estimated_size = QLabel("")
        self.lbl_estimated_size.setStyleSheet("""
            QLabel {
                color: #00d2d3;
                background-color: #252a34;
                border: 1px solid #3b4252;
                border-radius: 5px;
                padding: 4px 10px;
                font-family: 'Segoe UI', monospace;
                font-weight: bold;
                font-size: 12px;
            }
        """)
        self.lbl_estimated_size.setToolTip("Dung lượng ước tính của file sau khi xuất (100% Lossless)")
        self.lbl_estimated_size.setVisible(False)

        self.btn_export = QPushButton("⚡ Xuất Video")
        self.btn_export.setStyleSheet(BUTTON_EXPORT_STYLE)
        self.btn_export.setFixedHeight(32)
        self.btn_export.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._start_cut)

        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.setToolTip("Đóng video hiện tại và làm mới màn hình (Phím Esc)")
        self.btn_cancel.setStyleSheet(BUTTON_CANCEL_STYLE)
        self.btn_cancel.setFixedHeight(32)
        self.btn_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._close_current_video)

        top_layout.addWidget(self.btn_undo)
        top_layout.addWidget(self.btn_redo)
        top_layout.addWidget(self.btn_shortcuts)
        top_layout.addWidget(self.lbl_estimated_size)
        top_layout.addWidget(self.btn_export)
        top_layout.addWidget(self.btn_cancel)

        main_layout.addWidget(top_bar)

        # ---------------------------------------------------------------------
        # 2. Thanh phân chia Splitter linh hoạt: Player & Timeline (Phong cách CapCut)
        # ---------------------------------------------------------------------
        self.splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStyleSheet("""
            QSplitter::handle:vertical {
                background-color: #1a1d24;
                border-top: 1px solid #2c313c;
                border-bottom: 1px solid #2c313c;
                height: 6px;
            }
            QSplitter::handle:vertical:hover {
                background-color: #00d2d3;
                border-color: #00d2d3;
            }
            QSplitter::handle:vertical:pressed {
                background-color: #00b4b5;
                border-color: #00b4b5;
            }
        """)

        # Khung nhìn phát video
        self.player_widget = PlayerWidget(self)
        self.player_widget.file_dropped.connect(self._load_video)
        self.player_widget.open_file_requested.connect(self._select_video_file)
        self.splitter.addWidget(self.player_widget)

        # Timeline đa track phong cách CapCut
        self.timeline_widget = TimelineWidget(self)
        self.timeline_widget.setAcceptDrops(True)
        self.splitter.addWidget(self.timeline_widget)

        # Ưu tiên dãn màn phát video khi cửa sổ phóng to, Timeline giữ theo số lượng track
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)

        init_tl_h = self.timeline_widget.get_ideal_height(1)
        self.splitter.setSizes([600, init_tl_h])

        main_layout.addWidget(self.splitter, stretch=1)

        # Kết nối Trình phát & Timeline
        self.player_widget.position_changed.connect(self.timeline_widget.set_position)
        self.player_widget.duration_changed.connect(self.timeline_widget.set_duration)
        self.timeline_widget.seek_requested.connect(self.player_widget.seek)
        self.timeline_widget.tracks_changed.connect(self._on_timeline_tracks_changed)
        self.timeline_widget.track_selected.connect(self._on_timeline_track_selected)
        self.timeline_widget.in_point_changed.connect(self._on_in_point_changed)
        self.timeline_widget.out_point_changed.connect(self._on_out_point_changed)
        self.player_widget.speed_changed.connect(self.timeline_widget.sync_zoom_with_speed)
        self.player_widget.snapshot_requested.connect(self._take_snapshot)
        self.player_widget.rotation_changed.connect(self._on_rotation_changed)
        self.player_widget.decode_mode_changed.connect(self._on_decode_mode_changed)
        self.timeline_widget.render_mode_changed.connect(self._on_render_mode_changed)
        self.timeline_widget.edit_action_completed.connect(self._record_edit_state)

        # ---------------------------------------------------------------------
        # 4. Thanh trạng thái tinh gọn & Tiến trình ở đáy
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

        # Bật tính năng kéo thả tệp toàn cục trên toàn bộ widget trong cửa sổ
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
        filter_str = (
            "Tất cả tệp Media (*.mp4 *.mkv *.mov *.avi *.ts *.webm *.flv *.wmv *.m4v *.3gp *.mp3 *.m4a *.aac *.flac *.wav *.ogg *.opus *.wma *.mka);;"
            "Tệp Video (*.mp4 *.mkv *.mov *.avi *.ts *.webm *.flv *.wmv *.m4v *.3gp);;"
            "Tệp Âm Thanh (*.mp3 *.m4a *.aac *.flac *.wav *.ogg *.opus *.wma *.mka);;"
            "Tất cả tệp (*.*)"
        )
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file video hoặc âm thanh cần cắt",
            "",
            filter_str,
        )
        if file_path:
            self._load_video(Path(file_path))

    _select_media_file = _select_video_file

    def _load_video(self, video_path: Path):
        for w in [self._worker, self._kf_worker, self._audio_worker, self._snapshot_worker]:
            if w and w.isRunning():
                w.cancel()
                w.wait(100)

        self._current_video_path = video_path.resolve()
        self.lbl_status.setText(f"Đang phân tích: {video_path.name}...")
        self.timeline_widget.clear_preview_data()

        try:
            # 1. Phân tích siêu dữ liệu nhanh (tức thì < 50ms)
            self._video_info = probe_video_info(self._current_video_path)
            self._keyframes = []

            dur_sec = self._video_info.get("duration", 0.0)
            codec = self._video_info.get("video_codec", "")
            has_video = self._video_info.get("has_video", False)
            width = self._video_info.get("width", 0)
            height = self._video_info.get("height", 0)
            fps = self._video_info.get("fps", 0.0)
            tracks = self._video_info.get("tracks", [])

            if has_video:
                info_str = (
                    f"🎬 {video_path.name} | {width}x{height} @ {fps}fps | "
                    f"Codec: {codec.upper()} | {len(tracks)} Tracks | Tổng thời lượng: {format_timestamp(dur_sec)}"
                )
            else:
                audio_tracks = self._video_info.get("audio_tracks", [])
                first_audio = audio_tracks[0] if audio_tracks else {}
                a_codec = first_audio.get("codec_name", "AUDIO").upper()
                details = first_audio.get("details", "")
                info_str = (
                    f"🎵 {video_path.name} | Codec: {a_codec} ({details}) | "
                    f"{len(tracks)} Tracks | Tổng thời lượng: {format_timestamp(dur_sec)}"
                )
            self.lbl_video_info.setText(info_str)

            # 2. Nạp các track vào Timeline đa track CapCut
            self.timeline_widget.set_tracks(tracks)
            self.timeline_widget.set_video_info(self._video_info)
            self.timeline_widget.set_duration(int(dur_sec * 1000))

            # Tự động mở rộng Splitter để hiển thị trọn vẹn toàn bộ các track
            ideal_h = self.timeline_widget.get_ideal_height(len(tracks))
            tot_h = self.splitter.height()
            if tot_h <= 100:
                tot_h = max(600, self.height() - 100)
            player_h = max(200, tot_h - ideal_h)
            self.splitter.setSizes([player_h, ideal_h])

            # 3. Nạp file vào khung nhìn trình phát và khởi tạo phạm vi xem trước
            self.player_widget.load_video(
                self._current_video_path,
                self._keyframes,
                fps=fps,
                codec=codec,
                has_video=has_video,
            )
            self.player_widget.set_cut_range(0.0, dur_sec)
            init_rot = int(self._video_info.get("rotation", 0))
            self.player_widget.set_initial_rotation(init_rot)
            self.player_widget.update_active_tracks(
                self.timeline_widget.get_selected_stream_indices(),
                tracks,
            )
            self._update_estimated_size_display()

            # 4. Quét keyframe và dạng sóng âm thanh không đồng bộ trong nền
            if has_video:
                self.lbl_status.setText("Đã nạp video. Đang quét Keyframe trong nền...")
                self._start_keyframe_scan()
                self.btn_export.setText("⚡ Xuất Video")
            else:
                self._keyframes = []
                self.player_widget.set_keyframes([])
                self.timeline_widget.set_keyframes([])
                self.lbl_status.setText("Sẵn sàng (Chế độ âm thanh Lossless - Cắt chính xác từng mili-giây).")
                self.btn_export.setText("🎵 Xuất Âm Thanh")

            self._start_audio_waveform_scan()

            # 5. Kích hoạt nút Xuất và nút Hủy/Đóng
            self.btn_export.setEnabled(True)
            self.btn_cancel.setEnabled(True)

            # 6. Khởi tạo lịch sử thao tác (Undo/Redo) cho tệp vừa nạp
            self._history.clear()
            self._last_committed_state = self._get_current_edit_state()
            self._update_history_buttons()

            # Áp dụng lại tính năng kéo thả đệ quy cho các widget track mới thêm vào
            self._enable_global_drag_drop()

        except Exception as e:
            QMessageBox.critical(self, "Lỗi phân tích video", f"Không thể đọc video:\n{str(e)}")
            self.lbl_status.setText("Lỗi khi nạp video.")

    def _on_timeline_tracks_changed(self, active_indices: list[int]):
        """Hàm phản hồi khi người dùng chuyển đổi Giữ/Bỏ trên bất kỳ track nào trên timeline."""
        all_tracks = self._video_info.get("tracks", [])
        self.player_widget.update_active_tracks(active_indices, all_tracks)

        # Đổi nhãn nút động: Chuyển đổi giữa "⚡ Xuất Video" và "🎵 Xuất Âm Thanh"
        video_streams = [t for t in all_tracks if t.get("codec_type") == "video"]
        has_active_video = any(t.get("stream_index") in active_indices for t in video_streams) if video_streams else False
        if not has_active_video and any(t.get("codec_type") == "audio" and t.get("stream_index") in active_indices for t in all_tracks):
            self.btn_export.setText("🎵 Xuất Âm Thanh")
        else:
            self.btn_export.setText("⚡ Xuất Video")

        self._update_estimated_size_display()
        self._record_edit_state()

    def _on_in_point_changed(self, in_sec: float):
        self.player_widget.set_cut_range(in_sec, self.timeline_widget.get_out_point())
        self._update_estimated_size_display()

    def _on_out_point_changed(self, out_sec: float):
        self.player_widget.set_cut_range(self.timeline_widget.get_in_point(), out_sec)
        self._update_estimated_size_display()

    def _update_estimated_size_display(self):
        """Cập nhật nhãn dung lượng ước tính cạnh nút Xuất Video."""
        if not self._current_video_path or not self._video_info:
            self.lbl_estimated_size.setVisible(False)
            return

        in_sec = self.timeline_widget.get_in_point()
        out_sec = self.timeline_widget.get_out_point()
        cut_dur = max(0.0, out_sec - in_sec)

        active_indices = self.timeline_widget.get_selected_stream_indices()
        from src.core.cutter import estimate_output_file_size
        bytes_val, size_str = estimate_output_file_size(
            cut_dur,
            self._video_info,
            active_indices,
        )

        if cut_dur > 0 and bytes_val > 0:
            self.lbl_estimated_size.setText(f"💾 {size_str}")
            self.lbl_estimated_size.setToolTip(f"Dung lượng ước tính file xuất: {size_str} (Thời lượng: {cut_dur:.2f}s)")
            self.lbl_estimated_size.setVisible(True)
            self.btn_export.setToolTip(f"Xuất đoạn video đã chọn (Ước tính: {size_str})")
        else:
            self.lbl_estimated_size.setVisible(False)

    def _on_timeline_track_selected(self, stream_index: int):
        """Hàm phản hồi khi người dùng nhấp/chọn một track trên timeline."""
        all_tracks = self._video_info.get("tracks", [])
        self.player_widget.set_active_audio_stream(stream_index, all_tracks)

    def _start_keyframe_scan(self):
        """Quét keyframe trong một QThread riêng để giữ giao diện hoàn toàn mượt mà."""
        if self._kf_worker and self._kf_worker.isRunning():
            self._kf_worker.cancel()
            self._kf_worker.wait()

        self._kf_worker = KeyframeWorker(self._current_video_path, parent=self)
        self._kf_worker.keyframes_ready.connect(self._on_keyframes_loaded)
        self._kf_worker.start()

    def _on_keyframes_loaded(self, keyframes: list[float]):
        """Hàm phản hồi khi tiến trình quét keyframe ngầm hoàn tất."""
        self._keyframes = keyframes
        self.player_widget.set_keyframes(keyframes)
        self.timeline_widget.set_keyframes(keyframes)
        if keyframes:
            self.lbl_status.setText(f"Sẵn sàng (Đã nhận diện {len(keyframes)} Keyframes).")
            current_info = self.lbl_video_info.text()
            if "Keyframes:" not in current_info:
                self.lbl_video_info.setText(f"{current_info} | Keyframes: {len(keyframes)}")
        else:
            self.lbl_status.setText("Sẵn sàng (Chế độ âm thanh Lossless - Cắt chính xác từng mili-giây).")

    def _start_audio_waveform_scan(self):
        """Trích xuất dạng sóng âm thanh thực tế cho tất cả các luồng âm thanh trong nền."""
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
        """Đảm bảo tất cả các luồng worker ngầm bị hủy và giải phóng tài nguyên player an toàn khi đóng cửa sổ."""
        # 1. Dừng và giải phóng an toàn backend player (mpv C threads hoặc Qt Direct3D surface)
        try:
            self.player_widget.cleanup()
        except Exception:
            pass

        # 2. Hủy toàn bộ các worker đang chạy ngầm
        for w in [self._worker, self._kf_worker, self._audio_worker, self._tool_worker, self._snapshot_worker]:
            if w and w.isRunning():
                w.cancel()
                w.wait(100)
        super().closeEvent(event)

    def _start_cut(self):
        if not self._current_video_path:
            QMessageBox.warning(self, "Chưa chọn file", "Vui lòng mở file video hoặc âm thanh trước khi cắt.")
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

        # Nếu chỉ chọn các track âm thanh (không có video), âm thanh có thể cắt chính xác mà không cần bám keyframe video
        if not has_video:
            snap = False

        # 1. Đảm bảo luồng quét Keyframe hoàn tất trước khi lấy mốc cắt nếu đang bật Bám Keyframe
        if snap and (not self._keyframes) and self._kf_worker and self._kf_worker.isRunning():
            self.lbl_status.setText("Đang hoàn tất quét Keyframe để bám chuẩn xác...")
            self._kf_worker.wait(4000)

        in_sec = self.timeline_widget.get_in_point()
        out_sec = self.timeline_widget.get_out_point()
        total_dur = self.timeline_widget.get_duration() or self._video_info.get("duration", 0.0)
        render_mode = self.timeline_widget.get_render_mode()

        # Trong chế độ Stream Copy: Chỉ ép In bám Keyframe để tránh lỗi giải mã
        if render_mode == "copy" and snap and self._keyframes:
            in_sec = self.timeline_widget.snap_to_keyframe(in_sec, force_closest=True)
            self.timeline_widget.set_in_point(in_sec)

        # Điểm Out: Nếu ở gần sát hoặc chạm mốc kết thúc video, giữ nguyên 100% thời lượng video
        if total_dur > 0 and out_sec >= (total_dur - 0.05):
            out_sec = total_dur
            self.timeline_widget.set_out_point(out_sec)

        if out_sec <= in_sec:
            if total_dur > in_sec:
                out_sec = total_dur
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

        # Kiểm tra dung lượng ổ đĩa đích còn trống để bảo vệ file và tránh tràn đĩa
        try:
            import shutil
            from src.core.cutter import estimate_output_file_size, format_file_size
            dest_dir = chosen_path.parent
            _, _, free_bytes = shutil.disk_usage(str(dest_dir))
            active_streams = self.timeline_widget.get_selected_stream_indices()
            cut_duration_pre = max(0.0, out_sec - in_sec)
            est_bytes, est_str = estimate_output_file_size(cut_duration_pre, self._video_info, active_streams)
            safety_margin = 50 * 1024 * 1024  # 50 MB đệm an toàn
            if est_bytes > 0 and free_bytes < (est_bytes + safety_margin):
                free_str = format_file_size(free_bytes)
                reply = QMessageBox.warning(
                    self,
                    "Cảnh báo bộ nhớ đĩa",
                    f"Ổ đĩa lưu trữ ({dest_dir.drive or dest_dir}) chỉ còn trống khoảng {free_str}, "
                    f"trong khi file xuất ước tính cần {est_str}.\n\n"
                    f"Quá trình xuất file có thể bị gián đoạn hoặc hỏng file do tràn ổ cứng.\n"
                    f"Bạn có muốn tiếp tục xuất không?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.No:
                    return
        except Exception:
            pass

        try:
            fps_val = float(self._video_info.get("fps", 0.0))
            rot_val = self.player_widget.get_rotation()

            smart_plan = None
            if render_mode == "smart" and has_video:
                smart_plan = analyze_smart_cut_plan(
                    input_path=self._current_video_path,
                    output_path=chosen_path,
                    start_sec=in_sec,
                    end_sec=out_sec,
                    keyframes=self._keyframes,
                    total_duration=total_dur,
                    video_info=self._video_info,
                    rotation=rot_val,
                    selected_stream_indices=selected_streams if all_tracks else None,
                )

            if smart_plan and smart_plan.needs_smart_cut:
                eff_start = smart_plan.effective_start
                eff_end = smart_plan.effective_end
                cut_duration = max(0.001, eff_end - eff_start)
                self._worker = SmartCutWorker(smart_plan, parent=self)
                export_type_label = "🎯 Smart Cut (Chính xác từng khung hình)"
            else:
                eff_s = smart_plan.effective_start if smart_plan else in_sec
                eff_e = smart_plan.effective_end if smart_plan else out_sec
                cmd, eff_start, eff_end = build_cut_command(
                    input_path=self._current_video_path,
                    output_path=chosen_path,
                    start_sec=eff_s,
                    end_sec=eff_e,
                    snap_keyframe=(render_mode == "copy" and snap),
                    keyframes=self._keyframes,
                    selected_stream_indices=selected_streams if all_tracks else None,
                    snap_mode="closest",
                    rotation=rot_val,
                    total_duration=total_dur,
                    fps=fps_val,
                )
                cut_duration = max(0.001, eff_end - eff_start)
                self._worker = CutWorker(cmd, str(chosen_path), cut_duration, parent=self)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi thiết lập lệnh", str(e))
            return

        # Trạng thái giao diện trong quá trình cắt
        self.btn_export.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText(
            f"Đang xuất [{export_type_label}]: {format_timestamp(eff_start)} -> {format_timestamp(eff_end)} ({cut_duration:.2f}s)..."
        )

        self._worker.progress_changed.connect(lambda val: self.progress_bar.setValue(int(round(val))))
        self._worker.status_message.connect(self.lbl_status.setText)
        self._worker.finished_success.connect(self._on_cut_success)
        self._worker.failed.connect(self._on_cut_failed)
        self._worker.start()

    def _close_current_video(self):
        """Gỡ bỏ video hiện tại, dừng phát, hủy các worker và đặt lại giao diện về ban đầu."""
        # 1. Hủy mọi worker ngầm đang hoạt động
        for w in [self._worker, self._kf_worker, self._audio_worker, self._snapshot_worker]:
            if w and w.isRunning():
                w.cancel()
                w.wait(200)

        # 2. Đặt lại thông tin video & keyframe và giải phóng tham chiếu worker
        self._worker = None
        self._kf_worker = None
        self._audio_worker = None
        self._snapshot_worker = None
        self._current_video_path = None
        self._video_info = {}
        self._keyframes = []

        # 3. Đặt lại các nhãn & trạng thái giao diện
        self.lbl_video_info.setText("")
        self.lbl_status.setText("Sẵn sàng.")
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)

        # 4. Vô hiệu hóa nút Xuất và Hủy, đặt lại nhãn nút
        self.btn_export.setText("⚡ Xuất Video")
        self.btn_export.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.lbl_estimated_size.setVisible(False)
        self.lbl_estimated_size.setText("")

        # 5. Xóa sạch khung nhìn player và timeline
        self.player_widget.clear_video()
        self.timeline_widget.clear_timeline()

        # Đặt lại kích thước Splitter về mặc định (1 track)
        def_h = self.timeline_widget.get_ideal_height(1)
        tot_h = self.splitter.height()
        if tot_h <= 100:
            tot_h = max(600, self.height() - 100)
        self.splitter.setSizes([max(200, tot_h - def_h), def_h])

        # 6. Đặt lại ngăn xếp lịch sử Undo/Redo
        self._history.clear()
        self._last_committed_state = None
        self._update_history_buttons()

        # 7. Đảm bảo tính năng kéo & thả vẫn kích hoạt ở mọi nơi
        self._enable_global_drag_drop()

        # 8. Thu hồi bộ nhớ RAM tức thì
        import gc
        gc.collect()

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
        """Trích xuất ảnh chụp khung hình video hiện tại ở độ phân giải gốc bằng FFmpeg."""
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
        self._record_edit_state()

    def _on_render_mode_changed(self, mode: str):
        if mode == "smart":
            self.lbl_status.setText("Chế độ: 🎯 Thông Minh (SmartCut) - Cắt chính xác từng khung hình bất kỳ.")
        else:
            self.lbl_status.setText("Chế độ: ⚡ Siêu Tốc (Stream Copy) - 100% Lossless, bám Keyframe.")
        self._update_estimated_size_display()
        self._record_edit_state()

    # --- Lịch sử thao tác (Undo / Redo) ---
    def _get_current_edit_state(self) -> EditState:
        in_sec = self.timeline_widget.get_in_point()
        out_sec = self.timeline_widget.get_out_point()
        active_streams = set(self.timeline_widget.get_selected_stream_indices())
        rotation = self.player_widget.get_rotation()
        render_mode = self.timeline_widget.get_render_mode()
        track_ranges = self.timeline_widget.get_track_ranges()
        return EditState(
            in_sec=in_sec,
            out_sec=out_sec,
            active_stream_indices=active_streams,
            rotation=rotation,
            render_mode=render_mode,
            track_cut_ranges=track_ranges,
        )

    def _record_edit_state(self):
        """Ghi nhận thay đổi biên tập vào ngăn xếp lịch sử Undo."""
        if not self._current_video_path or self._history.is_applying_history:
            return
        new_state = self._get_current_edit_state()
        if self._last_committed_state is None:
            self._last_committed_state = new_state
            self._update_history_buttons()
            return
        if self._last_committed_state.is_equal_to(new_state):
            return
        self._history.push_state(self._last_committed_state)
        self._last_committed_state = new_state
        self._update_history_buttons()

    def _apply_edit_state(self, state: EditState):
        """Khôi phục trạng thái biên tập từ snapshot lịch sử mà không gây vòng lặp sự kiện."""
        self._history.set_applying(True)
        try:
            # 1. Điểm In & Out
            self.timeline_widget.set_in_point(state.in_sec)
            self.timeline_widget.set_out_point(state.out_sec)

            # 2. Chế độ cắt (Stream Copy vs Smart Cut)
            self.timeline_widget.set_render_mode(state.render_mode, emit_signal=False)

            # 3. Góc xoay video
            self.player_widget.set_rotation(state.rotation)

            # 4. Kích hoạt track
            self.timeline_widget.set_active_stream_indices(state.active_stream_indices)
            self._on_timeline_tracks_changed(sorted(list(state.active_stream_indices)))

            # 5. Cập nhật nhãn dung lượng ước tính
            self._update_estimated_size_display()
        finally:
            self._history.set_applying(False)
            self._update_history_buttons()

    def _undo(self):
        """Hoàn tác thao tác chỉnh sửa trước đó (Ctrl+Z)."""
        if not self._history.can_undo() or not self._current_video_path:
            return
        cur = self._get_current_edit_state()
        prev = self._history.undo(cur)
        if prev:
            self._apply_edit_state(prev)
            self._last_committed_state = prev
            self.lbl_status.setText("↶ Đã hoàn tác (Undo).")

    def _redo(self):
        """Làm lại thao tác vừa hoàn tác (Ctrl+Y hoặc Ctrl+Shift+Z)."""
        if not self._history.can_redo() or not self._current_video_path:
            return
        cur = self._get_current_edit_state()
        nxt = self._history.redo(cur)
        if nxt:
            self._apply_edit_state(nxt)
            self._last_committed_state = nxt
            self.lbl_status.setText("↷ Đã làm lại (Redo).")

    def _update_history_buttons(self):
        has_media = bool(self._current_video_path)
        if hasattr(self, "btn_undo"):
            self.btn_undo.setEnabled(has_media and self._history.can_undo())
        if hasattr(self, "btn_redo"):
            self.btn_redo.setEnabled(has_media and self._history.can_redo())

    def _on_decode_mode_changed(self, mode: str):
        label = "Phần cứng GPU (*H/W)" if mode == "hw" else "Phần mềm CPU (S/W - an toàn)"
        self.lbl_status.setText(f"Chế độ giải mã video: {label}")

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

    # Hỗ trợ Kéo & Thả
    def _enable_global_drag_drop(self):
        """Kích hoạt đệ quy tính năng kéo và thả trên MainWindow và toàn bộ widget con."""
        self.setAcceptDrops(True)
        for w in self.findChildren(QWidget):
            w.setAcceptDrops(True)
            w.installEventFilter(self)

    def _extract_dropped_file(self, mime_data) -> Path | None:
        if not mime_data:
            return None
        from urllib.parse import unquote
        media_exts = {
            # Video
            ".mp4", ".mkv", ".mov", ".avi", ".ts", ".webm", ".flv", ".m4v", ".wmv", ".3gp",
            # Audio
            ".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".wma", ".mka",
        }
        valid_files = []

        # 1. Kiểm tra các mục QUrl
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
                            if p.suffix.lower() in media_exts:
                                return p
                            valid_files.append(p)
                    except Exception:
                        pass

        # 2. Kiểm tra văn bản thuần dự phòng (ví dụ đường dẫn copy từ Explorer)
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
                        if p.suffix.lower() in media_exts:
                            return p
                        valid_files.append(p)
                except Exception:
                    pass

        return valid_files[0] if valid_files else None

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if event.mimeData() and (event.mimeData().hasUrls() or event.mimeData().hasText()):
                event.acceptProposedAction()
                self.lbl_status.setText("📂 Thả video hoặc âm thanh vào bất kỳ đâu để mở ngay...")
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
            self.lbl_status.setText("📂 Thả video hoặc âm thanh vào bất kỳ đâu để mở ngay...")

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

    def _show_shortcuts_dialog(self):
        """Mở cửa sổ hiển thị danh sách phím tắt nhanh và phục hồi focus an toàn."""
        if getattr(self, "_shortcuts_dialog_active", False):
            return
        self._shortcuts_dialog_active = True
        try:
            from src.ui.shortcuts_dialog import ShortcutsDialog
            dialog = ShortcutsDialog(self)
            dialog.exec()
        finally:
            self._shortcuts_dialog_active = False
            # Phục hồi focus hoàn toàn cho MainWindow để các phím tắt tiếp tục hoạt động ngay
            self.setFocus()
            self.activateWindow()

    # Phím tắt bàn phím
    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        modifiers = event.modifiers()

        # 0. Hoàn tác (Undo: Ctrl+Z) & Làm lại (Redo: Ctrl+Y / Ctrl+Shift+Z)
        if key == Qt.Key.Key_Z and (modifiers & Qt.KeyboardModifier.ControlModifier) and not (modifiers & Qt.KeyboardModifier.ShiftModifier):
            self._undo()
            return
        if (key == Qt.Key.Key_Y and (modifiers & Qt.KeyboardModifier.ControlModifier)) or \
           (key == Qt.Key.Key_Z and (modifiers & Qt.KeyboardModifier.ControlModifier) and (modifiers & Qt.KeyboardModifier.ShiftModifier)):
            self._redo()
            return

        # 1. Bật/Đóng bảng phím tắt: F1 hoặc ?
        if key == Qt.Key.Key_F1 or key == Qt.Key.Key_Question:
            self._show_shortcuts_dialog()
            return

        # 2. Mở video nhanh: Ctrl + O
        if key == Qt.Key.Key_O and (modifiers & Qt.KeyboardModifier.ControlModifier):
            self._select_video_file()
            return

        # 3. Xuất video nhanh: Ctrl + E hoặc Enter
        if (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or
            (key == Qt.Key.Key_E and (modifiers & Qt.KeyboardModifier.ControlModifier))):
            if self.btn_export.isEnabled():
                self._start_cut()
            return

        # 4. Hủy / Đóng video hiện tại: Escape
        if key == Qt.Key.Key_Escape:
            if self._current_video_path and self.btn_cancel.isEnabled():
                self._close_current_video()
            return

        # 5. Phát / Tạm dừng video
        if key == Qt.Key.Key_Space:
            self.player_widget.play_pause()
            return

        # 6. Đặt mốc cắt In / Out
        if key == Qt.Key.Key_I:
            self.timeline_widget._set_in_current()
            return
        if key == Qt.Key.Key_O:
            self.timeline_widget._set_out_current()
            return

        # 6b. Chuyển đổi chế độ cắt (Copy ↔ SmartCut): Phím M hoặc Ctrl + M
        if key == Qt.Key.Key_M:
            self.timeline_widget.toggle_render_mode()
            return

        # 7. Tua khung hình (Left / Right / Comma / Period)
        if key == Qt.Key.Key_Left:
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                self.player_widget.step_keyframe(-1)
            else:
                self.player_widget.step_frame(-1)
            return
        if key == Qt.Key.Key_Right:
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                self.player_widget.step_keyframe(1)
            else:
                self.player_widget.step_frame(1)
            return
        if key == Qt.Key.Key_Comma:
            self.player_widget.step_frame(-1)
            return
        if key == Qt.Key.Key_Period:
            self.player_widget.step_frame(1)
            return

        # 8. Nhảy Keyframe: J / L
        if key == Qt.Key.Key_J:
            self.player_widget.step_keyframe(-1)
            return
        if key == Qt.Key.Key_L:
            self.player_widget.step_keyframe(1)
            return

        # 9. Tốc độ phát video
        if key == Qt.Key.Key_BracketLeft:
            self.player_widget.change_speed(-0.25)
            return
        if key == Qt.Key.Key_BracketRight:
            self.player_widget.change_speed(0.25)
            return
        if key == Qt.Key.Key_R and (modifiers & Qt.KeyboardModifier.ControlModifier):
            self.player_widget.rotate_90()
            return
        if key == Qt.Key.Key_R:
            self.player_widget.reset_speed()
            return

        # 10. Chụp ảnh khung hình
        if key == Qt.Key.Key_C or (key == Qt.Key.Key_S and (modifiers & Qt.KeyboardModifier.ControlModifier)):
            self._take_snapshot()
            return

        # 11. Chuyển đổi giải mã phần cứng GPU và CPU (H/W ↔ S/W)
        if key == Qt.Key.Key_H and not (modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            self.player_widget.toggle_hw_sw()
            return

        super().keyPressEvent(event)

    def closeEvent(self, event):
        """Dọn dẹp và giải phóng tài nguyên an toàn khi đóng ứng dụng."""
        if hasattr(self, "player_widget") and self.player_widget:
            self.player_widget.cleanup()
        super().closeEvent(event)
