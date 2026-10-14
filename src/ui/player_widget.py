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
    QStackedWidget,
    QGridLayout,
)


class PlayerDropOverlay(QWidget):
    """Transparent overlay directly covering the video viewport.
    
    Guarantees 100% reliable drag & drop on Windows without native HWND interception,
    provides visual drop guidance, and allows clicking on the video to play/pause.
    """

    file_dropped = Signal(Path)

    def __init__(self, player_widget: "PlayerWidget", parent=None):
        super().__init__(parent)
        self.player_widget = player_widget
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setStyleSheet("background-color: transparent;")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_hint = QLabel("📂 Thả video vào đây để mở ngay", self)
        self.lbl_hint.setStyleSheet("""
            QLabel {
                color: #ffffff;
                background-color: rgba(0, 132, 255, 220);
                font-size: 16px;
                font-weight: bold;
                padding: 12px 28px;
                border-radius: 8px;
                border: 2px dashed #ffffff;
            }
        """)
        self.lbl_hint.hide()
        layout.addWidget(self.lbl_hint)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.player_widget.play_pause()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("background-color: rgba(0, 132, 255, 35); border: 2px dashed #0084ff;")
            self.lbl_hint.show()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("background-color: transparent; border: none;")
        self.lbl_hint.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet("background-color: transparent; border: none;")
        self.lbl_hint.hide()
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p_str = url.toLocalFile()
                if p_str and Path(p_str).is_file():
                    event.acceptProposedAction()
                    self.file_dropped.emit(Path(p_str))
                    return
                raw_path = url.path()
                if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
                    raw_path = raw_path[1:]
                if raw_path and Path(raw_path).is_file():
                    event.acceptProposedAction()
                    self.file_dropped.emit(Path(raw_path))
                    return


