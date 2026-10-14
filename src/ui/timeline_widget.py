"""CapCut-style Multi-Track Timeline Widget for Lossless Video Cutter.

Provides visual multi-track lanes (Video with thumbnail filmstrip, Audio streams
with authentic waveforms, Subtitles), time ruler, In/Out range highlighting,
interactive playhead scrubbing, per-track inclusion toggles, and zoom controls.
"""

import bisect
import math
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QSize
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QFont,
    QPainterPath,
    QLinearGradient,
    QCursor,
    QMouseEvent,
    QWheelEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QCheckBox,
    QSlider,
    QScrollArea,
    QFrame,
    QSizePolicy,
)

from src.core.cutter import format_timestamp


# Palette presets for distinct track types
TRACK_PALETTES = [
    # Video palette (Teal / Cyan)
    {"bg_grad1": QColor("#0e6251"), "bg_grad2": QColor("#16a085"), "border": QColor("#1abc9c"), "accent": QColor("#48c9b0")},
    # Audio 1 (CapCut Blue)
    {"bg_grad1": QColor("#1b4f72"), "bg_grad2": QColor("#2874a6"), "border": QColor("#2980b9"), "accent": QColor("#38bdf8")},
    # Audio 2 (Emerald Green)
    {"bg_grad1": QColor("#145a32"), "bg_grad2": QColor("#1e8449"), "border": QColor("#27ae60"), "accent": QColor("#4ade80")},
    # Audio 3 (Purple / Amethyst)
    {"bg_grad1": QColor("#4a235a"), "bg_grad2": QColor("#6c3483"), "border": QColor("#8e44ad"), "accent": QColor("#c084fc")},
    # Audio 4 (Amber / Orange)
    {"bg_grad1": QColor("#7e5109"), "bg_grad2": QColor("#b9770e"), "border": QColor("#d35400"), "accent": QColor("#fb923c")},
]


