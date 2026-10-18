"""Widget khung phát video xem trước hỗ trợ bộ lõi mpv và dự phòng Qt Multimedia."""

from datetime import datetime
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QUrl, Signal, QObject, QEvent
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QPixmap
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QLabel,
    QComboBox,
    QStackedWidget,
)

from src.core.config import get_project_root, has_mpv, has_hardware_av1_decode
from src.ui.styles import UNIFIED_BUTTON_STYLE, UNIFIED_ICON_BUTTON_STYLE, BUTTON_HW_STYLE, BUTTON_SW_STYLE

SPEED_PRESETS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]


class ClickableVideoWidget(QVideoWidget):
    """Lớp kế thừa QVideoWidget hỗ trợ phát/dừng khi click chuột và chuyển tiếp focus về MainWindow."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        main_win = self.window()
        if main_win:
            main_win.setFocus()
        super().mousePressEvent(event)


class MpvSignalBridge(QObject):
    """Cầu nối tín hiệu Qt an toàn để chuyển tiếp sự kiện từ luồng ngầm C của libmpv sang GUI thread."""

    position_changed = Signal(int)   # ms
    duration_changed = Signal(int)   # ms
    pause_changed = Signal(bool)     # True (tạm dừng) / False (đang phát)
    eof_reached = Signal()


class _CompatAudio:
    """Lớp hỗ trợ tương thích ngược cho các nơi truy vấn audio_output."""

    def __init__(self, parent):
        self._parent = parent

    def setVolume(self, val: float):
        self._parent._on_volume_changed(int(val * 100))

    def setMuted(self, muted: bool):
        if self._parent._engine_type == "mpv" and self._parent.mpv_player:
            try:
                self._parent.mpv_player.mute = muted
            except Exception:
                pass


class _CompatPlayer:
    """Lớp hỗ trợ tương thích ngược cho các nơi truy vấn thuộc tính player."""

    def __init__(self, parent):
        self._parent = parent

    def setVideoOutput(self, *args, **kwargs):
        pass

    def stop(self):
        self._parent.clear_video()

    def pause(self):
        if self._parent._engine_type == "mpv" and self._parent.mpv_player:
            try:
                self._parent.mpv_player.pause = True
            except Exception:
                pass
        elif self._parent._qt_player:
            self._parent._qt_player.pause()

    def play(self):
        if self._parent._engine_type == "mpv" and self._parent.mpv_player:
            try:
                self._parent.mpv_player.pause = False
            except Exception:
                pass
        elif self._parent._qt_player:
            self._parent._qt_player.play()

    def position(self) -> int:
        return self._parent._current_pos_ms

    def duration(self) -> int:
        if self._parent._engine_type == "mpv" and self._parent.mpv_player:
            dur = getattr(self._parent.mpv_player, "duration", 0)
            return int(float(dur or 0) * 1000)
        return self._parent._qt_player.duration() if self._parent._qt_player else 0

    def setPosition(self, pos: int):
        self._parent.seek(pos)

    def setSource(self, *args):
        pass

    def source(self) -> QUrl:
        if self._parent._current_file_path:
            return QUrl.fromLocalFile(str(self._parent._current_file_path))
        return QUrl()

    def playbackState(self) -> QMediaPlayer.PlaybackState:
        if self._parent._engine_type == "mpv" and self._parent.mpv_player:
            is_paused = getattr(self._parent.mpv_player, "pause", True)
            if is_paused:
                return QMediaPlayer.PlaybackState.PausedState
            return QMediaPlayer.PlaybackState.PlayingState
        if self._parent._qt_player:
            return self._parent._qt_player.playbackState()
        return QMediaPlayer.PlaybackState.StoppedState


class PlayerWidget(QWidget):
    """Khung xem trước video tích hợp điều khiển phát, tua từng frame/keyframe, xoay và chụp ảnh."""

    position_changed = Signal(int)   # ms
    duration_changed = Signal(int)   # ms
    file_dropped = Signal(Path)
    speed_changed = Signal(float)   # Tốc độ phát (0.25 .. 2.0)
    snapshot_requested = Signal()
    rotation_changed = Signal(int)
    decode_mode_changed = Signal(str)  # "hw" hoặc "sw"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keyframes: list[float] = []
        self._fps: float = 30.0
        self._in_point_ms: int = 0
        self._out_point_ms: int = 0
        self._pending_first_frame: bool = False
        self._current_speed: float = 1.0
        self._current_rotation: int = 0
        self._initial_rotation: int = 0
        self._player_failed: bool = False
        self._current_file_path: Path | None = None
        self._current_pos_ms: int = 0
        self._preview_worker = None
        self._engine_type: str = "qt"  # "mpv" hoặc "qt"
        self._decode_mode: str = "hw"  # "hw" (Phần cứng GPU) hoặc "sw" (Phần mềm CPU)
        self._user_forced_decode_mode: str | None = None
        self._current_codec: str = ""

        self._qt_player = None
        self._qt_audio_output = None
        self.mpv_player = None
        self.bridge = None
        self._compat_audio = _CompatAudio(self)
        self._compat_player = _CompatPlayer(self)

        self._setup_ui()
        self._setup_player()

    @property
    def player(self):
        if self._engine_type == "qt" and self._qt_player is not None:
            return self._qt_player
        return self._compat_player

    @property
    def audio_output(self):
        if self._engine_type == "qt" and self._qt_audio_output is not None:
            return self._qt_audio_output
        return self._compat_audio

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Khung chứa video xếp lớp (nền đen thuần)
        self.viewport_stack = QStackedWidget(self)
        self.viewport_stack.setMinimumSize(480, 270)
        self.viewport_stack.setStyleSheet("background-color: #000000;")

        # Lớp 0: Khung hiển thị video thực tế
        self.video_widget = ClickableVideoWidget(self)
        self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video_widget.clicked.connect(self.play_pause)
        self.viewport_stack.addWidget(self.video_widget)

        # Lớp 1: Khung phủ khi track video bị tắt (khi người dùng bấm [Bỏ] track Video)
        self.overlay_disabled = QWidget(self)
        self.overlay_disabled.setStyleSheet("background-color: #0f1115; border-radius: 4px;")
        overlay_layout = QVBoxLayout(self.overlay_disabled)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_icon = QLabel("🎬❌")
        lbl_icon.setStyleSheet("font-size: 40px;")
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_msg = QLabel("Track Video Đang Bị Tắt (Bỏ Qua)")
        lbl_msg.setStyleSheet("color: #e74c3c; font-size: 16px; font-weight: bold; margin-top: 8px;")
        lbl_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_sub = QLabel(
            "Hình ảnh video sẽ không hiển thị trong xem trước và không xuất ra file.\n"
            "Bấm '✓ Giữ' trên thanh Timeline nếu bạn muốn bật lại video."
        )
        lbl_sub.setStyleSheet("color: #8b949e; font-size: 12px; margin-top: 4px;")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

        overlay_layout.addWidget(lbl_icon)
        overlay_layout.addWidget(lbl_msg)
        overlay_layout.addWidget(lbl_sub)
        self.viewport_stack.addWidget(self.overlay_disabled)

        # Lớp 2: Khung phủ khi giải mã phần cứng không hỗ trợ (chuyển sang chế độ CPU an toàn)
        self.overlay_fallback = QWidget(self)
        self.overlay_fallback.setStyleSheet("background-color: #0f1115; border-radius: 4px;")
        fallback_layout = QVBoxLayout(self.overlay_fallback)
        fallback_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fallback_layout.setContentsMargins(12, 12, 12, 12)
        fallback_layout.setSpacing(8)

        self.lbl_fallback_preview = QLabel(self)
        self.lbl_fallback_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_fallback_preview.setMinimumSize(320, 180)
        self.lbl_fallback_preview.setStyleSheet("background-color: #000000; border: 1px dashed #3b4252; border-radius: 6px;")
        fallback_layout.addWidget(self.lbl_fallback_preview, stretch=1)

        info_box = QWidget(self)
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_fallback_title = QLabel("⚡ Chế độ xem trước tương thích (CPU libdav1d)")
        self.lbl_fallback_title.setStyleSheet("color: #00d2d3; font-size: 14px; font-weight: bold;")
        self.lbl_fallback_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_fallback_desc = QLabel(
            "Card đồ họa (GPU) không giải mã được video này qua phần cứng. Ứng dụng đã tự động\n"
            "kích hoạt chế độ CPU an toàn. Bạn vẫn có thể tua khung hình, cắt từng track, bám Keyframe,\n"
            "nghe âm thanh và Xuất Video Lossless 100% nguyên bản hoàn toàn bình thường!"
        )
        self.lbl_fallback_desc.setStyleSheet("color: #8b949e; font-size: 12px;")
        self.lbl_fallback_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)

        info_layout.addWidget(self.lbl_fallback_title)
        info_layout.addWidget(self.lbl_fallback_desc)
        fallback_layout.addWidget(info_box)

        self.viewport_stack.addWidget(self.overlay_fallback)

        # Gắn viewport trực tiếp vào layout chính
        layout.addWidget(self.viewport_stack, stretch=1)

        # Thanh công cụ điều khiển
        controls_layout = QHBoxLayout()

        self.btn_prev_kf = QPushButton("⏮ Keyframe Trước")
        self.btn_prev_kf.setToolTip("Nhảy lùi về Keyframe (I-frame) gần nhất")
        self.btn_prev_kf.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_prev_kf.setFixedHeight(30)
        self.btn_prev_kf.clicked.connect(lambda: self.step_keyframe(-1))

        self.btn_step_back = QPushButton("◀ 1 Frame")
        self.btn_step_back.setToolTip("Lùi 1 khung hình (~0.033s)")
        self.btn_step_back.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_step_back.setFixedHeight(30)
        self.btn_step_back.clicked.connect(lambda: self.step_frame(-1))

        self.btn_play_pause = QPushButton("▶ Phát")
        self.btn_play_pause.setStyleSheet(UNIFIED_BUTTON_STYLE + " QPushButton { min-width: 80px; }")
        self.btn_play_pause.setFixedHeight(30)
        self.btn_play_pause.clicked.connect(self.play_pause)

        self.btn_step_forward = QPushButton("1 Frame ▶")
        self.btn_step_forward.setToolTip("Tiến 1 khung hình (~0.033s)")
        self.btn_step_forward.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_step_forward.setFixedHeight(30)
        self.btn_step_forward.clicked.connect(lambda: self.step_frame(1))

        self.btn_next_kf = QPushButton("Keyframe Tiếp ⏭")
        self.btn_next_kf.setToolTip("Nhảy tiến tới Keyframe (I-frame) kế tiếp")
        self.btn_next_kf.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_next_kf.setFixedHeight(30)
        self.btn_next_kf.clicked.connect(lambda: self.step_keyframe(1))

        # Điều khiển tốc độ phát: [ ➖ ] [ 1.00x ▾ ] [ ➕ ] (0.25x - 2.00x)
        self.lbl_speed = QLabel("Tốc độ:")
        self.lbl_speed.setStyleSheet("color: #ecf0f1; font-weight: bold; font-size: 13px;")

        self.btn_speed_down = QPushButton("-")
        self.btn_speed_down.setToolTip("Giảm tốc độ phát (Phím [)")
        self.btn_speed_down.setFixedSize(28, 28)
        self.btn_speed_down.setStyleSheet(UNIFIED_ICON_BUTTON_STYLE)
        self.btn_speed_down.clicked.connect(lambda: self.change_speed(-0.25))

        self.combo_speed = QComboBox(self)
        self.combo_speed.setToolTip("Chọn tốc độ phát (0.25x - 2.00x, phím [ / ] hoặc R để đặt về 1x)")
        for s in SPEED_PRESETS:
            self.combo_speed.addItem(f"{s:.2f}x")
        self.combo_speed.setCurrentText("1.00x")
        self.combo_speed.setFixedHeight(28)
        self.combo_speed.setFixedWidth(78)
        self.combo_speed.setStyleSheet("""
            QComboBox {
                background-color: #252a34;
                color: #00d2d3;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid #3b4252;
                border-radius: 5px;
                padding-left: 8px;
            }
            QComboBox:hover {
                border-color: #00d2d3;
            }
            QComboBox::drop-down {
                border: none;
                width: 18px;
            }
            QComboBox QAbstractItemView {
                background-color: #252a34;
                color: #ffffff;
                selection-background-color: #0084ff;
                selection-color: #ffffff;
                border: 1px solid #3b4252;
            }
        """)
        self.combo_speed.currentTextChanged.connect(self._on_combo_speed_changed)

        self.btn_speed_up = QPushButton("+")
        self.btn_speed_up.setToolTip("Tăng tốc độ phát (Phím ])")
        self.btn_speed_up.setFixedSize(28, 28)
        self.btn_speed_up.setStyleSheet(UNIFIED_ICON_BUTTON_STYLE)
        self.btn_speed_up.clicked.connect(lambda: self.change_speed(0.25))

        # Điều khiển âm lượng
        self.lbl_vol = QLabel("🔊")
        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(100)
        self.slider_vol.setMaximumWidth(80)
        self.slider_vol.valueChanged.connect(self._on_volume_changed)

        # Nút Chụp Ảnh (Lưu khung hình hiện tại ở độ phân giải gốc 100%)
        self.btn_snapshot = QPushButton("📸 Chụp Ảnh")
        self.btn_snapshot.setToolTip("Chụp ảnh khung hình hiện tại ở độ phân giải gốc (Phím tắt C)")
        self.btn_snapshot.setEnabled(False)
        self.btn_snapshot.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_snapshot.setFixedHeight(30)
        self.btn_snapshot.clicked.connect(self.snapshot_requested.emit)

        # Nút Xoay video (Xoay hướng hiển thị metadata: 0 -> 90 -> 180 -> 270)
        self.btn_rotate = QPushButton("⟳ Xoay: 0°")
        self.btn_rotate.setToolTip("Xoay hướng hiển thị video theo chiều kim đồng hồ 90° (Áp dụng khi xuất file & chụp ảnh, phím tắt Ctrl+R)")
        self.btn_rotate.setEnabled(False)
        self.btn_rotate.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_rotate.setFixedHeight(30)
        self.btn_rotate.clicked.connect(self.rotate_90)

        # Nút chuyển đổi H/W và S/W (Giải mã phần cứng GPU vs giải mã phần mềm CPU)
        self.btn_hw_sw = QPushButton("*H/W")
        self.btn_hw_sw.setToolTip("Giải mã phần cứng (GPU) - Click để chuyển sang S/W (CPU an toàn)")
        self.btn_hw_sw.setEnabled(False)
        self.btn_hw_sw.setStyleSheet(BUTTON_HW_STYLE)
        self.btn_hw_sw.setFixedHeight(30)
        self.btn_hw_sw.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_hw_sw.clicked.connect(self.toggle_hw_sw)

        controls_layout.addWidget(self.btn_prev_kf)
        controls_layout.addWidget(self.btn_step_back)
        controls_layout.addWidget(self.btn_play_pause)
        controls_layout.addWidget(self.btn_step_forward)
        controls_layout.addWidget(self.btn_next_kf)
        controls_layout.addSpacing(6)
        controls_layout.addWidget(self.btn_snapshot)
        controls_layout.addWidget(self.btn_rotate)
        controls_layout.addWidget(self.btn_hw_sw)
        controls_layout.addStretch()
        controls_layout.addWidget(self.lbl_speed)
        controls_layout.addWidget(self.btn_speed_down)
        controls_layout.addWidget(self.combo_speed)
        controls_layout.addWidget(self.btn_speed_up)
        controls_layout.addSpacing(10)
        controls_layout.addWidget(self.lbl_vol)
        controls_layout.addWidget(self.slider_vol)

        layout.addLayout(controls_layout)

    def _setup_player(self):
        """Khởi tạo engine phát video.

        Ưu tiên bộ lõi mpv phần cứng/phần mềm thích ứng cao.
        Nếu thiếu mpv-2.dll hoặc python-mpv, tự động chuyển đổi dự phòng sang Qt Multimedia an toàn.
        """
        self._engine_type = "qt"
        if has_mpv():
            try:
                import locale
                try:
                    locale.setlocale(locale.LC_NUMERIC, "C")
                except Exception:
                    pass

                import mpv

                self.bridge = MpvSignalBridge(self)
                self.bridge.position_changed.connect(self._on_mpv_position_changed, Qt.ConnectionType.QueuedConnection)
                self.bridge.duration_changed.connect(self._on_mpv_duration_changed, Qt.ConnectionType.QueuedConnection)
                self.bridge.pause_changed.connect(self._on_mpv_pause_changed, Qt.ConnectionType.QueuedConnection)
                self.bridge.eof_reached.connect(self._on_mpv_eof_reached, Qt.ConnectionType.QueuedConnection)

                # Cấu hình libmpv:
                # - wid: gắn trực tiếp vào HWND của video_widget
                # - hwdec='auto-safe': tự động chọn giải mã phần cứng GPU (D3D11VA/NVDEC),
                #   tự động rơi về CPU libdav1d mượt mà nếu GPU cũ không có phần cứng AV1
                # - input_default_bindings=False, input_vo_keyboard=False, input_cursor=False:
                #   cách ly hoàn toàn sự kiện chuột/phím để không cướp phím tắt của Qt
                # - keep_open='yes': giữ nguyên khung hình cuối cùng khi hết video
                self.mpv_player = mpv.MPV(
                    wid=str(int(self.video_widget.winId())),
                    hwdec="auto-safe",
                    vo="gpu",
                    keep_open="yes",
                    input_default_bindings=False,
                    input_vo_keyboard=False,
                    input_cursor=False,
                    osc=False,
                    osd_level=0,
                    ytdl=False,
                )

                @self.mpv_player.property_observer("time-pos")
                def _on_time_pos(_name, val):
                    if val is not None:
                        self.bridge.position_changed.emit(int(float(val) * 1000))

                @self.mpv_player.property_observer("duration")
                def _on_duration(_name, val):
                    if val is not None and float(val) > 0:
                        self.bridge.duration_changed.emit(int(float(val) * 1000))

                @self.mpv_player.property_observer("pause")
                def _on_pause(_name, val):
                    if val is not None:
                        self.bridge.pause_changed.emit(bool(val))

                @self.mpv_player.property_observer("eof-reached")
                def _on_eof(_name, val):
                    if val:
                        self.bridge.eof_reached.emit()

                self._engine_type = "mpv"
            except Exception as e:
                print(f"[PlayerWidget] Khởi tạo mpv không thành công ({e}), chuyển sang dự phòng Qt Multimedia.")
                self._engine_type = "qt"

        if self._engine_type == "qt":
            self._setup_qt_player()

    def _setup_qt_player(self):
        """Khởi tạo engine dự phòng PySide6 Qt Multimedia."""
        self._qt_player = QMediaPlayer(self)
        self._qt_audio_output = QAudioOutput(self)
        self._qt_player.setAudioOutput(self._qt_audio_output)
        self._qt_player.setVideoOutput(self.video_widget)

        self._qt_player.positionChanged.connect(self._on_position_changed)
        self._qt_player.durationChanged.connect(self._on_duration_changed)
        self._qt_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._qt_player.errorOccurred.connect(self._on_player_error)

    # -------------------------------------------------------------------------
    # Các hàm phản hồi tín hiệu từ libmpv C thread thông qua MpvSignalBridge
    # -------------------------------------------------------------------------
    def _on_mpv_position_changed(self, pos_ms: int):
        self._current_pos_ms = pos_ms
        self.position_changed.emit(pos_ms)

    def _on_mpv_duration_changed(self, dur_ms: int):
        if dur_ms > 0:
            self.duration_changed.emit(dur_ms)

    def _on_mpv_pause_changed(self, is_paused: bool):
        self.btn_play_pause.setText("▶ Phát" if is_paused else "⏸ Tạm dừng")

    def _on_mpv_eof_reached(self):
        if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
            try:
                self.mpv_player.pause = True
            except Exception:
                pass
        self.btn_play_pause.setText("▶ Phát")

    # -------------------------------------------------------------------------
    # Các hàm phản hồi tín hiệu từ PySide6 QMediaPlayer (dự phòng)
    # -------------------------------------------------------------------------
    def _on_player_error(self, error, error_string):
        try:
            log_dir = get_project_root() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "player_error.log", "a", encoding="utf-8") as f:
                p_err = self._qt_player.errorString() if self._qt_player else ""
                f.write(f"[{datetime.now().isoformat()}] Code: {error} | Msg: {error_string} | PlayerErr: {p_err}\n")
        except Exception:
            pass

        if self._decode_mode == "hw":
            print("[PlayerWidget] Gặp lỗi giải mã phần cứng GPU, tự động chuyển đổi an toàn sang S/W (CPU)...")
            self.set_decode_mode("sw", reload=True, user_action=False)
            return

        self._player_failed = True
        if self.is_video_enabled():
            self.viewport_stack.setCurrentIndex(2)
            self._request_fallback_preview(self._current_pos_ms)

    def _on_position_changed(self, pos_ms: int):
        self._current_pos_ms = pos_ms
        if self._qt_player:
            dur_ms = self._qt_player.duration()
            if dur_ms > 0 and pos_ms >= dur_ms:
                self._qt_player.pause()
                self.btn_play_pause.setText("▶ Phát")
        self.position_changed.emit(pos_ms)

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            if self._decode_mode == "hw":
                self._on_player_error(QMediaPlayer.Error.FormatError, "Tự động kích hoạt bộ giải mã CPU an toàn")
                return
            self._on_player_error(QMediaPlayer.Error.FormatError, "Hệ thống không hỗ trợ định dạng này.")
            return

        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            if self._pending_first_frame:
                self._pending_first_frame = False
                if self._qt_player:
                    self._qt_player.setPosition(0)
                    self._qt_player.pause()
                self.video_widget.update()
                self.btn_play_pause.setText("▶ Phát")

    def _on_duration_changed(self, dur_ms: int):
        if dur_ms > 0:
            if self._pending_first_frame:
                self._pending_first_frame = False
                if self._qt_player:
                    self._qt_player.pause()
                    self._qt_player.setPosition(0)
                self.btn_play_pause.setText("▶ Phát")
            self.duration_changed.emit(dur_ms)

    # -------------------------------------------------------------------------
    # Các hàm điều khiển phát / tua / xoay / âm lượng
    # -------------------------------------------------------------------------
    def rotate_90(self):
        """Xoay theo chiều kim đồng hồ 90 độ."""
        self._current_rotation = (self._current_rotation + 90) % 360
        self._update_rotate_button_ui()
        if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
            try:
                self.mpv_player.video_rotate = self._current_rotation
            except Exception:
                try:
                    self.mpv_player["video-rotate"] = self._current_rotation
                except Exception:
                    pass
        self.rotation_changed.emit(self._current_rotation)

    def set_initial_rotation(self, rot: int):
        """Đặt góc xoay ban đầu bóc tách từ metadata file."""
        self._initial_rotation = int(rot) % 360
        self._current_rotation = self._initial_rotation
        self._update_rotate_button_ui()
        if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
            try:
                self.mpv_player.video_rotate = self._current_rotation
            except Exception:
                try:
                    self.mpv_player["video-rotate"] = self._current_rotation
                except Exception:
                    pass

    def get_rotation(self) -> int:
        return self._current_rotation

    def _update_rotate_button_ui(self):
        rot = self._current_rotation % 360
        if rot == 0:
            self.btn_rotate.setText("⟳ Xoay: 0°")
        else:
            self.btn_rotate.setText(f"⟳ Xoay: {rot}°")

    def _update_hw_sw_button_ui(self):
        """Cập nhật giao diện nhãn và màu sắc của nút H/W hoặc S/W theo phong cách PotPlayer."""
        if self._decode_mode == "hw":
            self.btn_hw_sw.setText("*H/W")
            self.btn_hw_sw.setStyleSheet(BUTTON_HW_STYLE)
            self.btn_hw_sw.setToolTip("Giải mã phần cứng GPU (*H/W) - Click hoặc nhấn H để chuyển sang CPU (S/W an toàn)")
        else:
            self.btn_hw_sw.setText("S/W")
            self.btn_hw_sw.setStyleSheet(BUTTON_SW_STYLE)
            self.btn_hw_sw.setToolTip("Giải mã phần mềm CPU (S/W) - Click hoặc nhấn H để chuyển sang GPU (*H/W)")

    def get_decode_mode(self) -> str:
        """Trả về chế độ giải mã hiện tại ('hw' hoặc 'sw')."""
        return self._decode_mode

    def is_playing(self) -> bool:
        """Kiểm tra trạng thái đang phát (True) hay tạm dừng/dừng (False)."""
        if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
            return not bool(getattr(self.mpv_player, "pause", True))
        if hasattr(self, "_qt_player") and self._qt_player:
            return self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        return False

    def toggle_hw_sw(self):
        """Chuyển đổi qua lại giữa giải mã phần cứng (*H/W) và giải mã phần mềm (S/W)."""
        if not self._current_file_path:
            return
        new_mode = "sw" if self._decode_mode == "hw" else "hw"
        self.set_decode_mode(new_mode, reload=True, user_action=True)

    def set_decode_mode(self, mode: str, reload: bool = True, user_action: bool = False):
        """Thiết lập chế độ giải mã phần cứng ('hw') hoặc phần mềm ('sw').

        Args:
            mode: 'hw' (GPU) hoặc 'sw' (CPU).
            reload: Nếu True và đang mở video, nạp lại luồng giải mã tại vị trí hiện tại.
            user_action: Nếu True, đánh dấu người dùng chủ động ép chọn chế độ này.
        """
        mode = str(mode or "").strip().lower()
        if mode not in ("hw", "sw"):
            return

        self._decode_mode = mode
        if user_action:
            self._user_forced_decode_mode = mode

        self._update_hw_sw_button_ui()
        self.decode_mode_changed.emit(self._decode_mode)

        # Cấu hình biến môi trường và thiết lập engine phát
        if mode == "sw":
            os.environ["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"] = "none"
            if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
                try:
                    self.mpv_player.hwdec = "no"
                except Exception:
                    try:
                        self.mpv_player["hwdec"] = "no"
                    except Exception:
                        pass
        else:
            os.environ.pop("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", None)
            if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
                try:
                    self.mpv_player.hwdec = "auto-safe"
                except Exception:
                    try:
                        self.mpv_player["hwdec"] = "auto-safe"
                    except Exception:
                        pass

        if reload and self._current_file_path and self._current_file_path.is_file():
            saved_pos = self._current_pos_ms
            is_play = self.is_playing()
            file_str = str(self._current_file_path)

            self._player_failed = False
            if self.is_video_enabled():
                self.viewport_stack.setCurrentIndex(0)

            if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
                try:
                    self.mpv_player.pause = not is_play
                    if hasattr(self.mpv_player, "play"):
                        self.mpv_player.play(file_str)
                    else:
                        self.mpv_player.command("loadfile", file_str, "replace")
                    if saved_pos > 0:
                        self.seek(saved_pos)
                    return
                except Exception as e:
                    print(f"[PlayerWidget] Lỗi nạp lại chế độ {mode} qua mpv: {e}")

            # Dự phòng bằng Qt Multimedia
            if self._qt_player:
                try:
                    self._qt_player.stop()
                    url = QUrl.fromLocalFile(file_str)
                    self._qt_player.setSource(url)
                    if saved_pos > 0:
                        self._qt_player.setPosition(saved_pos)
                    if is_play:
                        self._qt_player.play()
                    else:
                        self._qt_player.pause()
                except Exception as e:
                    print(f"[PlayerWidget] Lỗi nạp lại chế độ {mode} qua Qt: {e}")

    def load_video(self, file_path: str | Path, keyframes: list[float] | None = None, fps: float = 30.0, codec: str = ""):
        """Nạp file video vào media player và hiển thị khung hình đầu tiên."""
        self._current_file_path = Path(file_path).resolve()
        self._current_codec = str(codec or "").strip().lower()
        self._player_failed = False
        self._retried_cpu_decode = False
        self._current_pos_ms = 0
        self._keyframes = sorted(keyframes or [])
        self._fps = fps if (fps and fps > 0) else 30.0
        self.set_video_enabled(True)
        self.btn_snapshot.setEnabled(True)
        self.btn_rotate.setEnabled(True)
        self.btn_hw_sw.setEnabled(True)
        self._pending_first_frame = True

        # Pre-flight Check:
        # 1. Nếu người dùng đã tự tay chuyển chế độ (*H/W hoặc S/W), tôn trọng lựa chọn đó.
        # 2. Nếu là AV1: Kiểm tra an toàn GPU. Nếu GPU không hỗ trợ giải mã phần cứng AV1 chắc chắn 100%
        #    hoặc là laptop Optimus có iGPU Intel cũ -> Fail-Safe MẶC ĐỊNH S/W (CPU libdav1d)
        #    để ngăn chặn triệt để lỗi treo driver màn hình 2 giây (TDR).
        # 3. Với các codec khác (H.264, HEVC, VP9...): Mặc định H/W (GPU) tối ưu hiệu năng.
        if self._user_forced_decode_mode:
            chosen_mode = self._user_forced_decode_mode
        elif self._current_codec in ("av1", "av01"):
            chosen_mode = "hw" if has_hardware_av1_decode() else "sw"
        else:
            chosen_mode = "hw"

        self.set_decode_mode(chosen_mode, reload=False, user_action=False)

        if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
            try:
                file_str = str(self._current_file_path)
                self.mpv_player.pause = True
                if hasattr(self.mpv_player, "play"):
                    self.mpv_player.play(file_str)
                else:
                    self.mpv_player.command("loadfile", file_str, "replace")

                if self._current_speed != 1.0:
                    self.mpv_player.speed = self._current_speed
                if self._current_rotation != 0:
                    try:
                        self.mpv_player.video_rotate = self._current_rotation
                    except Exception:
                        try:
                            self.mpv_player["video-rotate"] = self._current_rotation
                        except Exception:
                            pass
                self.btn_play_pause.setText("▶ Phát")
                return
            except Exception as e:
                print(f"[PlayerWidget] Lỗi nạp video qua mpv ({e}), chuyển sang dự phòng Qt...")
                self._player_failed = True

        # Dự phòng bằng Qt Multimedia
        if self._qt_player:
            url = QUrl.fromLocalFile(str(self._current_file_path))
            self._qt_player.setSource(url)
            self._qt_player.setPosition(0)
            self._qt_player.pause()
        self.btn_play_pause.setText("▶ Phát")

    def clear_video(self):
        """Dừng phát và giải phóng video hiện tại khỏi trình phát."""
        self._pending_first_frame = False
        self._player_failed = False
        self._current_file_path = None
        self._current_pos_ms = 0
        if hasattr(self, "_preview_worker") and self._preview_worker:
            try:
                self._preview_worker.cancel()
            except Exception:
                pass

        if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
            try:
                self.mpv_player.command("stop")
            except Exception:
                pass
        elif hasattr(self, "_qt_player") and self._qt_player:
            self._qt_player.stop()
            self._qt_player.setSource(QUrl())

        self._keyframes = []
        self._in_point_ms = 0
        self._out_point_ms = 0
        self._current_rotation = 0
        self._initial_rotation = 0
        self.btn_play_pause.setText("▶ Phát")
        self.btn_snapshot.setEnabled(False)
        self.btn_rotate.setEnabled(False)
        self.btn_rotate.setText("⟳ Xoay: 0°")
        self.btn_hw_sw.setEnabled(False)
        self.btn_hw_sw.setText("*H/W")
        self.btn_hw_sw.setStyleSheet(BUTTON_HW_STYLE)
        self._decode_mode = "hw"
        self._user_forced_decode_mode = None
        self._current_codec = ""
        os.environ.pop("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", None)
        self.set_video_enabled(True)
        if hasattr(self, "lbl_fallback_preview"):
            self.lbl_fallback_preview.clear()
            self.lbl_fallback_preview.setText("")

    def cleanup(self):
        """Giải phóng tài nguyên trình phát an toàn trước khi đóng ứng dụng."""
        if hasattr(self, "_preview_worker") and self._preview_worker:
            try:
                self._preview_worker.cancel()
            except Exception:
                pass
        if getattr(self, "_engine_type", "qt") == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
            try:
                self.mpv_player.terminate()
                self.mpv_player = None
            except Exception:
                pass
        elif hasattr(self, "_qt_player") and self._qt_player:
            try:
                self._qt_player.stop()
                self._qt_player.setVideoOutput(None)
            except Exception:
                pass

    def set_video_enabled(self, enabled: bool):
        """Bật hoặc tắt hiển thị hình ảnh video khi track Video được bật/tắt."""
        self._video_enabled = enabled
        if enabled:
            if getattr(self, "_player_failed", False):
                self.viewport_stack.setCurrentIndex(2)
            else:
                self.viewport_stack.setCurrentIndex(0)
                if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
                    try:
                        self.mpv_player.vid = "auto"
                    except Exception:
                        pass
                elif hasattr(self, "_qt_player") and self._qt_player:
                    self._qt_player.setVideoOutput(self.video_widget)
            has_media = bool(getattr(self, "_current_file_path", None))
            if hasattr(self, "btn_snapshot"):
                self.btn_snapshot.setEnabled(has_media)
                self.btn_snapshot.setToolTip("Chụp ảnh khung hình hiện tại ở độ phân giải gốc (Phím tắt C)")
            if hasattr(self, "btn_rotate"):
                self.btn_rotate.setEnabled(has_media)
                self.btn_rotate.setToolTip("Xoay hướng hiển thị video theo chiều kim đồng hồ 90° (Áp dụng khi xuất file & chụp ảnh, phím tắt Ctrl+R)")
        else:
            self.viewport_stack.setCurrentIndex(1)
            if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
                try:
                    self.mpv_player.vid = "no"
                except Exception:
                    pass
            elif hasattr(self, "_qt_player") and self._qt_player:
                self._qt_player.setVideoOutput(None)
            if hasattr(self, "btn_snapshot"):
                self.btn_snapshot.setEnabled(False)
                self.btn_snapshot.setToolTip("Không có hình ảnh để chụp (Track video đang bị tắt)")
            if hasattr(self, "btn_rotate"):
                self.btn_rotate.setEnabled(False)
                self.btn_rotate.setToolTip("Không thể xoay khi tắt track video")

    def is_video_enabled(self) -> bool:
        return getattr(self, "_video_enabled", True)

    def update_active_tracks(self, active_stream_indices: list[int], all_tracks: list[dict]):
        """Đồng bộ trạng thái phát video/audio với danh sách track được bật trên timeline."""
        # 1. Kiểm tra track Video
        video_streams = [t for t in all_tracks if t.get("codec_type") == "video"]
        video_enabled = any(t.get("stream_index") in active_stream_indices for t in video_streams) if video_streams else True
        self.set_video_enabled(video_enabled)

        # 2. Kiểm tra các track Audio
        audio_streams = [t for t in all_tracks if t.get("codec_type") == "audio"]
        if audio_streams:
            enabled_audio = [t for t in audio_streams if t.get("stream_index") in active_stream_indices]
            if not enabled_audio:
                if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
                    try:
                        self.mpv_player.aid = "no"
                    except Exception:
                        pass
                elif hasattr(self, "_qt_audio_output") and self._qt_audio_output:
                    self._qt_audio_output.setMuted(True)
            else:
                first_enabled = enabled_audio[0]
                audio_idx = audio_streams.index(first_enabled) + 1  # 1-based index cho mpv
                if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
                    try:
                        self.mpv_player.aid = audio_idx
                    except Exception:
                        pass
                elif hasattr(self, "_qt_audio_output") and self._qt_audio_output and self._qt_player:
                    self._qt_audio_output.setMuted(False)
                    try:
                        self._qt_player.setActiveAudioTrack(audio_idx - 1)
                    except Exception:
                        pass

    def set_active_audio_stream(self, stream_index: int, all_tracks: list[dict]):
        """Chuyển đổi âm thanh phát trước sang track audio được chọn."""
        audio_streams = [t for t in all_tracks if t.get("codec_type") == "audio"]
        if not audio_streams:
            return
        target = next((t for t in audio_streams if t.get("stream_index") == stream_index), None)
        if target:
            audio_idx = audio_streams.index(target) + 1
            if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
                try:
                    self.mpv_player.aid = audio_idx
                except Exception:
                    pass
            elif hasattr(self, "_qt_player") and self._qt_player:
                try:
                    self._qt_player.setActiveAudioTrack(audio_idx - 1)
                except Exception:
                    pass

    def set_cut_range(self, in_sec: float, out_sec: float):
        """Cập nhật giới hạn mốc cắt In/Out cho trình xem trước."""
        self._in_point_ms = int(in_sec * 1000)
        self._out_point_ms = int(out_sec * 1000)

    def set_keyframes(self, keyframes: list[float]):
        """Cập nhật danh sách Keyframe sau khi tiến trình quét ngầm hoàn tất."""
        self._keyframes = sorted(keyframes or [])

    def set_fps(self, fps: float):
        """Cập nhật FPS của video để tua từng khung hình chính xác."""
        if fps and fps > 0:
            self._fps = fps

    def play_pause(self):
        """Chuyển đổi giữa trạng thái phát và tạm dừng."""
        if not self._current_file_path:
            return

        if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
            try:
                dur_sec = getattr(self.mpv_player, "duration", None)
                pos_sec = getattr(self.mpv_player, "time_pos", None)
                if dur_sec and pos_sec and pos_sec >= (dur_sec - 0.1):
                    self.seek(0)
                is_paused = bool(getattr(self.mpv_player, "pause", True))
                self.mpv_player.pause = not is_paused
                self.btn_play_pause.setText("▶ Phát" if not is_paused else "⏸ Tạm dừng")
            except Exception as e:
                print(f"[PlayerWidget] Lỗi play_pause mpv: {e}")
            return

        # Dự phòng bằng Qt Multimedia:
        if not self._qt_player or not self._qt_player.source().isValid():
            return
        if self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._qt_player.pause()
            self.btn_play_pause.setText("▶ Phát")
        else:
            dur_ms = self._qt_player.duration()
            if dur_ms > 0 and self._qt_player.position() >= dur_ms:
                self.seek(0)
            self._qt_player.play()
            self.btn_play_pause.setText("⏸ Tạm dừng")

    def seek(self, position_ms: int):
        """Tua trình phát đến vị trí mili-giây mong muốn."""
        self._current_pos_ms = max(0, position_ms)

        if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
            try:
                target_sec = self._current_pos_ms / 1000.0
                self.mpv_player.command("seek", target_sec, "absolute+exact")
                self.position_changed.emit(self._current_pos_ms)
                return
            except Exception:
                pass

        if hasattr(self, "_qt_player") and self._qt_player:
            self._qt_player.setPosition(self._current_pos_ms)
        if getattr(self, "_player_failed", False):
            self.position_changed.emit(self._current_pos_ms)
            self._request_fallback_preview(self._current_pos_ms)

    def step_frame(self, direction: int):
        """Tua tiến (+1) hoặc lùi (-1) đúng 1 khung hình theo FPS của video."""
        if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
            try:
                if not getattr(self.mpv_player, "pause", True):
                    self.mpv_player.pause = True
                    self.btn_play_pause.setText("▶ Phát")
                if direction > 0:
                    self.mpv_player.command("frame-step")
                else:
                    self.mpv_player.command("frame-back-step")
                return
            except Exception:
                pass

        fps = self._fps if self._fps > 0 else 30.0
        step_ms = 1000.0 / fps
        curr_pos = self._current_pos_ms if getattr(self, "_player_failed", False) else (
            self._qt_player.position() if self._qt_player else self._current_pos_ms
        )
        current_frame = round(curr_pos / step_ms)
        new_frame = max(0, current_frame + direction)
        new_pos = int(round(new_frame * step_ms))
        self.seek(new_pos)

    def step_keyframe(self, direction: int):
        """Nhảy nhanh tới Keyframe (I-frame) phía trước hoặc phía sau."""
        if not self._keyframes:
            if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
                try:
                    if not getattr(self.mpv_player, "pause", True):
                        self.mpv_player.pause = True
                        self.btn_play_pause.setText("▶ Phát")
                    self.mpv_player.command("seek", 5 * direction, "relative+keyframes")
                    return
                except Exception:
                    pass
            self.step_frame(direction * 10)
            return

        curr_pos = self._current_pos_ms
        current_sec = curr_pos / 1000.0
        if direction < 0:
            candidates = [k for k in self._keyframes if k < (current_sec - 0.05)]
            if candidates:
                self.seek(int(max(candidates) * 1000))
            else:
                self.seek(0)
        else:
            candidates = [k for k in self._keyframes if k > (current_sec + 0.05)]
            if candidates:
                self.seek(int(min(candidates) * 1000))

    def _request_fallback_preview(self, pos_ms: int):
        """Trích xuất ảnh xem trước nhanh bằng FFmpeg (CPU libdav1d) khi GPU không giải mã được video."""
        if not getattr(self, "_current_file_path", None) or not self._current_file_path.is_file():
            return

        from src.core.cutter import build_snapshot_command
        from src.core.worker import SnapshotWorker

        if hasattr(self, "_preview_worker") and self._preview_worker and self._preview_worker.isRunning():
            self._preview_worker.cancel()
            self._preview_worker.wait(50)

        preview_dir = get_project_root() / "cache" / "fallback_preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_img = preview_dir / "current_frame.jpg"

        time_sec = pos_ms / 1000.0
        cmd = build_snapshot_command(
            self._current_file_path,
            preview_img,
            time_sec,
            rotation=self._current_rotation,
        )

        self._preview_worker = SnapshotWorker(cmd, preview_img, time_sec, parent=self)

        def on_preview_ready(img_path_str: str, t_sec: float):
            img_p = Path(img_path_str)
            if img_p.is_file() and hasattr(self, "lbl_fallback_preview"):
                pix = QPixmap(str(img_p))
                if not pix.isNull():
                    target_size = self.lbl_fallback_preview.size()
                    if target_size.width() > 50 and target_size.height() > 50:
                        scaled = pix.scaled(
                            target_size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        self.lbl_fallback_preview.setPixmap(scaled)
                    else:
                        self.lbl_fallback_preview.setPixmap(pix)

        self._preview_worker.finished_success.connect(on_preview_ready)
        self._preview_worker.start()

    def _on_volume_changed(self, val: int):
        if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
            try:
                self.mpv_player.volume = val
            except Exception:
                pass
        elif hasattr(self, "_qt_audio_output") and self._qt_audio_output:
            self._qt_audio_output.setVolume(val / 100.0)

    def _on_combo_speed_changed(self, text: str):
        """Xử lý thay đổi tốc độ phát từ combobox."""
        raw = text.rstrip("xX").strip().replace(",", ".")
        try:
            val = float(raw)
            self.set_speed(val)
        except ValueError:
            pass

    def set_speed(self, speed: float):
        """Cài đặt tốc độ phát trong khoảng từ 0.25x đến 2.0x."""
        clamped = max(0.25, min(2.0, round(speed, 2)))
        self._current_speed = clamped
        text = f"{clamped:.2f}x"
        idx = self.combo_speed.findText(text)
        if idx >= 0 and self.combo_speed.currentIndex() != idx:
            self.combo_speed.blockSignals(True)
            self.combo_speed.setCurrentIndex(idx)
            self.combo_speed.blockSignals(False)

        if self._engine_type == "mpv" and hasattr(self, "mpv_player") and self.mpv_player:
            try:
                self.mpv_player.speed = clamped
            except Exception:
                pass
        elif hasattr(self, "_qt_player") and self._qt_player:
            self._qt_player.setPlaybackRate(clamped)

        self.speed_changed.emit(clamped)

    def change_speed(self, delta: float):
        """Tăng hoặc giảm tốc độ theo danh sách cài sẵn [0.25x .. 2.0x]."""
        curr = self._current_speed
        if delta > 0:
            candidates = [s for s in SPEED_PRESETS if s > curr + 0.01]
            target = candidates[0] if candidates else SPEED_PRESETS[-1]
        else:
            candidates = [s for s in SPEED_PRESETS if s < curr - 0.01]
            target = candidates[-1] if candidates else SPEED_PRESETS[0]
        self.set_speed(target)

    def reset_speed(self):
        """Đặt lại tốc độ phát về 1.0x chuẩn."""
        self.set_speed(1.0)

    @property
    def spin_speed(self):
        """Lớp hỗ trợ tương thích ngược cho các nơi truy vấn spin_speed."""
        class _CompatSpeed:
            def __init__(self, parent):
                self._parent = parent
            def value(self):
                return self._parent._current_speed
            def setValue(self, val):
                self._parent.set_speed(float(val))
        return _CompatSpeed(self)

    @property
    def txt_speed(self):
        """Lớp hỗ trợ tương thích ngược cho các nơi truy vấn txt_speed."""
        class _CompatTxt:
            def __init__(self, parent):
                self._parent = parent
            def text(self):
                return self._parent.combo_speed.currentText()
            def setText(self, val):
                self._parent.combo_speed.setCurrentText(str(val))
        return _CompatTxt(self)

    # --- Hỗ trợ Kéo & Thả file (Drag & Drop) ---
    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return True
        elif event.type() == QEvent.Type.Drop:
            if event.mimeData().hasUrls():
                for url in event.mimeData().urls():
                    p_str = url.toLocalFile()
                    if p_str and Path(p_str).is_file():
                        event.acceptProposedAction()
                        self.file_dropped.emit(Path(p_str))
                        return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p_str = url.toLocalFile()
                if p_str and Path(p_str).is_file():
                    event.acceptProposedAction()
                    self.file_dropped.emit(Path(p_str))
                    return