class PlayerWidget(QWidget):
    """Video preview container with play/pause, stepping controls, and track preview muting."""

    position_changed = Signal(int)  # ms
    duration_changed = Signal(int)  # ms
    file_dropped = Signal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keyframes: list[float] = []
        self._fps: float = 30.0
        self._in_point_ms: int = 0
        self._out_point_ms: int = 0
        self._pending_first_frame: bool = False
        self._current_speed: float = 1.0

        self._setup_player()
        self._setup_ui()

    def _setup_player(self):
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Video viewport stacked container
        self.viewport_stack = QStackedWidget(self)
        self.viewport_stack.setMinimumSize(480, 270)

        # Layer 0: Active Video Output
        self.video_widget = QVideoWidget(self)
        self.video_widget.setStyleSheet("background-color: #1e1e1e;")
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

        # Composite Viewport Container with transparent Drop Overlay on top
        viewport_container = QWidget(self)
        v_layout = QGridLayout(viewport_container)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(0)
        v_layout.addWidget(self.viewport_stack, 0, 0)

        self.drop_overlay = PlayerDropOverlay(self, viewport_container)
        self.drop_overlay.file_dropped.connect(self.file_dropped.emit)
        v_layout.addWidget(self.drop_overlay, 0, 0)
        self.drop_overlay.raise_()

        layout.addWidget(viewport_container, stretch=1)

        # Controls bar
        controls_layout = QHBoxLayout()

        self.btn_prev_kf = QPushButton("⏮ Keyframe Trước")
        self.btn_prev_kf.setToolTip("Nhảy lùi về Keyframe (I-frame) gần nhất")
        self.btn_prev_kf.clicked.connect(lambda: self.step_keyframe(-1))

        self.btn_step_back = QPushButton("◀ 1 Frame")
        self.btn_step_back.setToolTip("Lùi 1 khung hình (~0.033s)")
        self.btn_step_back.clicked.connect(lambda: self.step_frame(-1))

        self.btn_play_pause = QPushButton("▶ Phát")
        self.btn_play_pause.setStyleSheet("font-weight: bold; min-width: 80px;")
        self.btn_play_pause.clicked.connect(self.play_pause)

        self.btn_step_forward = QPushButton("1 Frame ▶")
        self.btn_step_forward.setToolTip("Tiến 1 khung hình (~0.033s)")
        self.btn_step_forward.clicked.connect(lambda: self.step_frame(1))

        self.btn_next_kf = QPushButton("Keyframe Tiếp ⏭")
        self.btn_next_kf.setToolTip("Nhảy tiến tới Keyframe (I-frame) kế tiếp")
        self.btn_next_kf.clicked.connect(lambda: self.step_keyframe(1))

        # Playback speed control: [ ➖ ] [ 1.00x ] [ ➕ ] [ 1x ]
        self.lbl_speed = QLabel("Tốc độ:")
        self.lbl_speed.setStyleSheet("color: #ecf0f1; font-weight: bold; font-size: 13px;")

        self.btn_speed_down = QPushButton("➖")
        self.btn_speed_down.setToolTip("Giảm tốc độ phát (-0.25x hoặc phím [)")
        self.btn_speed_down.setFixedSize(28, 28)
        self.btn_speed_down.setStyleSheet("""
            QPushButton {
                background-color: #2c313c;
                color: #ffffff;
                font-size: 11px;
                border-radius: 4px;
                border: 1px solid #3d4452;
            }
            QPushButton:hover {
                background-color: #3d4452;
                color: #00d2d3;
                border-color: #00d2d3;
            }
        """)
        self.btn_speed_down.clicked.connect(lambda: self.change_speed(-0.25))

        self.txt_speed = QLineEdit("1.00x")
        self.txt_speed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.txt_speed.setToolTip("Nhập tốc độ phát tùy ý (0.10x - 16.00x) hoặc dùng phím [ và ]")
        self.txt_speed.setFixedWidth(76)
        self.txt_speed.setFixedHeight(28)
        self.txt_speed.setStyleSheet("""
            QLineEdit {
                background-color: #22262f;
                color: #00d2d3;
                font-size: 13px;
                font-weight: bold;
                border: 1px solid #3d4452;
                border-radius: 4px;
                padding: 0px;
                selection-background-color: #0084ff;
                selection-color: #ffffff;
            }
            QLineEdit:hover {
                border: 1px solid #00d2d3;
            }
            QLineEdit:focus {
                border: 1px solid #00d2d3;
                background-color: #1a1d24;
            }
        """)
        pal = self.txt_speed.palette()
        pal.setColor(QPalette.ColorRole.Text, QColor("#00d2d3"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#22262f"))
        self.txt_speed.setPalette(pal)
        self.txt_speed.returnPressed.connect(self._on_speed_text_entered)
        self.txt_speed.editingFinished.connect(self._on_speed_text_entered)

        self.btn_speed_up = QPushButton("➕")
        self.btn_speed_up.setToolTip("Tăng tốc độ phát (+0.25x hoặc phím ])")
        self.btn_speed_up.setFixedSize(28, 28)
        self.btn_speed_up.setStyleSheet("""
            QPushButton {
                background-color: #2c313c;
                color: #ffffff;
                font-size: 11px;
                border-radius: 4px;
                border: 1px solid #3d4452;
            }
            QPushButton:hover {
                background-color: #3d4452;
                color: #00d2d3;
                border-color: #00d2d3;
            }
        """)
        self.btn_speed_up.clicked.connect(lambda: self.change_speed(0.25))

        self.btn_reset_speed = QPushButton("1x")
        self.btn_reset_speed.setToolTip("Đặt lại tốc độ về 1.0x (Phím R)")
        self.btn_reset_speed.setFixedSize(36, 28)
        self.btn_reset_speed.setStyleSheet("""
            QPushButton {
                background-color: #2c313c;
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                border-radius: 4px;
                border: 1px solid #3d4452;
            }
            QPushButton:hover {
                background-color: #3d4452;
                color: #00d2d3;
                border: 1px solid #00d2d3;
            }
        """)
        self.btn_reset_speed.clicked.connect(self.reset_speed)

        # Volume control
        self.lbl_vol = QLabel("🔊")
        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(100)
        self.slider_vol.setMaximumWidth(80)
        self.slider_vol.valueChanged.connect(self._on_volume_changed)

        controls_layout.addWidget(self.btn_prev_kf)
        controls_layout.addWidget(self.btn_step_back)
        controls_layout.addWidget(self.btn_play_pause)
        controls_layout.addWidget(self.btn_step_forward)
        controls_layout.addWidget(self.btn_next_kf)
        controls_layout.addStretch()
        controls_layout.addWidget(self.lbl_speed)
        controls_layout.addWidget(self.btn_speed_down)
        controls_layout.addWidget(self.txt_speed)
        controls_layout.addWidget(self.btn_speed_up)
        controls_layout.addWidget(self.btn_reset_speed)
        controls_layout.addSpacing(10)
        controls_layout.addWidget(self.lbl_vol)
        controls_layout.addWidget(self.slider_vol)

        layout.addLayout(controls_layout)

    def load_video(self, file_path: str | Path, keyframes: list[float] | None = None, fps: float = 30.0):
        """Load video into media player and pre-roll first frame."""
        self._keyframes = sorted(keyframes or [])
        self._fps = fps if (fps and fps > 0) else 30.0
        self.set_video_enabled(True)
        self._pending_first_frame = True
        url = QUrl.fromLocalFile(str(Path(file_path).resolve()))
        self.player.setSource(url)
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
        self.btn_play_pause.setText("▶ Phát")
        self.set_video_enabled(True)

    def set_video_enabled(self, enabled: bool):
        """Show or hide video preview when Video track is toggled."""
        if enabled:
            self.viewport_stack.setCurrentIndex(0)
            self.player.setVideoOutput(self.video_widget)
        else:
            self.viewport_stack.setCurrentIndex(1)
            self.player.setVideoOutput(None)
        if hasattr(self, "drop_overlay"):
            self.drop_overlay.raise_()

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
        """Toggle playback state, respecting In/Out bounds."""
        if not self.player.source().isValid() or self.player.duration() <= 0:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.btn_play_pause.setText("▶ Phát")
        else:
            # If at or past out point, restart from in point
            if self._out_point_ms > self._in_point_ms and self.player.position() >= self._out_point_ms:
                self.seek(self._in_point_ms)
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
        # Stop at Out point during preview playback
        if (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            and self._out_point_ms > self._in_point_ms
            and pos_ms >= self._out_point_ms
        ):
            self.player.pause()
            self.seek(self._out_point_ms)
            self.btn_play_pause.setText("▶ Phát")
        self.position_changed.emit(pos_ms)

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        """Force the player to decode and render the first frame immediately upon load."""
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            if self._pending_first_frame:
                self._pending_first_frame = False
                self.player.pause()
                self.player.setPosition(0)
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

    def _on_speed_text_entered(self):
        """Parse text input when user finishes typing a custom playback speed."""
        raw = self.txt_speed.text().strip().rstrip("xX").strip().replace(",", ".")
        try:
            val = float(raw)
            self.set_speed(val)
        except ValueError:
            self.txt_speed.setText(f"{self._current_speed:.2f}x")

    def set_speed(self, speed: float):
        """Set playback speed and update UI label & media player."""
        clamped = max(0.1, min(16.0, round(speed, 2)))
        self._current_speed = clamped
        self.txt_speed.setText(f"{clamped:.2f}x")
        self.player.setPlaybackRate(clamped)

    def change_speed(self, delta: float):
        """Increase or decrease playback speed by delta."""
        self.set_speed(self._current_speed + delta)

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