class TimelineCanvas(QWidget):
    """Custom painted timeline canvas with ruler, video filmstrip, and audio waveforms."""

    seek_requested = Signal(int)  # ms
    in_point_dragged = Signal(float)  # sec
    out_point_dragged = Signal(float)  # sec
    track_clicked = Signal(int)  # stream_index

    RULER_HEIGHT = 28
    LANE_HEIGHT = 44
    LANE_SPACING = 4
    HANDLE_WIDTH = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._duration_sec: float = 0.0
        self._current_pos_sec: float = 0.0
        self._in_point_sec: float = 0.0
        self._out_point_sec: float = 0.0
        self._pixels_per_sec: float = 50.0  # Zoom level
        self._tracks: list[dict[str, Any]] = []
        self._active_stream_indices: set[int] = set()

        # Per-track cut state
        self._track_cut_ranges: dict[int, tuple[float, float]] = {}
        self._selected_stream_index: int | None = None
        self._cut_mode: str = "global"

        # Real preview data
        self._thumbnails: list[dict[str, Any]] = []  # [{"time_sec": float, "pixmap": QPixmap}]
        self._audio_waveforms: dict[int, list[float]] = {}  # {stream_index: [float]}
        self._keyframes: list[float] = []

        # Drag state: None, 'playhead', 'in', 'out'
        self._drag_mode: str | None = None

        self._update_geometry()

    def set_keyframes(self, keyframes: list[float]):
        """Pass keyframes to canvas for visual ticks and snap aids."""
        self._keyframes = list(keyframes)
        self.update()

    def set_track_ranges(self, ranges: dict[int, tuple[float, float]]):
        self._track_cut_ranges = dict(ranges)
        self.update()

    def set_selected_stream(self, stream_index: int | None):
        self._selected_stream_index = stream_index
        self.update()

    def set_cut_mode(self, mode: str):
        self._cut_mode = mode
        self.update()

    def clear_preview_data(self):
        """Clear cached thumbnails, waveforms, and keyframes when loading a completely new file."""
        self._thumbnails = []
        self._audio_waveforms = {}
        self._keyframes = []
        self.update()

    def set_duration(self, duration_sec: float):
        if abs(self._duration_sec - duration_sec) < 0.05 and self._duration_sec > 0:
            return
        self._duration_sec = max(0.0, duration_sec)
        self._in_point_sec = 0.0
        self._out_point_sec = self._duration_sec
        self._update_geometry()
        self.update()

    def set_position(self, pos_sec: float):
        if self._drag_mode is not None:
            # User is actively dragging playhead or in/out markers, do not overwrite with player tick
            return
        self._current_pos_sec = max(0.0, min(self._duration_sec, pos_sec))
        self.update()

    def set_in_point(self, in_sec: float):
        self._in_point_sec = max(0.0, min(in_sec, self._out_point_sec))
        self.update()

    def set_out_point(self, out_sec: float):
        self._out_point_sec = min(self._duration_sec, max(out_sec, self._in_point_sec))
        self.update()

    def set_tracks(self, tracks: list[dict[str, Any]], active_indices: set[int]):
        self._tracks = tracks
        self._active_stream_indices = set(active_indices)
        self._update_geometry()
        self.update()

    def set_active_stream_indices(self, active_indices: set[int]):
        self._active_stream_indices = set(active_indices)
        self.update()

    def set_zoom(self, pps: float):
        self._pixels_per_sec = max(0.05, min(500.0, pps))
        self._update_geometry()
        self.update()

    def set_thumbnails(self, thumbnails_data: list[dict[str, Any]]):
        """Store thumbnails loaded from background worker and cache QPixmaps."""
        self._thumbnails = []
        for item in thumbnails_data:
            p_str = item.get("image_path")
            if p_str and Path(p_str).is_file():
                pix = QPixmap(p_str)
                if not pix.isNull():
                    self._thumbnails.append({
                        "time_sec": item.get("time_sec", 0.0),
                        "pixmap": pix,
                    })
        self.update()

    def set_audio_waveforms(self, waveforms: dict[int, list[float]]):
        """Store extracted real audio waveforms and repaint."""
        self._audio_waveforms.update(waveforms)
        self.update()

    def set_audio_waveform_stream(self, stream_index: int, peaks: list[float]):
        """Store a single stream waveform and repaint immediately."""
        self._audio_waveforms[stream_index] = peaks
        self.update()

    def get_pixels_per_sec(self) -> float:
        return self._pixels_per_sec

    def _update_geometry(self):
        if not self._tracks or self._duration_sec <= 0:
            h = self.RULER_HEIGHT + self.LANE_HEIGHT + 10
            self.setMinimumSize(600, h)
            self.resize(600, h)
            return
        w = int(max(600.0, self._duration_sec * self._pixels_per_sec + 40))
        track_count = max(1, len(self._tracks))
        h = self.RULER_HEIGHT + track_count * (self.LANE_HEIGHT + self.LANE_SPACING) + 10
        self.setMinimumSize(w, h)
        self.resize(w, h)

    def _sec_to_x(self, sec: float) -> float:
        return 10.0 + sec * self._pixels_per_sec

    def _x_to_sec(self, x: float) -> float:
        if self._pixels_per_sec <= 0:
            return 0.0
        sec = (x - 10.0) / self._pixels_per_sec
        return max(0.0, min(self._duration_sec, sec))

    # --- Mouse Events ---
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton or not self._tracks or self._duration_sec <= 0:
            return

        x = event.position().x()
        y = event.position().y()
        click_sec = self._x_to_sec(x)

        in_x = self._sec_to_x(self._in_point_sec)
        out_x = self._sec_to_x(self._out_point_sec)

        # Check if clicking on In marker flag on ruler
        if y <= self.RULER_HEIGHT and abs(x - in_x) <= 8:
            self._drag_mode = "in"
        # Check if clicking on Out marker flag on ruler
        elif y <= self.RULER_HEIGHT and abs(x - out_x) <= 8:
            self._drag_mode = "out"
        else:
            # If clicked on a track lane, select that track
            if y > self.RULER_HEIGHT:
                lane_idx = int((y - self.RULER_HEIGHT) // (self.LANE_HEIGHT + self.LANE_SPACING))
                if 0 <= lane_idx < len(self._tracks):
                    clicked_s_idx = self._tracks[lane_idx].get("stream_index", lane_idx)
                    self.track_clicked.emit(clicked_s_idx)

            self._drag_mode = "playhead"
            self._current_pos_sec = click_sec
            self.seek_requested.emit(int(click_sec * 1000))
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._tracks or self._duration_sec <= 0:
            return

        x = event.position().x()
        cur_sec = self._x_to_sec(x)

        if self._drag_mode == "playhead":
            self._current_pos_sec = cur_sec
            self.seek_requested.emit(int(cur_sec * 1000))
            self.update()
        elif self._drag_mode == "in":
            new_in = min(cur_sec, self._out_point_sec - 0.05)
            self._in_point_sec = max(0.0, new_in)
            self.in_point_dragged.emit(self._in_point_sec)
            self.update()
        elif self._drag_mode == "out":
            new_out = max(cur_sec, self._in_point_sec + 0.05)
            self._out_point_sec = min(self._duration_sec, new_out)
            self.out_point_dragged.emit(self._out_point_sec)
            self.update()
        else:
            # Update cursor shape when hovering ruler markers
            y = event.position().y()
            in_x = self._sec_to_x(self._in_point_sec)
            out_x = self._sec_to_x(self._out_point_sec)
            if y <= self.RULER_HEIGHT and (abs(x - in_x) <= 8 or abs(x - out_x) <= 8):
                self.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_mode = None

    # --- Painting ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        w = self.width()
        h = self.height()

        # 1. Background
        painter.fillRect(0, 0, w, h, QColor("#16181d"))

        # 2. Draw Time Ruler
        self._draw_ruler(painter, w)

        if not self._tracks or self._duration_sec <= 0:
            # Draw subtle placeholder message in track area
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor("#484f58"))
            empty_rect = QRectF(0, self.RULER_HEIGHT, w, h - self.RULER_HEIGHT)
            painter.drawText(empty_rect, Qt.AlignmentFlag.AlignCenter, "Chưa nạp video (Kéo thả video vào bất kỳ đâu hoặc bấm 'Mở Video')")
            return

        # 3. Draw Track Lanes (Video Filmstrip & Audio Waveforms)
        self._draw_tracks(painter, w)

        # 4. Draw Cut Selection Overlay (In -> Out)
        self._draw_cut_overlay(painter, w, h)

        # 5. Draw Playhead Needle
        self._draw_playhead(painter, h)

    def _draw_ruler(self, painter: QPainter, width: int):
        ruler_rect = QRectF(0, 0, width, self.RULER_HEIGHT)
        painter.fillRect(ruler_rect, QColor("#1e222b"))

        # Bottom border of ruler
        painter.setPen(QPen(QColor("#2c313c"), 1))
        painter.drawLine(0, self.RULER_HEIGHT, width, self.RULER_HEIGHT)

        if self._duration_sec <= 0:
            return

        # Adaptive time interval based on zoom
        pps = self._pixels_per_sec
        if pps >= 150:
            step = 0.5
            sub_step = 0.1
        elif pps >= 60:
            step = 1.0
            sub_step = 0.2
        elif pps >= 25:
            step = 5.0
            sub_step = 1.0
        elif pps >= 10:
            step = 10.0
            sub_step = 2.0
        elif pps >= 3:
            step = 30.0
            sub_step = 5.0
        elif pps >= 1.0:
            step = 60.0
            sub_step = 10.0
        elif pps >= 0.3:
            step = 300.0  # 5 minutes
            sub_step = 60.0
        else:
            step = 600.0  # 10 minutes
            sub_step = 120.0

        font = QFont("Segoe UI", 8)
        painter.setFont(font)

        # Culling optimization: Only loop over ticks that fall within the visible [0, width] range
        start_sec = max(0.0, self._x_to_sec(0) - step)
        end_sec = min(self._duration_sec + step, self._x_to_sec(width) + step)

        # Align start_sec to the nearest previous multiple of step
        t = math.floor(start_sec / step) * step
        while t <= end_sec:
            x = self._sec_to_x(t)
            if 0 <= x <= width:
                # Major tick
                painter.setPen(QPen(QColor("#8b949e"), 1))
                painter.drawLine(QPointF(x, self.RULER_HEIGHT - 12), QPointF(x, self.RULER_HEIGHT))

                # Time text
                hrs = int(t // 3600)
                mins = int((t % 3600) // 60)
                secs = int(t % 60)
                millis = int(round((t - int(t)) * 10))

                if step < 1.0:
                    label = f"{mins:02d}:{secs:02d}.{millis}"
                elif hrs > 0:
                    label = f"{hrs:02d}:{mins:02d}:{secs:02d}"
                else:
                    label = f"{mins:02d}:{secs:02d}"

                painter.setPen(QColor("#abb2bf"))
                painter.drawText(QRectF(x - 30, 2, 60, 14), Qt.AlignmentFlag.AlignCenter, label)

                # Sub ticks
                sub_t = t + sub_step
                while sub_t < t + step and sub_t <= self._duration_sec:
                    sx = self._sec_to_x(sub_t)
                    if 0 <= sx <= width:
                        painter.setPen(QPen(QColor("#484f58"), 1))
                        painter.drawLine(QPointF(sx, self.RULER_HEIGHT - 6), QPointF(sx, self.RULER_HEIGHT))
                    sub_t += sub_step

            t += step

        # Subtle emerald green ticks along bottom of ruler for all Keyframes (I-frames)
        if self._keyframes:
            kf_pen = QPen(QColor("#2ecc71"), 1.5)
            painter.setPen(kf_pen)
            for kf in self._keyframes:
                if start_sec <= kf <= end_sec:
                    kx = self._sec_to_x(kf)
                    if 0 <= kx <= width:
                        painter.drawLine(QPointF(kx, self.RULER_HEIGHT - 5), QPointF(kx, self.RULER_HEIGHT))

    def _draw_tracks(self, painter: QPainter, width: int):
        tracks = self._tracks
        if not tracks or self._duration_sec <= 0:
            return

        start_x = self._sec_to_x(0.0)
        end_x = self._sec_to_x(self._duration_sec)
        clip_width = max(10.0, end_x - start_x)

        audio_counter = 0

        for i, trk in enumerate(tracks):
            lane_y = self.RULER_HEIGHT + self.LANE_SPACING + i * (self.LANE_HEIGHT + self.LANE_SPACING)
            lane_rect = QRectF(start_x, lane_y, clip_width, self.LANE_HEIGHT)

            s_idx = trk.get("stream_index", i)
            is_active = (s_idx in self._active_stream_indices) or (not self._active_stream_indices)
            c_type = trk.get("codec_type", "video")

            # Determine color palette
            if c_type == "video":
                palette = TRACK_PALETTES[0]
            elif c_type == "audio":
                audio_counter += 1
                p_idx = 1 + ((audio_counter - 1) % (len(TRACK_PALETTES) - 1))
                palette = TRACK_PALETTES[p_idx]
            else:
                palette = TRACK_PALETTES[4]

            # Lane background slot
            painter.fillRect(QRectF(0, lane_y, width, self.LANE_HEIGHT), QColor("#1c1f26"))

            # Clip Block
            painter.save()
            if not is_active:
                painter.setOpacity(0.3)

            # Gradient base for clip
            grad = QLinearGradient(lane_rect.topLeft(), lane_rect.bottomLeft())
            grad.setColorAt(0.0, palette["bg_grad1"])
            grad.setColorAt(1.0, palette["bg_grad2"])
            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(palette["border"], 1.5))
            painter.drawRoundedRect(lane_rect, 4.0, 4.0)

            # 1. Video Lane: Render Real Filmstrip Frames
            if c_type == "video":
                if self._thumbnails:
                    self._draw_video_filmstrip(painter, lane_rect)
                else:
                    self._draw_filmstrip_perforations(painter, lane_rect)

            # 2. Audio Lane: Render Real Audio Waveform
            elif c_type == "audio":
                self._draw_real_audio_wave(painter, lane_rect, palette["accent"], s_idx)

            # Clip Title Badge (CapCut style top-left pill)
            label_text = f"{trk.get('icon', '🎬')} {trk.get('type_label', 'Track')} : {trk.get('codec_name', '').upper()} {trk.get('details', '')}"
            if trk.get("title"):
                label_text += f" ({trk.get('title')})"
            if not is_active:
                label_text += " [ĐÃ BỎ QUA - KHÔNG XUẤT]"

            # Semi-transparent label badge on top-left of clip
            font = QFont("Segoe UI", 8, QFont.Weight.Bold)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            text_w = metrics.horizontalAdvance(label_text) + 14
            badge_w = min(text_w, lane_rect.width() - 8)
            badge_rect = QRectF(lane_rect.left() + 4, lane_rect.top() + 3, badge_w, 16)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0, 160)))
            painter.drawRoundedRect(badge_rect, 3.0, 3.0)

            painter.setPen(QColor("#ffffff"))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label_text)

            painter.restore()

    def _draw_video_filmstrip(self, painter: QPainter, rect: QRectF):
        """Draw real video thumbnail frames as a continuous filmstrip with preserved aspect ratio."""
        if not self._thumbnails:
            return

        painter.save()
        painter.setClipRect(rect)

        # 1. Determine natural frame aspect ratio from loaded thumbnails
        first_pix = self._thumbnails[0].get("pixmap")
        aspect_ratio = 16.0 / 9.0
        if first_pix and not first_pix.isNull() and first_pix.height() > 0:
            aspect_ratio = first_pix.width() / first_pix.height()

        h = max(10.0, rect.height() - 2.0)
        frame_w = max(35.0, min(140.0, h * aspect_ratio))

        times = [item["time_sec"] for item in self._thumbnails]
        count = len(times)

        # 2. Tile frames across the entire clip range
        tile_x = rect.left()
        clip_right = rect.right()

        while tile_x < clip_right:
            center_x = tile_x + frame_w / 2.0
            t_center = self._x_to_sec(center_x)

            # Find closest thumbnail timestamp via binary search
            pos = bisect.bisect_left(times, t_center)
            if pos == 0:
                best_idx = 0
            elif pos >= count:
                best_idx = count - 1
            else:
                best_idx = pos if (times[pos] - t_center) < (t_center - times[pos - 1]) else pos - 1

            pix = self._thumbnails[best_idx].get("pixmap")
            if pix and not pix.isNull():
                frame_rect = QRectF(tile_x, rect.top() + 1.0, frame_w, h)
                painter.drawPixmap(frame_rect.toRect(), pix)

            # Thin divider line between adjacent filmstrip frames
            painter.setPen(QPen(QColor(0, 0, 0, 160), 1.0))
            painter.drawLine(QPointF(tile_x + frame_w, rect.top()), QPointF(tile_x + frame_w, rect.bottom()))

            tile_x += frame_w

        # Subtle top & bottom filmstrip borders
        painter.setPen(QPen(QColor(0, 0, 0, 100), 1.0))
        painter.drawLine(rect.topLeft(), rect.topRight())
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())

        painter.restore()

    def _draw_real_audio_wave(self, painter: QPainter, rect: QRectF, color: QColor, stream_index: int):
        """Draw real extracted audio waveform peaks across the audio lane."""
        peaks = self._audio_waveforms.get(stream_index)
        if not peaks:
            # Fallback to matching by audio track index if stream keys differ
            keys = sorted(list(self._audio_waveforms.keys()))
            if keys and stream_index in range(len(keys)):
                peaks = self._audio_waveforms.get(keys[stream_index])
            elif keys:
                peaks = self._audio_waveforms.get(keys[0])

        if not peaks:
            self._draw_fallback_audio_wave(painter, rect, color, stream_index)
            return

        painter.save()
        painter.setClipRect(rect)

        mid_y = rect.center().y()

        # 1. Subtle, clean centerline guide for silence regions
        guide_pen = QPen(QColor(color.red(), color.green(), color.blue(), 55), 1.0)
        painter.setPen(guide_pen)
        painter.drawLine(QPointF(rect.left() + 4, mid_y), QPointF(rect.right() - 4, mid_y))

        # 2. CapCut style crisp vertical waveform bars with rounded caps
        bar_pen = QPen(color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(bar_pen)

        max_h = (rect.height() - 6) / 2.0
        step = 3.0  # 3 pixels per bar

        total_samples = len(peaks)
        pps = self._pixels_per_sec
        SAMPLES_PER_SEC = 200.0

        x = rect.left() + 4.0
        while x < rect.right() - 4.0:
            t = self._x_to_sec(x)
            dt = step / pps if pps > 0 else 0.015

            start_idx = int(t * SAMPLES_PER_SEC)
            end_idx = int((t + dt) * SAMPLES_PER_SEC) + 1

            start_idx = max(0, min(total_samples - 1, start_idx))
            end_idx = max(start_idx + 1, min(total_samples, end_idx))

            # Peak amplitude in this time window
            amp = max(peaks[start_idx:end_idx]) if end_idx > start_idx else peaks[start_idx]

            # High-contrast threshold: If silence, keep clean baseline; if audible click, draw tall spike
            if amp >= 0.025:
                bar_h = max(2.5, amp * max_h)
                painter.drawLine(QPointF(x, mid_y - bar_h), QPointF(x, mid_y + bar_h))

            x += step

        painter.restore()

    def _draw_fallback_audio_wave(self, painter: QPainter, rect: QRectF, color: QColor, seed: int):
        """Clean baseline while background real audio waveform is loading."""
        painter.save()
        painter.setClipRect(rect)
        painter.setPen(QPen(color, 1.2))
        mid_y = rect.center().y()
        painter.drawLine(QPointF(rect.left() + 6, mid_y), QPointF(rect.right() - 6, mid_y))
        painter.restore()

    def _draw_filmstrip_perforations(self, painter: QPainter, rect: QRectF):
        """Draw subtle filmstrip perforation notches for video clip."""
        painter.save()
        painter.setClipRect(rect)
        painter.setBrush(QBrush(QColor(0, 0, 0, 70)))
        painter.setPen(Qt.PenStyle.NoPen)

        x = rect.left() + 8.0
        while x < rect.right() - 8.0:
            painter.drawRoundedRect(QRectF(x, rect.top() + 3, 6, 4), 1.0, 1.0)
            painter.drawRoundedRect(QRectF(x, rect.bottom() - 7, 6, 4), 1.0, 1.0)
            x += 16.0

        painter.restore()

    def _draw_cut_overlay(self, painter: QPainter, width: int, height: int):
        """Shade the excluded regions per track lane and on the ruler, and draw In/Out markers."""
        if self._duration_sec <= 0:
            return

        dim_brush = QBrush(QColor(10, 12, 16, 185))

        # 1. Dim excluded regions per track lane
        for i, trk in enumerate(self._tracks):
            s_idx = trk.get("stream_index", i)
            trk_in, trk_out = self._track_cut_ranges.get(s_idx, (self._in_point_sec, self._out_point_sec))
            in_x = self._sec_to_x(trk_in)
            out_x = self._sec_to_x(trk_out)
            lane_y = self.RULER_HEIGHT + self.LANE_SPACING + i * (self.LANE_HEIGHT + self.LANE_SPACING)

            # Dim before In of this track
            if in_x > 0:
                painter.fillRect(QRectF(0, lane_y, in_x, self.LANE_HEIGHT), dim_brush)
            # Dim after Out of this track
            if out_x < width:
                painter.fillRect(QRectF(out_x, lane_y, width - out_x, self.LANE_HEIGHT), dim_brush)

            # Selected track active region highlight (glowing cyan border)
            if s_idx == self._selected_stream_index:
                painter.save()
                painter.setPen(QPen(QColor("#00d2d3"), 2.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                active_w = max(4.0, out_x - in_x)
                painter.drawRoundedRect(QRectF(in_x, lane_y, active_w, self.LANE_HEIGHT), 2, 2)
                painter.restore()

        # 2. Dim excluded regions on Ruler
        cur_in_x = self._sec_to_x(self._in_point_sec)
        cur_out_x = self._sec_to_x(self._out_point_sec)
        if cur_in_x > 0:
            painter.fillRect(QRectF(0, 0, cur_in_x, self.RULER_HEIGHT), QBrush(QColor(10, 12, 16, 150)))
        if cur_out_x < width:
            painter.fillRect(QRectF(cur_out_x, 0, width - cur_out_x, self.RULER_HEIGHT), QBrush(QColor(10, 12, 16, 150)))

        # 3. Vertical guidelines and Flags on Ruler
        painter.setPen(QPen(QColor("#2ecc71"), 1.8, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(cur_in_x, self.RULER_HEIGHT), QPointF(cur_in_x, height))

        # In Flag Handle on ruler
        in_flag = QPainterPath()
        in_flag.moveTo(cur_in_x, 0)
        in_flag.lineTo(cur_in_x + self.HANDLE_WIDTH, 0)
        in_flag.lineTo(cur_in_x + self.HANDLE_WIDTH, self.RULER_HEIGHT - 6)
        in_flag.lineTo(cur_in_x, self.RULER_HEIGHT)
        in_flag.closeSubpath()
        painter.fillPath(in_flag, QBrush(QColor("#2ecc71")))
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        painter.drawText(QRectF(cur_in_x + 1, 3, self.HANDLE_WIDTH - 1, 14), Qt.AlignmentFlag.AlignCenter, "I")

        # 4. Out Point Marker (Red)
        painter.setPen(QPen(QColor("#e74c3c"), 2.0, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(cur_out_x, self.RULER_HEIGHT), QPointF(cur_out_x, height))

        # Out Flag Handle on ruler
        out_flag = QPainterPath()
        out_flag.moveTo(cur_out_x, 0)
        out_flag.lineTo(cur_out_x - self.HANDLE_WIDTH, 0)
        out_flag.lineTo(cur_out_x - self.HANDLE_WIDTH, self.RULER_HEIGHT - 6)
        out_flag.lineTo(cur_out_x, self.RULER_HEIGHT)
        out_flag.closeSubpath()
        painter.fillPath(out_flag, QBrush(QColor("#e74c3c")))
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        painter.drawText(QRectF(cur_out_x - self.HANDLE_WIDTH + 1, 3, self.HANDLE_WIDTH - 1, 14), Qt.AlignmentFlag.AlignCenter, "O")

    def _draw_playhead(self, painter: QPainter, height: int):
        """Draw white playhead needle spanning across ruler and tracks."""
        play_x = self._sec_to_x(self._current_pos_sec)

        # Needle vertical line
        painter.setPen(QPen(QColor("#ffffff"), 2.0))
        painter.drawLine(QPointF(play_x, self.RULER_HEIGHT), QPointF(play_x, height))

        # Playhead Head on ruler
        head_path = QPainterPath()
        head_path.moveTo(play_x - 6, 0)
        head_path.lineTo(play_x + 6, 0)
        head_path.lineTo(play_x + 6, self.RULER_HEIGHT - 8)
        head_path.lineTo(play_x, self.RULER_HEIGHT)
        head_path.lineTo(play_x - 6, self.RULER_HEIGHT - 8)
        head_path.closeSubpath()

        painter.fillPath(head_path, QBrush(QColor("#ffffff")))
        painter.setPen(QPen(QColor("#00d2d3"), 1.0))
        painter.drawPath(head_path)


class TrackHeadersWidget(QWidget):
    """Left sidebar displaying track headers with enable/disable switches."""

    track_toggle_clicked = Signal(int, bool)  # stream_index, is_enabled
    track_selected = Signal(int)  # stream_index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setStyleSheet("background-color: #1a1d24; border-right: 1px solid #2c313c;")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 0, 4, 4)
        self._layout.setSpacing(4)

        # Top Header matching Ruler Height
        self._top_header = QWidget()
        self._top_header.setFixedHeight(TimelineCanvas.RULER_HEIGHT)
        top_h_layout = QHBoxLayout(self._top_header)
        top_h_layout.setContentsMargins(6, 0, 6, 0)
        self.lbl_title = QLabel("TRACKS")
        self.lbl_title.setStyleSheet("color: #8b949e; font-size: 11px; font-weight: bold;")
        top_h_layout.addWidget(self.lbl_title)
        self._layout.addWidget(self._top_header)

        self._items_layout = QVBoxLayout()
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(TimelineCanvas.LANE_SPACING)
        self._layout.addLayout(self._items_layout)
        self._layout.addStretch()

        self._track_buttons: dict[int, QPushButton] = {}
        self._cards: dict[int, QFrame] = {}
        self._selected_stream_index: int | None = None

    def set_tracks(self, tracks: list[dict[str, Any]], active_indices: set[int]):
        # Clear existing
        while self._items_layout.count():
            item = self._items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._track_buttons.clear()
        self._cards.clear()

        if len(tracks) > 0:
            self.lbl_title.setText(f"TRACKS ({len(tracks)})")
        else:
            self.lbl_title.setText("TRACKS")

        for trk in tracks:
            s_idx = trk.get("stream_index", 0)
            is_active = (s_idx in active_indices)

            card = QFrame()
            card.setFixedHeight(TimelineCanvas.LANE_HEIGHT)
            card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._cards[s_idx] = card
            self._update_card_style(card, s_idx == self._selected_stream_index)

            # Card click handler
            def _make_click_handler(idx):
                return lambda event: self._on_card_clicked(idx, event)
            card.mousePressEvent = _make_click_handler(s_idx)

            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(6, 2, 6, 2)
            card_layout.setSpacing(6)

            # Info text
            info_layout = QVBoxLayout()
            info_layout.setSpacing(1)

            lbl_name = QLabel(f"{trk.get('icon', '')} {trk.get('type_label', '')}")
            lbl_name.setStyleSheet("color: #ecf0f1; font-weight: bold; font-size: 11px;")

            meta_text = f"{trk.get('codec_name', '').upper()}"
            if trk.get("title"):
                meta_text += f" • {trk.get('title')}"
            lbl_meta = QLabel(meta_text)
            lbl_meta.setStyleSheet("color: #95a5a6; font-size: 10px;")

            info_layout.addWidget(lbl_name)
            info_layout.addWidget(lbl_meta)
            card_layout.addLayout(info_layout, stretch=1)

            # Toggle button
            btn_toggle = QPushButton("✓ Giữ" if is_active else "✕ Bỏ")
            btn_toggle.setCheckable(True)
            btn_toggle.setChecked(is_active)
            btn_toggle.setFixedWidth(54)
            btn_toggle.setFixedHeight(24)
            self._update_btn_style(btn_toggle, is_active)

            btn_toggle.toggled.connect(lambda chk, idx=s_idx, btn=btn_toggle: self._on_toggle(idx, chk, btn))
            card_layout.addWidget(btn_toggle)
            self._track_buttons[s_idx] = btn_toggle

            self._items_layout.addWidget(card)

    def _on_card_clicked(self, stream_index: int, event):
        self.set_selected_stream(stream_index)
        self.track_selected.emit(stream_index)
        event.accept()

    def set_selected_stream(self, stream_index: int | None):
        self._selected_stream_index = stream_index
        for s_idx, card in self._cards.items():
            self._update_card_style(card, s_idx == stream_index)

    def _update_card_style(self, card: QFrame, is_selected: bool):
        if is_selected:
            card.setStyleSheet(
                "QFrame { background-color: #272c37; border-radius: 4px; border: 2px solid #00d2d3; }"
            )
        else:
            card.setStyleSheet(
                "QFrame { background-color: #22262f; border-radius: 4px; border: 1px solid #2e3440; }"
            )

    def _on_toggle(self, stream_index: int, checked: bool, btn: QPushButton):
        btn.setText("✓ Giữ" if checked else "✕ Bỏ")
        self._update_btn_style(btn, checked)
        self.track_toggle_clicked.emit(stream_index, checked)

    def _update_btn_style(self, btn: QPushButton, is_active: bool):
        if is_active:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60;
                    color: white;
                    font-weight: bold;
                    font-size: 10px;
                    border-radius: 3px;
                    border: none;
                }
                QPushButton:hover { background-color: #2ecc71; }
            """)
        else:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #4a5568;
                    color: #a0aec0;
                    font-size: 10px;
                    border-radius: 3px;
                    border: none;
                }
                QPushButton:hover { background-color: #718096; color: white; }
            """)


class TimelineWidget(QWidget):
    """Full CapCut-style Multi-Track Timeline widget."""

    seek_requested = Signal(int)  # ms
    in_point_changed = Signal(float)  # sec
    out_point_changed = Signal(float)  # sec
    snap_toggled = Signal(bool)
    tracks_changed = Signal(list)  # list of active stream indices

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration_sec: float = 0.0
        self._current_pos_sec: float = 0.0
        self._in_point_sec: float = 0.0
        self._out_point_sec: float = 0.0
        self._tracks: list[dict[str, Any]] = []
        self._active_stream_indices: set[int] = set()

        # Per-track cut state
        self._cut_mode: str = "global"  # "global" or "per_track"
        self._selected_stream_index: int | None = None
        self._track_cut_ranges: dict[int, tuple[float, float]] = {}
        self._keyframes: list[float] = []

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(2)

        # 1. Top Controls Bar
        ctrl_bar = QWidget()
        ctrl_bar.setStyleSheet("background-color: #1e222b; border-bottom: 1px solid #2c313c;")
        ctrl_layout = QHBoxLayout(ctrl_bar)
        ctrl_layout.setContentsMargins(8, 4, 8, 4)
        ctrl_layout.setSpacing(10)

        # Current Playhead Time Display
        self.lbl_time_display = QLabel("00:00:00.000 / 00:00:00.000")
        self.lbl_time_display.setStyleSheet(
            "font-family: monospace; font-size: 13px; font-weight: bold; color: #00d2d3;"
        )
        ctrl_layout.addWidget(self.lbl_time_display)

        ctrl_layout.addSpacing(10)

        # In Point Button & Display
        self.btn_set_in = QPushButton("📍 Đặt In [I]")
        self.btn_set_in.setStyleSheet("font-weight: bold; padding: 4px 10px; background-color: #22262f;")
        self.btn_set_in.clicked.connect(self._set_in_current)
        self.lbl_in_val = QLabel("In: 00:00:00.000")
        self.lbl_in_val.setStyleSheet("font-family: monospace; font-weight: bold; color: #2ecc71;")

        # Out Point Button & Display
        self.btn_set_out = QPushButton("🏁 Đặt Out [O]")
        self.btn_set_out.setStyleSheet("font-weight: bold; padding: 4px 10px; background-color: #22262f;")
        self.btn_set_out.clicked.connect(self._set_out_current)
        self.lbl_out_val = QLabel("Out: 00:00:00.000")
        self.lbl_out_val.setStyleSheet("font-family: monospace; font-weight: bold; color: #e74c3c;")

        # Cut Duration
        self.lbl_cut_dur = QLabel("Thời lượng cắt: 00:00:00.000")
        self.lbl_cut_dur.setStyleSheet("font-family: monospace; font-weight: bold; color: #f1c40f;")

        ctrl_layout.addWidget(self.btn_set_in)
        ctrl_layout.addWidget(self.lbl_in_val)
        ctrl_layout.addSpacing(5)
        ctrl_layout.addWidget(self.btn_set_out)
        ctrl_layout.addWidget(self.lbl_out_val)
        ctrl_layout.addSpacing(5)
        ctrl_layout.addWidget(self.lbl_cut_dur)

        # Mode Toggle & Active Track
        self.btn_cut_mode = QPushButton("🔗 Cắt đồng bộ")
        self.btn_cut_mode.setCheckable(True)
        self.btn_cut_mode.setChecked(False)
        self.btn_cut_mode.setToolTip("Chuyển đổi giữa 'Cắt đồng bộ tất cả track' và 'Cắt độc lập từng track'")
        self.btn_cut_mode.setStyleSheet("""
            QPushButton {
                background-color: #2c313c;
                color: #ffffff;
                font-weight: bold;
                font-size: 11px;
                padding: 4px 10px;
                border-radius: 4px;
                border: 1px solid #3d4452;
            }
            QPushButton:hover {
                background-color: #3d4452;
                border-color: #00d2d3;
            }
            QPushButton:checked {
                background-color: #0084ff;
                color: #ffffff;
                border-color: #00a8ff;
            }
        """)
        self.btn_cut_mode.toggled.connect(self._on_cut_mode_toggled)

        self.lbl_active_track = QLabel("Track: Tất cả")
        self.lbl_active_track.setStyleSheet("color: #00d2d3; font-weight: bold; font-size: 11px; margin-left: 2px;")

        ctrl_layout.addSpacing(8)
        ctrl_layout.addWidget(self.btn_cut_mode)
        ctrl_layout.addWidget(self.lbl_active_track)

        ctrl_layout.addSpacing(15)

        # Snap Checkbox (Enabled by default)
        self.chk_snap = QCheckBox("🧲 Bám Keyframe (Khuyên dùng)")
        self.chk_snap.setChecked(True)
        self.chk_snap.setStyleSheet("font-weight: bold; color: #2ecc71;")
        self.chk_snap.setToolTip("Tự động bám dính vào mốc Keyframe gần nhất để video 100% nguyên bản, không giật lag giây đầu.")
        self.chk_snap.toggled.connect(self.snap_toggled.emit)
        ctrl_layout.addWidget(self.chk_snap)

        ctrl_layout.addStretch()

        # Zoom Controls
        self.btn_zoom_out = QPushButton("➖")
        self.btn_zoom_out.setFixedSize(26, 24)
        self.btn_zoom_out.clicked.connect(lambda: self._adjust_zoom(-0.25))

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(1, 200)
        self.zoom_slider.setValue(40)
        self.zoom_slider.setFixedWidth(90)
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider_changed)

        self.btn_zoom_in = QPushButton("➕")
        self.btn_zoom_in.setFixedSize(26, 24)
        self.btn_zoom_in.clicked.connect(lambda: self._adjust_zoom(0.25))

        self.btn_zoom_fit = QPushButton("Thu vừa")
        self.btn_zoom_fit.setFixedHeight(24)
        self.btn_zoom_fit.clicked.connect(self.fit_to_width)

        ctrl_layout.addWidget(self.btn_zoom_out)
        ctrl_layout.addWidget(self.zoom_slider)
        ctrl_layout.addWidget(self.btn_zoom_in)
        ctrl_layout.addWidget(self.btn_zoom_fit)

        main_layout.addWidget(ctrl_bar)

        # 2. Tracks View (Left Headers + Right Canvas)
        tracks_container = QWidget()
        tracks_layout = QHBoxLayout(tracks_container)
        tracks_layout.setContentsMargins(0, 0, 0, 0)
        tracks_layout.setSpacing(0)

        # Left Headers
        self.headers_widget = TrackHeadersWidget()
        self.headers_widget.track_toggle_clicked.connect(self._on_track_toggled)
        tracks_layout.addWidget(self.headers_widget)

        # Right Canvas inside ScrollArea
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background-color: #16181d; }")

        self.canvas = TimelineCanvas()
        self.canvas.seek_requested.connect(self._on_seek_requested)
        self.canvas.in_point_dragged.connect(self._on_in_dragged)
        self.canvas.out_point_dragged.connect(self._on_out_dragged)

        self.scroll_area.setWidget(self.canvas)
        tracks_layout.addWidget(self.scroll_area, stretch=1)

        # Wire Track Selection
        self.headers_widget.track_selected.connect(self.select_track)
        self.canvas.track_clicked.connect(self.select_track)

        main_layout.addWidget(tracks_container)

    # --- Public API for Player & Window ---
    def select_track(self, stream_index: int):
        """Set the active track for editing in per_track mode."""
        self._selected_stream_index = stream_index
        self.headers_widget.set_selected_stream(stream_index)
        self.canvas.set_selected_stream(stream_index)
        if self._cut_mode == "per_track" and stream_index in self._track_cut_ranges:
            trk_in, trk_out = self._track_cut_ranges[stream_index]
            self.canvas.set_in_point(trk_in)
            self.canvas.set_out_point(trk_out)
        else:
            self.canvas.set_in_point(self._in_point_sec)
            self.canvas.set_out_point(self._out_point_sec)
        self._update_time_labels()

    def _on_cut_mode_toggled(self, checked: bool):
        """Toggle between Global Cut and Per-Track Cut modes."""
        if checked:
            self._cut_mode = "per_track"
            self.btn_cut_mode.setText("🎯 Cắt từng track")
            target = self._selected_stream_index if self._selected_stream_index is not None else self._get_master_video_stream_index()
            self.select_track(target)
        else:
            self._cut_mode = "global"
            self.btn_cut_mode.setText("🔗 Cắt đồng bộ")
            # When switching back to global: synchronize all tracks to master [in_point_sec, out_point_sec]
            for s_idx in self._track_cut_ranges:
                self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
            self.canvas.set_track_ranges(self._track_cut_ranges)
            self.canvas.set_in_point(self._in_point_sec)
            self.canvas.set_out_point(self._out_point_sec)

        self.canvas.set_cut_mode(self._cut_mode)
        self._update_time_labels()

    def _get_master_video_stream_index(self) -> int:
        for trk in self._tracks:
            if trk.get("codec_type") == "video":
                return trk.get("stream_index", 0)
        return self._tracks[0].get("stream_index", 0) if self._tracks else 0

    def _enforce_master_child_constraints(self, changed_s_idx: int):
        """Ensure Master-Child constraint: In_video <= In_audio < Out_audio <= Out_video."""
        video_idx = self._get_master_video_stream_index()
        if video_idx not in self._track_cut_ranges:
            return
        vid_in, vid_out = self._track_cut_ranges[video_idx]

        if changed_s_idx == video_idx:
            # Video changed: auto-pull child audio tracks so they remain within [vid_in, vid_out]
            for s_idx, (a_in, a_out) in list(self._track_cut_ranges.items()):
                if s_idx == video_idx:
                    continue
                new_in = max(vid_in, min(a_in, vid_out - 0.05))
                new_out = min(vid_out, max(a_out, new_in + 0.05))
                self._track_cut_ranges[s_idx] = (new_in, new_out)
        else:
            # Audio track changed: clamp strictly inside [vid_in, vid_out]
            a_in, a_out = self._track_cut_ranges.get(changed_s_idx, (vid_in, vid_out))
            new_in = max(vid_in, min(a_in, a_out - 0.05))
            new_out = min(vid_out, max(a_out, new_in + 0.05))
            self._track_cut_ranges[changed_s_idx] = (new_in, new_out)

    def get_track_ranges(self) -> dict[int, tuple[float, float]]:
        """Return mapping of stream_index -> (in_sec, out_sec)."""
        return dict(self._track_cut_ranges)

    def get_cut_mode(self) -> str:
        """Return current cut mode ('global' | 'per_track')."""
        return self._cut_mode

    def clear_preview_data(self):
        """Clear cached thumbnails and waveforms when loading a completely new file."""
        self.canvas.clear_preview_data()

    def clear_timeline(self):
        """Reset timeline and all tracks back to empty initial state."""
        self._duration_sec = 0.0
        self._current_pos_sec = 0.0
        self._in_point_sec = 0.0
        self._out_point_sec = 0.0
        self._tracks = []
        self._active_stream_indices = set()
        self._track_cut_ranges = {}
        self._selected_stream_index = None

        self._cut_mode = "global"
        self.btn_cut_mode.blockSignals(True)
        self.btn_cut_mode.setChecked(False)
        self.btn_cut_mode.setText("🔗 Cắt đồng bộ")
        self.btn_cut_mode.blockSignals(False)

        self._keyframes = []
        self.canvas.clear_preview_data()
        self.canvas.set_cut_mode("global")
        self.canvas.set_selected_stream(None)
        self.canvas.set_track_ranges({})
        self.canvas.set_tracks([], set())
        self.canvas.set_duration(0.0)
        self.headers_widget.set_tracks([], set())
        self._update_time_labels()

    def set_duration(self, duration_ms: int):
        new_dur = duration_ms / 1000.0
        if abs(self._duration_sec - new_dur) < 0.05 and self._duration_sec > 0:
            return
        self._duration_sec = new_dur
        self._in_point_sec = 0.0
        self._out_point_sec = self._duration_sec
        for s_idx in self._track_cut_ranges:
            self._track_cut_ranges[s_idx] = (0.0, self._duration_sec)

        self.canvas.set_duration(self._duration_sec)
        self.canvas.set_track_ranges(self._track_cut_ranges)
        self.fit_to_width()
        self._update_time_labels()

    def set_position(self, position_ms: int):
        self._current_pos_sec = position_ms / 1000.0
        self.canvas.set_position(self._current_pos_sec)
        self._update_time_labels()

    def set_tracks(self, tracks: list[dict[str, Any]]):
        self._tracks = tracks
        self._active_stream_indices = {t.get("stream_index", i) for i, t in enumerate(tracks)}
        self._selected_stream_index = self._get_master_video_stream_index()
        self._track_cut_ranges = {
            t.get("stream_index", i): (self._in_point_sec, self._out_point_sec)
            for i, t in enumerate(tracks)
        }

        self.headers_widget.set_tracks(self._tracks, self._active_stream_indices)
        self.headers_widget.set_selected_stream(self._selected_stream_index)
        self.canvas.set_tracks(self._tracks, self._active_stream_indices)
        self.canvas.set_selected_stream(self._selected_stream_index)
        self.canvas.set_track_ranges(self._track_cut_ranges)
        self._update_time_labels()

    def set_keyframes(self, keyframes: list[float]):
        """Pass keyframes to timeline widget and canvas for visual display and snapping."""
        self._keyframes = sorted(keyframes or [])
        self.canvas.set_keyframes(self._keyframes)

    def snap_to_keyframe(self, target_sec: float, max_delta: float = 3.0) -> float:
        """Snap timestamp to closest keyframe if snap is enabled and keyframe is within max_delta."""
        if not self.chk_snap.isChecked() or not self._keyframes:
            return target_sec
        closest = min(self._keyframes, key=lambda k: abs(k - target_sec))
        if abs(closest - target_sec) <= max_delta:
            return closest
        return target_sec

    def set_video_thumbnails(self, thumbnails: list[dict[str, Any]]):
        """Pass video frame thumbnails to canvas."""
        self.canvas.set_thumbnails(thumbnails)

    def set_audio_waveforms(self, waveforms: dict[int, list[float]]):
        """Pass real audio waveform peaks to canvas."""
        self.canvas.set_audio_waveforms(waveforms)

    def set_audio_waveform_stream(self, stream_index: int, peaks: list[float]):
        """Pass a single stream's waveform peaks to canvas immediately."""
        self.canvas.set_audio_waveform_stream(stream_index, peaks)

    def get_in_point(self) -> float:
        return self._in_point_sec

    def get_out_point(self) -> float:
        return self._out_point_sec

    def is_snap_enabled(self) -> bool:
        return self.chk_snap.isChecked()

    def get_selected_stream_indices(self) -> list[int]:
        return sorted(list(self._active_stream_indices))

    def fit_to_width(self):
        """Scale zoom so entire video fits available canvas width."""
        avail_w = max(400, self.scroll_area.viewport().width() - 40)
        if self._duration_sec > 0:
            pps = avail_w / self._duration_sec
            pps = max(0.05, min(200.0, pps))
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(max(1, int(round(pps))))
            self.zoom_slider.blockSignals(False)
            self.canvas.set_zoom(pps)

    # --- Internal Handlers ---
    def _on_track_toggled(self, stream_index: int, is_active: bool):
        if is_active:
            self._active_stream_indices.add(stream_index)
        else:
            self._active_stream_indices.discard(stream_index)
        self.canvas.set_active_stream_indices(self._active_stream_indices)
        self.tracks_changed.emit(self.get_selected_stream_indices())

    def _on_seek_requested(self, pos_ms: int):
        self._current_pos_sec = pos_ms / 1000.0
        self._update_time_labels()
        self.seek_requested.emit(pos_ms)

    def _on_in_dragged(self, in_sec: float):
        if self.chk_snap.isChecked() and self._keyframes:
            in_sec = self.snap_to_keyframe(in_sec, max_delta=0.4)

        video_idx = self._get_master_video_stream_index()
        if self._cut_mode == "global":
            self._in_point_sec = in_sec
            for s_idx in self._track_cut_ranges:
                self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
            self.canvas.set_in_point(self._in_point_sec)
        else:
            target_idx = self._selected_stream_index if self._selected_stream_index is not None else video_idx
            cur_in, cur_out = self._track_cut_ranges.get(target_idx, (0.0, self._duration_sec))
            self._track_cut_ranges[target_idx] = (min(in_sec, cur_out - 0.05), cur_out)
            self._enforce_master_child_constraints(target_idx)
            if target_idx == video_idx:
                self._in_point_sec = self._track_cut_ranges[target_idx][0]
                self._out_point_sec = self._track_cut_ranges[target_idx][1]
            act_in, _ = self._track_cut_ranges[target_idx]
            self.canvas.set_in_point(act_in)

        self.canvas.set_track_ranges(self._track_cut_ranges)
        self._update_time_labels()
        self.in_point_changed.emit(self._in_point_sec)

    def _on_out_dragged(self, out_sec: float):
        if self.chk_snap.isChecked() and self._keyframes:
            out_sec = self.snap_to_keyframe(out_sec, max_delta=0.4)

        video_idx = self._get_master_video_stream_index()
        if self._cut_mode == "global":
            self._out_point_sec = out_sec
            for s_idx in self._track_cut_ranges:
                self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
            self.canvas.set_out_point(self._out_point_sec)
        else:
            target_idx = self._selected_stream_index if self._selected_stream_index is not None else video_idx
            cur_in, cur_out = self._track_cut_ranges.get(target_idx, (0.0, self._duration_sec))
            self._track_cut_ranges[target_idx] = (cur_in, max(out_sec, cur_in + 0.05))
            self._enforce_master_child_constraints(target_idx)
            if target_idx == video_idx:
                self._in_point_sec = self._track_cut_ranges[target_idx][0]
                self._out_point_sec = self._track_cut_ranges[target_idx][1]
            _, act_out = self._track_cut_ranges[target_idx]
            self.canvas.set_out_point(act_out)

        self.canvas.set_track_ranges(self._track_cut_ranges)
        self._update_time_labels()
        self.out_point_changed.emit(self._out_point_sec)

    def _set_in_current(self):
        pos = self._current_pos_sec
        if self.chk_snap.isChecked() and self._keyframes:
            pos = self.snap_to_keyframe(pos, max_delta=5.0)
            self._current_pos_sec = pos
            self.canvas.set_position(pos)
            self.seek_requested.emit(int(round(pos * 1000)))

        video_idx = self._get_master_video_stream_index()

        if self._cut_mode == "global":
            self._in_point_sec = min(pos, self._out_point_sec - 0.05)
            for s_idx in self._track_cut_ranges:
                self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
            self.canvas.set_in_point(self._in_point_sec)
        else:
            target_idx = self._selected_stream_index if self._selected_stream_index is not None else video_idx
            cur_in, cur_out = self._track_cut_ranges.get(target_idx, (0.0, self._duration_sec))
            self._track_cut_ranges[target_idx] = (min(pos, cur_out - 0.05), cur_out)
            self._enforce_master_child_constraints(target_idx)
            if target_idx == video_idx:
                self._in_point_sec = self._track_cut_ranges[target_idx][0]
                self._out_point_sec = self._track_cut_ranges[target_idx][1]
            act_in, _ = self._track_cut_ranges[target_idx]
            self.canvas.set_in_point(act_in)

        self.canvas.set_track_ranges(self._track_cut_ranges)
        self._update_time_labels()
        self.in_point_changed.emit(self._in_point_sec)

    def _set_out_current(self):
        pos = self._current_pos_sec
        if self.chk_snap.isChecked() and self._keyframes:
            pos = self.snap_to_keyframe(pos, max_delta=5.0)
            self._current_pos_sec = pos
            self.canvas.set_position(pos)
            self.seek_requested.emit(int(round(pos * 1000)))

        video_idx = self._get_master_video_stream_index()

        if self._cut_mode == "global":
            self._out_point_sec = max(pos, self._in_point_sec + 0.05)
            for s_idx in self._track_cut_ranges:
                self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
            self.canvas.set_out_point(self._out_point_sec)
        else:
            target_idx = self._selected_stream_index if self._selected_stream_index is not None else video_idx
            cur_in, cur_out = self._track_cut_ranges.get(target_idx, (0.0, self._duration_sec))
            self._track_cut_ranges[target_idx] = (cur_in, max(pos, cur_in + 0.05))
            self._enforce_master_child_constraints(target_idx)
            if target_idx == video_idx:
                self._in_point_sec = self._track_cut_ranges[target_idx][0]
                self._out_point_sec = self._track_cut_ranges[target_idx][1]
            _, act_out = self._track_cut_ranges[target_idx]
            self.canvas.set_out_point(act_out)

        self.canvas.set_track_ranges(self._track_cut_ranges)
        self._update_time_labels()
        self.out_point_changed.emit(self._out_point_sec)

    def _update_time_labels(self):
        cur_str = format_timestamp(self._current_pos_sec)
        dur_str = format_timestamp(self._duration_sec)
        self.lbl_time_display.setText(f"{cur_str} / {dur_str}")

        if not self._tracks or self._duration_sec <= 0:
            self.lbl_active_track.setText("Track: Tất cả")
            act_in = 0.0
            act_out = 0.0
        elif self._cut_mode == "global" or self._selected_stream_index is None:
            self.lbl_active_track.setText("Track: Tất cả (Đồng bộ)")
            act_in = self._in_point_sec
            act_out = self._out_point_sec
        else:
            trk_info = next((t for t in self._tracks if t.get("stream_index") == self._selected_stream_index), None)
            trk_name = f"{trk_info.get('type_label', '')}" if trk_info else f"Track #{self._selected_stream_index}"
            self.lbl_active_track.setText(f"Đang chỉnh: [{trk_name}]")
            act_in, act_out = self._track_cut_ranges.get(
                self._selected_stream_index, (self._in_point_sec, self._out_point_sec)
            )

        self.lbl_in_val.setText(f"In: {format_timestamp(act_in)}")
        self.lbl_out_val.setText(f"Out: {format_timestamp(act_out)}")

        cut_dur = max(0.0, act_out - act_in)
        self.lbl_cut_dur.setText(f"Thời lượng cắt: {format_timestamp(cut_dur)}")

    def _on_zoom_slider_changed(self, val: int):
        self.canvas.set_zoom(float(val))

    def _adjust_zoom(self, delta_factor: float):
        cur_pps = self.canvas.get_pixels_per_sec()
        new_pps = cur_pps * (1.0 + delta_factor)
        new_pps = max(0.05, min(200.0, new_pps))
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(max(1, int(round(new_pps))))
        self.zoom_slider.blockSignals(False)
        self.canvas.set_zoom(new_pps)

    def resizeEvent(self, event):
        super().resizeEvent(event)
