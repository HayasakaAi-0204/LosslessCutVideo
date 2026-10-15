"""Video player preview widget using PySide6 QMediaPlayer."""

from pathlib import Path
from PySide6.QtCore import Qt, QUrl, Signal, QEvent
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QPalette, QColor
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QLabel,
    QLineEdit,
    QComboBox,
    QStackedWidget,
    QGridLayout,
)

SPEED_PRESETS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]

from src.ui.styles import UNIFIED_BUTTON_STYLE, UNIFIED_ICON_BUTTON_STYLE


class ClickableVideoWidget(QVideoWidget):
    """QVideoWidget subclass that handles play/pause on mouse click and forwards drag-drop."""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class PlayerWidget(QWidget):
    """Video preview container with play/pause, stepping controls, and track preview muting."""

    position_changed = Signal(int)  # ms
    duration_changed = Signal(int)  # ms
    file_dropped = Signal(Path)
    speed_changed = Signal(float)  # playback rate e.g. 0.25 .. 2.0
    snapshot_requested = Signal()
    rotation_changed = Signal(int)

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

        self._setup_player()
        self._setup_ui()

    def _setup_player(self):
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.player.errorOccurred.connect(self._on_player_error)

    def _on_player_error(self, error, error_string):
        import sys
        print(f"[Player Error] {error}: {error_string}", file=sys.stderr)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Video viewport stacked container (styled with solid black background)
        self.viewport_stack = QStackedWidget(self)
        self.viewport_stack.setMinimumSize(480, 270)
        self.viewport_stack.setStyleSheet("background-color: #000000;")

        # Layer 0: Active Video Output (NEVER set stylesheet on QVideoWidget directly to avoid solid color overlay)
        self.video_widget = ClickableVideoWidget(self)
        self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video_widget.clicked.connect(self.play_pause)
        self.player.setVideoOutput(self.video_widget)
        self.viewport_stack.addWidget(self.video_widget)

        # Layer 1: Disabled Video Overlay (Shown when user toggles Video to [Bỏ])
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

        # Mount viewport directly without any obscuring overlay widget
        layout.addWidget(self.viewport_stack, stretch=1)

        # Controls bar
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

        # Playback speed control: [ ➖ ] [ 1.00x ▾ ] [ ➕ ] (0.25x - 2.00x)
        self.lbl_speed = QLabel("Tốc độ:")
        self.lbl_speed.setStyleSheet("color: #ecf0f1; font-weight: bold; font-size: 13px;")

        self.btn_speed_down = QPushButton("➖")
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

        self.btn_speed_up = QPushButton("➕")
        self.btn_speed_up.setToolTip("Tăng tốc độ phát (Phím ])")
        self.btn_speed_up.setFixedSize(28, 28)
        self.btn_speed_up.setStyleSheet(UNIFIED_ICON_BUTTON_STYLE)
        self.btn_speed_up.clicked.connect(lambda: self.change_speed(0.25))

        # Volume control
        self.lbl_vol = QLabel("🔊")
        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(100)
        self.slider_vol.setMaximumWidth(80)
        self.slider_vol.valueChanged.connect(self._on_volume_changed)

        # Snapshot button (Save current frame in 100% native resolution)
        self.btn_snapshot = QPushButton("📸 Chụp Ảnh")
        self.btn_snapshot.setToolTip("Chụp ảnh khung hình hiện tại ở độ phân giải gốc (Phím tắt C)")
        self.btn_snapshot.setEnabled(False)
        self.btn_snapshot.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_snapshot.setFixedHeight(30)
        self.btn_snapshot.clicked.connect(self.snapshot_requested.emit)

        # Rotate button (Lossless metadata orientation cycle: 0 -> 90 -> 180 -> 270)
        self.btn_rotate = QPushButton("⟳ Xoay: 0°")
        self.btn_rotate.setToolTip("Xoay hướng hiển thị video theo chiều kim đồng hồ 90° (Áp dụng khi xuất file & chụp ảnh, phím tắt Ctrl+R)")
        self.btn_rotate.setEnabled(False)
        self.btn_rotate.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_rotate.setFixedHeight(30)
        self.btn_rotate.clicked.connect(self.rotate_90)

        controls_layout.addWidget(self.btn_prev_kf)
        controls_layout.addWidget(self.btn_step_back)
        controls_layout.addWidget(self.btn_play_pause)
        controls_layout.addWidget(self.btn_step_forward)
        controls_layout.addWidget(self.btn_next_kf)
        controls_layout.addSpacing(6)
        controls_layout.addWidget(self.btn_snapshot)
        controls_layout.addWidget(self.btn_rotate)
        controls_layout.addStretch()
        controls_layout.addWidget(self.lbl_speed)
        controls_layout.addWidget(self.btn_speed_down)
        controls_layout.addWidget(self.combo_speed)
        controls_layout.addWidget(self.btn_speed_up)
        controls_layout.addSpacing(10)
        controls_layout.addWidget(self.lbl_vol)
        controls_layout.addWidget(self.slider_vol)

        layout.addLayout(controls_layout)

    def rotate_90(self):
        """Rotate clockwise by 90 degrees."""
        self._current_rotation = (self._current_rotation + 90) % 360
        self._update_rotate_button_ui()
        self.rotation_changed.emit(self._current_rotation)

    def set_initial_rotation(self, rot: int):
        """Set initial rotation probed from file metadata."""
        self._initial_rotation = int(rot) % 360
        self._current_rotation = self._initial_rotation
        self._update_rotate_button_ui()

    def get_rotation(self) -> int:
        return self._current_rotation

    def _update_rotate_button_ui(self):
        rot = self._current_rotation % 360
        if rot == 0:
            self.btn_rotate.setText("⟳ Xoay: 0°")
        else:
            self.btn_rotate.setText(f"⟳ Xoay: {rot}°")

    def load_video(self, file_path: str | Path, keyframes: list[float] | None = None, fps: float = 30.0):
        """Load video into media player and pre-roll first frame."""
        self._keyframes = sorted(keyframes or [])
        self._fps = fps if (fps and fps > 0) else 30.0
        self.set_video_enabled(True)
        self.btn_snapshot.setEnabled(True)
        self.btn_rotate.setEnabled(True)
        self._pending_first_frame = True
        url = QUrl.fromLocalFile(str(Path(file_path).resolve()))
        self.player.setSource(url)
        self.player.setPosition(0)
        self.player.pause()
        self.btn_play_pause.setText("▶ Phát")

    def clear_video(self):
        """Stop playback and clear current video from media player."""
        self._pending_first_frame = False
        self.player.stop()
        self.player.setSource(QUrl())
        self._keyframes = []
        self._in_point_ms = 0
        self._out_point_ms = 0
        self._current_rotation = 0
        self._initial_rotation = 0
        self.btn_play_pause.setText("▶ Phát")
        self.btn_snapshot.setEnabled(False)
        self.btn_rotate.setEnabled(False)
        self.btn_rotate.setText("⟳ Xoay: 0°")
        self.set_video_enabled(True)

    def set_video_enabled(self, enabled: bool):
        """Show or hide video preview when Video track is toggled."""
        self._video_enabled = enabled
        if enabled:
            self.viewport_stack.setCurrentIndex(0)
            self.player.setVideoOutput(self.video_widget)
            has_media = bool(self.player.source() and not self.player.source().isEmpty())
            if hasattr(self, "btn_snapshot"):
                self.btn_snapshot.setEnabled(has_media)
                self.btn_snapshot.setToolTip("Chụp ảnh khung hình hiện tại ở độ phân giải gốc (Phím tắt C)")
            if hasattr(self, "btn_rotate"):
                self.btn_rotate.setEnabled(has_media)
                self.btn_rotate.setToolTip("Xoay hướng hiển thị video theo chiều kim đồng hồ 90° (Áp dụng khi xuất file & chụp ảnh)")
        else:
            self.viewport_stack.setCurrentIndex(1)
            self.player.setVideoOutput(None)
            if hasattr(self, "btn_snapshot"):
                self.btn_snapshot.setEnabled(False)
                self.btn_snapshot.setToolTip("Không có hình ảnh để chụp (Track video đang bị tắt)")
            if hasattr(self, "btn_rotate"):
                self.btn_rotate.setEnabled(False)
                self.btn_rotate.setToolTip("Không thể xoay khi tắt track video")

    def is_video_enabled(self) -> bool:
        return getattr(self, "_video_enabled", True)

    def update_active_tracks(self, active_stream_indices: list[int], all_tracks: list[dict]):
        """Sync player preview with active/disabled tracks from timeline."""
        # 1. Video track check
        video_streams = [t for t in all_tracks if t.get("codec_type") == "video"]
        video_enabled = any(t.get("stream_index") in active_stream_indices for t in video_streams) if video_streams else True
        self.set_video_enabled(video_enabled)

        # 2. Audio tracks check
        audio_streams = [t for t in all_tracks if t.get("codec_type") == "audio"]
        if audio_streams:
            enabled_audio = [t for t in audio_streams if t.get("stream_index") in active_stream_indices]
            if not enabled_audio:
                self.audio_output.setMuted(True)
            else:
                self.audio_output.setMuted(False)
                first_enabled = enabled_audio[0]
                audio_idx = audio_streams.index(first_enabled)
                try:
                    self.player.setActiveAudioTrack(audio_idx)
                except Exception:
                    pass

    def set_active_audio_stream(self, stream_index: int, all_tracks: list[dict]):
        """Switch player preview audio to selected track if it is an audio stream."""
        audio_streams = [t for t in all_tracks if t.get("codec_type") == "audio"]
        if not audio_streams:
            return
        target = next((t for t in audio_streams if t.get("stream_index") == stream_index), None)
        if target:
            audio_idx = audio_streams.index(target)
            try:
                self.player.setActiveAudioTrack(audio_idx)
            except Exception:
                pass

    def set_cut_range(self, in_sec: float, out_sec: float):
        """Set preview boundaries so playback respects In/Out cut points."""
        self._in_point_ms = int(in_sec * 1000)
        self._out_point_ms = int(out_sec * 1000)

    def set_keyframes(self, keyframes: list[float]):
        """Update keyframes list after background scan finishes."""
        self._keyframes = sorted(keyframes or [])

    def set_fps(self, fps: float):
        """Update video fps for frame-stepping."""
        if fps and fps > 0:
            self._fps = fps

    def play_pause(self):
        """Toggle playback state."""
        if not self.player.source().isValid():
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.btn_play_pause.setText("▶ Phát")
        else:
            # If at the very end of the video, restart from beginning
            dur_ms = self.player.duration()
            if dur_ms > 0 and self.player.position() >= dur_ms:
                self.seek(0)
            self.player.play()
            self.btn_play_pause.setText("⏸ Tạm dừng")

    def seek(self, position_ms: int):
        """Seek player to millisecond position."""
        self.player.setPosition(position_ms)

    def step_frame(self, direction: int):
        """Step one frame forward (+1) or backward (-1) precisely matching video fps."""
        fps = self._fps if self._fps > 0 else 30.0
        step_ms = 1000.0 / fps
        curr_pos = self.player.position()
        current_frame = round(curr_pos / step_ms)
        new_frame = max(0, current_frame + direction)
        new_pos = int(round(new_frame * step_ms))
        self.seek(new_pos)

    def step_keyframe(self, direction: int):
        """Jump to the previous or next keyframe."""
        if not self._keyframes:
            self.step_frame(direction * 10)
            return

        current_sec = self.player.position() / 1000.0
        if direction < 0:
            # Previous keyframe
            candidates = [k for k in self._keyframes if k < (current_sec - 0.05)]
            if candidates:
                self.seek(int(max(candidates) * 1000))
            else:
                self.seek(0)
        else:
            # Next keyframe
            candidates = [k for k in self._keyframes if k > (current_sec + 0.05)]
            if candidates:
                self.seek(int(min(candidates) * 1000))

    def _on_position_changed(self, pos_ms: int):
        # Stop at the end of the entire video
        dur_ms = self.player.duration()
        if dur_ms > 0 and pos_ms >= dur_ms:
            self.player.pause()
            self.btn_play_pause.setText("▶ Phát")
        self.position_changed.emit(pos_ms)

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        """Force the player to decode and render the first frame immediately upon load."""
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            if self._pending_first_frame:
                self._pending_first_frame = False
                self.player.setPosition(0)
                self.player.pause()
                self.video_widget.update()
                self.btn_play_pause.setText("▶ Phát")

    def _on_duration_changed(self, dur_ms: int):
        if dur_ms > 0 and self._pending_first_frame:
            self._pending_first_frame = False
            self.player.pause()
            self.player.setPosition(0)
            self.btn_play_pause.setText("▶ Phát")
        self.duration_changed.emit(dur_ms)

    def _on_volume_changed(self, val: int):
        self.audio_output.setVolume(val / 100.0)

    def _on_combo_speed_changed(self, text: str):
        """Handle speed selection from combo box."""
        raw = text.rstrip("xX").strip().replace(",", ".")
        try:
            val = float(raw)
            self.set_speed(val)
        except ValueError:
            pass

    def set_speed(self, speed: float):
        """Set playback speed clamped between 0.25x and 2.0x."""
        clamped = max(0.25, min(2.0, round(speed, 2)))
        self._current_speed = clamped
        text = f"{clamped:.2f}x"
        idx = self.combo_speed.findText(text)
        if idx >= 0 and self.combo_speed.currentIndex() != idx:
            self.combo_speed.blockSignals(True)
            self.combo_speed.setCurrentIndex(idx)
            self.combo_speed.blockSignals(False)
        self.player.setPlaybackRate(clamped)
        self.speed_changed.emit(clamped)

    def change_speed(self, delta: float):
        """Step to next or previous speed preset in [0.25x .. 2.0x]."""
        curr = self._current_speed
        if delta > 0:
            candidates = [s for s in SPEED_PRESETS if s > curr + 0.01]
            target = candidates[0] if candidates else SPEED_PRESETS[-1]
        else:
            candidates = [s for s in SPEED_PRESETS if s < curr - 0.01]
            target = candidates[-1] if candidates else SPEED_PRESETS[0]
        self.set_speed(target)

    def reset_speed(self):
        """Reset speed to 1.0x."""
        self.set_speed(1.0)

    @property
    def spin_speed(self):
        """Backward compatibility helper for any callers querying spin_speed."""
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
        """Backward compatibility helper for any callers querying txt_speed."""
        class _CompatTxt:
            def __init__(self, parent):
                self._parent = parent
            def text(self):
                return self._parent.combo_speed.currentText()
            def setText(self, val):
                self._parent.combo_speed.setCurrentText(str(val))
        return _CompatTxt(self)

    # --- Drag & Drop Support ---
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
