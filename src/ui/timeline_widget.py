"""Widget dòng thời gian đa luồng (Multi-track Timeline) phong cách CapCut cho Lossless Video Cutter.

Cung cấp các rãnh hiển thị trực quan (Video với dải cuộn phim, Audio với sóng âm thanh thực tế,
Phụ đề), thước đo thời gian, vùng chọn cắt In/Out nổi bật, thanh Playhead tương tác,
nút bật/tắt từng track độc lập và bộ điều khiển thu phóng zoom.
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

from src.core.cutter import format_timestamp, find_nearest_keyframe
from src.ui.styles import (
    UNIFIED_BUTTON_STYLE,
    UNIFIED_ICON_BUTTON_STYLE,
    BUTTON_SET_IN_STYLE,
    BUTTON_SET_OUT_STYLE,
)


# Bảng màu cài sẵn phân biệt các loại rãnh track
TRACK_PALETTES = [
    # Bảng màu Video (Xanh mòng két / Cyan)
    {"bg_grad1": QColor("#0e6251"), "bg_grad2": QColor("#16a085"), "border": QColor("#1abc9c"), "accent": QColor("#48c9b0")},
    # Audio 1 (Xanh dương CapCut)
    {"bg_grad1": QColor("#1b4f72"), "bg_grad2": QColor("#2874a6"), "border": QColor("#2980b9"), "accent": QColor("#38bdf8")},
    # Audio 2 (Xanh ngọc lục bảo)
    {"bg_grad1": QColor("#145a32"), "bg_grad2": QColor("#1e8449"), "border": QColor("#27ae60"), "accent": QColor("#4ade80")},
    # Audio 3 (Tím thạch anh)
    {"bg_grad1": QColor("#4a235a"), "bg_grad2": QColor("#6c3483"), "border": QColor("#8e44ad"), "accent": QColor("#c084fc")},
    # Audio 4 (Hổ phách / Cam)
    {"bg_grad1": QColor("#7e5109"), "bg_grad2": QColor("#b9770e"), "border": QColor("#d35400"), "accent": QColor("#fb923c")},
]


class TimelineCanvas(QWidget):
    """Canvas tự vẽ Timeline tích hợp thước đo thời gian, dải cuộn phim và sóng âm thanh."""

    seek_requested = Signal(int)  # ms
    in_point_dragged = Signal(float)  # giây
    out_point_dragged = Signal(float)  # giây
    drag_finished = Signal(str)  # 'in' | 'out' | 'playhead'
    track_clicked = Signal(int)  # stream_index
    zoom_requested = Signal(int)  # bước delta khi Ctrl + Lăn chuột

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
        self._pixels_per_sec: float = 50.0  # Tỷ lệ zoom
        self._tracks: list[dict[str, Any]] = []
        self._active_stream_indices: set[int] = set()

        # Trạng thái cắt từng track
        self._track_cut_ranges: dict[int, tuple[float, float]] = {}
        self._selected_stream_index: int | None = None
        self._cut_mode: str = "global"

        # Dữ liệu xem trước thực tế
        self._thumbnails: list[dict[str, Any]] = []  # [{"time_sec": float, "pixmap": QPixmap}]
        self._audio_waveforms: dict[int, list[float]] = {}  # {stream_index: [float]}
        self._keyframes: list[float] = []

        # Trạng thái kéo chuột: None, 'playhead', 'in', 'out'
        self._drag_mode: str | None = None

        self._update_geometry()

    def set_keyframes(self, keyframes: list[float]):
        """Truyền danh sách Keyframe vào canvas để vẽ vạch chia và hỗ trợ bám dính."""
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
        """Xóa cache ảnh thumbnail, sóng âm và keyframe khi nạp file video hoàn toàn mới."""
        self._thumbnails = []
        self._audio_waveforms = {}
        self._keyframes = []
        self.update()

    def set_duration(self, duration_sec: float):
        # BẢO VỆ AN TOÀN: Tuyệt đối không ghi đè thời lượng video hợp lệ (> 0) bằng 0 hoặc âm
        # khi media player gặp lỗi giải mã hoặc đang khởi tạo
        if duration_sec <= 0 and self._duration_sec > 0:
            return
        if abs(self._duration_sec - duration_sec) < 0.05 and self._duration_sec > 0:
            return
        self._duration_sec = max(0.0, duration_sec)
        self._in_point_sec = 0.0
        self._out_point_sec = self._duration_sec
        self._update_geometry()
        self.update()

    def set_position(self, pos_sec: float):
        if self._drag_mode is not None:
            # Người dùng đang chủ động kéo con trỏ phát hoặc mốc In/Out, không ghi đè từ nhịp phát của player
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
        self._pixels_per_sec = max(0.05, min(60.0, pps))
        self._update_geometry()
        self.update()

    def set_thumbnails(self, thumbnails_data: list[dict[str, Any]]):
        """Không thực hiện: Track video dùng răng cưa cuộn phim vector nhẹ để có độ trễ bằng 0."""
        self._thumbnails = []

    def set_audio_waveforms(self, waveforms: dict[int, list[float]]):
        """Lưu trữ dạng sóng âm thanh thực đã trích xuất và vẽ lại giao diện."""
        self._audio_waveforms.update(waveforms)
        self.update()

    def set_audio_waveform_stream(self, stream_index: int, peaks: list[float]):
        """Lưu trữ dạng sóng của một luồng đơn và vẽ lại ngay lập tức."""
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

    # --- Sự kiện chuột ---
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton or not self._tracks or self._duration_sec <= 0:
            return

        x = event.position().x()
        y = event.position().y()
        click_sec = self._x_to_sec(x)

        # Nếu nhấp vào một lane track, chọn track đó
        if y > self.RULER_HEIGHT:
            lane_idx = int((y - self.RULER_HEIGHT) // (self.LANE_HEIGHT + self.LANE_SPACING))
            if 0 <= lane_idx < len(self._tracks):
                clicked_s_idx = self._tracks[lane_idx].get("stream_index", lane_idx)
                self.track_clicked.emit(clicked_s_idx)

        # Nhấp và kéo chuột trên canvas dùng để di chuyển con trỏ phát (các mốc In/Out đặt qua nút bấm/phím tắt)
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
        else:
            # Chuột không được nhấn: giữ con trỏ chuột hình mũi tên chuẩn trên timeline
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, event: QMouseEvent):
        mode = self._drag_mode
        self._drag_mode = None
        if mode:
            self.drag_finished.emit(mode)

    def wheelEvent(self, event: QWheelEvent):
        """Cho phép phóng to/thu nhỏ bằng Ctrl + Con lăn chuột trực tiếp trên timeline."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta != 0:
                step = 10 if delta > 0 else -10
                self.zoom_requested.emit(step)
                event.accept()
                return
        super().wheelEvent(event)

    # --- Cắt tỉa khung nhìn (Viewport Culling) & Vẽ siêu tốc ---
    def _get_visible_x_bounds(self) -> tuple[float, float]:
        """Trả về (vis_left, vis_right) theo tọa độ canvas đại diện cho vùng đang hiển thị trên màn hình."""
        parent = self.parent()
        if isinstance(parent, QWidget):
            vp_rect = parent.rect()
            p_tl = self.mapFromParent(vp_rect.topLeft())
            p_br = self.mapFromParent(vp_rect.bottomRight())
            left = max(0.0, float(p_tl.x()) - 60.0)
            right = min(float(self.width()), float(p_br.x()) + 60.0)
            if right > left:
                return left, right

        return 0.0, float(self.width())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        w = self.width()
        h = self.height()
        vis_left, vis_right = self._get_visible_x_bounds()

        # 1. Hình nền (chỉ vẽ phần cắt khung nhìn đang hiển thị)
        painter.fillRect(QRectF(vis_left, 0, vis_right - vis_left, h), QColor("#16181d"))

        # 2. Vẽ thước thời gian (đã áp dụng cắt tỉa khung nhìn)
        self._draw_ruler(painter, w, vis_left, vis_right)

        if not self._tracks or self._duration_sec <= 0:
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor("#484f58"))
            empty_rect = QRectF(vis_left, self.RULER_HEIGHT, vis_right - vis_left, h - self.RULER_HEIGHT)
            painter.drawText(empty_rect, Qt.AlignmentFlag.AlignCenter, "Chưa nạp video (Kéo thả video vào bất kỳ đâu hoặc bấm 'Mở Video')")
            return

        # 3. Vẽ các lane track (Cuộn phim video & Dạng sóng âm thanh - đã cắt tỉa)
        self._draw_tracks(painter, w, vis_left, vis_right)

        # 4. Vẽ lớp phủ vùng chọn cắt (In -> Out - đã cắt tỉa)
        self._draw_cut_overlay(painter, w, h, vis_left, vis_right)

        # 5. Vẽ kim con trỏ phát (đã cắt tỉa)
        self._draw_playhead(painter, h, vis_left, vis_right)

    def _draw_ruler(self, painter: QPainter, width: int, vis_left: float, vis_right: float):
        ruler_rect = QRectF(vis_left, 0, vis_right - vis_left, self.RULER_HEIGHT)
        painter.fillRect(ruler_rect, QColor("#1e222b"))

        # Đường viền dưới của thước đo
        painter.setPen(QPen(QColor("#2c313c"), 1))
        painter.drawLine(QPointF(vis_left, self.RULER_HEIGHT), QPointF(vis_right, self.RULER_HEIGHT))

        if self._duration_sec <= 0:
            return

        pps = max(0.001, self._pixels_per_sec)
        font = QFont("Segoe UI", 8)
        painter.setFont(font)

        MIN_LABEL_PX_SPACING = 75.0

        # Chế độ A: Thước đo tập trung vào Keyframe (Số và vạch chia chỉ hiển thị tại Keyframe)
        if self._keyframes:
            start_sec = max(0.0, self._x_to_sec(vis_left) - 1.0)
            end_sec = min(self._duration_sec, self._x_to_sec(vis_right) + 1.0)

            # Lọc các keyframe nằm trong khung nhìn hiện tại
            visible_kfs = [k for k in self._keyframes if start_sec <= k <= end_sec]

            # 1. Lượt 1: Vẽ các vạch màu ngọc lục bảo cho TẤT CẢ keyframe hiển thị
            kf_pen = QPen(QColor("#2ecc71"), 1.8)
            painter.setPen(kf_pen)
            for kf in visible_kfs:
                kx = self._sec_to_x(kf)
                if vis_left <= kx <= vis_right:
                    painter.drawLine(QPointF(kx, self.RULER_HEIGHT - 10), QPointF(kx, self.RULER_HEIGHT))
                    painter.drawPoint(QPointF(kx, self.RULER_HEIGHT - 12))

            # 2. Lượt 2: Vẽ số mốc thời gian tại các vị trí keyframe (đảm bảo khoảng cách >= 75px)
            last_text_x = -9999.0
            painter.setPen(QColor("#2ecc71"))

            for kf in visible_kfs:
                kx = self._sec_to_x(kf)
                if vis_left <= kx <= vis_right and (kx - last_text_x >= MIN_LABEL_PX_SPACING):
                    hrs = int(kf // 3600)
                    mins = int((kf % 3600) // 60)
                    secs = int(kf % 60)
                    millis = int(round((kf - int(kf)) * 100))

                    if pps >= 20.0:
                        # Độ chính xác mili-giây khi phóng to
                        label = f"{mins:02d}:{secs:02d}.{millis:02d}"
                    elif hrs > 0:
                        label = f"{hrs:02d}:{mins:02d}:{secs:02d}"
                    else:
                        label = f"{mins:02d}:{secs:02d}"

                    painter.drawText(QRectF(kx - 35, 1, 70, 14), Qt.AlignmentFlag.AlignCenter, label)
                    last_text_x = kx

        # Chế độ B: Thước thời gian dự phòng (khi đang quét keyframe ngầm hoặc file chỉ có âm thanh)
        else:
            step_presets = [
                (0.2, 0.05), (0.5, 0.1), (1.0, 0.2), (2.0, 0.5), (5.0, 1.0),
                (10.0, 2.0), (15.0, 5.0), (30.0, 5.0), (60.0, 10.0), (120.0, 30.0),
                (300.0, 60.0), (600.0, 120.0), (1800.0, 300.0), (3600.0, 600.0),
            ]
            step, sub_step = step_presets[-1]
            for s, sub in step_presets:
                if s * pps >= 85.0:
                    step, sub_step = s, sub
                    break

            start_sec = max(0.0, self._x_to_sec(vis_left) - step)
            end_sec = min(self._duration_sec, self._x_to_sec(vis_right) + step)

            t = math.floor(start_sec / step) * step
            while t <= end_sec:
                x = self._sec_to_x(t)
                if vis_left <= x <= vis_right:
                    painter.setPen(QPen(QColor("#8b949e"), 1))
                    painter.drawLine(QPointF(x, self.RULER_HEIGHT - 12), QPointF(x, self.RULER_HEIGHT))

                    mins = int((t % 3600) // 60)
                    secs = int(t % 60)
                    label = f"{mins:02d}:{secs:02d}"
                    painter.setPen(QColor("#abb2bf"))
                    painter.drawText(QRectF(x - 35, 2, 70, 14), Qt.AlignmentFlag.AlignCenter, label)

                sub_t = t + sub_step
                while sub_t < t + step and sub_t <= self._duration_sec:
                    sx = self._sec_to_x(sub_t)
                    if vis_left <= sx <= vis_right:
                        painter.setPen(QPen(QColor("#484f58"), 1))
                        painter.drawLine(QPointF(sx, self.RULER_HEIGHT - 6), QPointF(sx, self.RULER_HEIGHT))
                    sub_t += sub_step

                t += step

    def _draw_tracks(self, painter: QPainter, width: int, vis_left: float, vis_right: float):
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

            # Xác định bảng màu tương ứng
            if c_type == "video":
                palette = TRACK_PALETTES[0]
            elif c_type == "audio":
                audio_counter += 1
                p_idx = 1 + ((audio_counter - 1) % (len(TRACK_PALETTES) - 1))
                palette = TRACK_PALETTES[p_idx]
            else:
                palette = TRACK_PALETTES[4]

            # Nền cho lane track (chỉ trong phạm vi hiển thị)
            painter.fillRect(QRectF(vis_left, lane_y, vis_right - vis_left, self.LANE_HEIGHT), QColor("#1c1f26"))

            # Khối clip
            if lane_rect.right() < vis_left or lane_rect.left() > vis_right:
                continue

            painter.save()
            if not is_active:
                painter.setOpacity(0.3)

            # Màu gradient nền cho clip
            grad = QLinearGradient(lane_rect.topLeft(), lane_rect.bottomLeft())
            grad.setColorAt(0.0, palette["bg_grad1"])
            grad.setColorAt(1.0, palette["bg_grad2"])
            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(palette["border"], 1.5))
            painter.drawRoundedRect(lane_rect, 4.0, 4.0)

            # 1. Lane Video: Vẽ răng cưa cuộn phim vector nhẹ (0% CPU, 0s trễ)
            if c_type == "video":
                self._draw_filmstrip_perforations(painter, lane_rect, vis_left, vis_right)

            # 2. Lane Âm thanh: Vẽ dạng sóng âm thanh thực tế (đã cắt tỉa)
            elif c_type == "audio":
                self._draw_real_audio_wave(painter, lane_rect, palette["accent"], s_idx, vis_left, vis_right)

            # Nhãn tên Clip (Ghim sát mép trái hiển thị để luôn nhìn rõ thông tin track)
            label_text = f"{trk.get('icon', '🎬')} {trk.get('type_label', 'Track')} : {trk.get('codec_name', '').upper()} {trk.get('details', '')}"
            if trk.get("title"):
                label_text += f" ({trk.get('title')})"
            if not is_active:
                label_text += " [ĐÃ BỎ QUA - KHÔNG XUẤT]"

            font = QFont("Segoe UI", 8, QFont.Weight.Bold)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            text_w = metrics.horizontalAdvance(label_text) + 14
            badge_w = min(text_w, lane_rect.width() - 8)

            badge_x = max(lane_rect.left() + 4, vis_left + 6)
            if badge_x + badge_w <= min(lane_rect.right() - 4, vis_right):
                badge_rect = QRectF(badge_x, lane_y + 3, badge_w, 16)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(0, 0, 0, 160)))
                painter.drawRoundedRect(badge_rect, 3.0, 3.0)

                painter.setPen(QColor("#ffffff"))
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label_text)

            painter.restore()

    def _draw_video_filmstrip(self, painter: QPainter, rect: QRectF, vis_left: float, vis_right: float):
        """Vẽ ảnh thu nhỏ video thành cuộn phim liên tục, giữ nguyên tỉ lệ khung hình."""
        if not self._thumbnails:
            return

        painter.save()
        painter.setClipRect(rect)

        # 1. Xác định tỉ lệ khung hình thực từ các ảnh thu nhỏ đã tải
        first_pix = self._thumbnails[0].get("pixmap")
        aspect_ratio = 16.0 / 9.0
        if first_pix and not first_pix.isNull() and first_pix.height() > 0:
            aspect_ratio = first_pix.width() / first_pix.height()

        h = max(10.0, rect.height() - 2.0)
        frame_w = max(35.0, min(140.0, h * aspect_ratio))

        times = [item["time_sec"] for item in self._thumbnails]
        count = len(times)

        # 2. Cắt tỉa khung nhìn: Chỉ xếp các khung hình trong phạm vi đang hiển thị
        left_bound = max(rect.left(), vis_left - frame_w)
        right_bound = min(rect.right(), vis_right + frame_w)

        offset = left_bound - rect.left()
        start_tile_x = rect.left() + math.floor(max(0.0, offset) / frame_w) * frame_w

        tile_x = start_tile_x
        while tile_x < right_bound:
            center_x = tile_x + frame_w / 2.0
            t_center = self._x_to_sec(center_x)

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

            # Đường phân cách mảnh giữa các khung hình liên tiếp
            painter.setPen(QPen(QColor(0, 0, 0, 160), 1.0))
            painter.drawLine(QPointF(tile_x + frame_w, rect.top()), QPointF(tile_x + frame_w, rect.bottom()))

            tile_x += frame_w

        # Đường viền trên và dưới của cuộn phim
        painter.setPen(QPen(QColor(0, 0, 0, 100), 1.0))
        painter.drawLine(QPointF(max(rect.left(), vis_left), rect.top()), QPointF(min(rect.right(), vis_right), rect.top()))
        painter.drawLine(QPointF(max(rect.left(), vis_left), rect.bottom()), QPointF(min(rect.right(), vis_right), rect.bottom()))

        painter.restore()

    def _draw_real_audio_wave(self, painter: QPainter, rect: QRectF, color: QColor, stream_index: int, vis_left: float, vis_right: float):
        """Vẽ các đỉnh sóng âm thanh thực tế đã trích xuất trên lane âm thanh."""
        peaks = self._audio_waveforms.get(stream_index)
        if not peaks:
            keys = sorted(list(self._audio_waveforms.keys()))
            if keys and stream_index in range(len(keys)):
                peaks = self._audio_waveforms.get(keys[stream_index])
            elif keys:
                peaks = self._audio_waveforms.get(keys[0])

        if not peaks:
            self._draw_fallback_audio_wave(painter, rect, color, stream_index, vis_left, vis_right)
            return

        painter.save()
        painter.setClipRect(rect)

        mid_y = rect.center().y()

        # 1. Đường tâm mảnh cho các vùng im lặng (chỉ trong phạm vi hiển thị)
        guide_pen = QPen(QColor(color.red(), color.green(), color.blue(), 55), 1.0)
        painter.setPen(guide_pen)
        painter.drawLine(QPointF(max(rect.left() + 4, vis_left), mid_y), QPointF(min(rect.right() - 4, vis_right), mid_y))

        # 2. Các cột dạng sóng sắc nét dạng bo tròn hai đầu (phong cách CapCut)
        bar_pen = QPen(color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(bar_pen)

        max_h = (rect.height() - 6) / 2.0
        step = 3.0  # 3 pixel mỗi cột sóng

        total_samples = len(peaks)
        pps = self._pixels_per_sec
        SAMPLES_PER_SEC = 200.0

        # Cắt tỉa khung nhìn: Chỉ vẽ các cột sóng trong phạm vi [vis_left, vis_right]
        left_bound = max(rect.left() + 4.0, vis_left)
        right_bound = min(rect.right() - 4.0, vis_right)

        offset = left_bound - (rect.left() + 4.0)
        start_x = (rect.left() + 4.0) + math.floor(max(0.0, offset) / step) * step

        x = start_x
        while x < right_bound:
            t = self._x_to_sec(x)
            dt = step / pps if pps > 0 else 0.015

            start_idx = int(t * SAMPLES_PER_SEC)
            end_idx = int((t + dt) * SAMPLES_PER_SEC) + 1

            start_idx = max(0, min(total_samples - 1, start_idx))
            end_idx = max(start_idx + 1, min(total_samples, end_idx))

            amp = max(peaks[start_idx:end_idx]) if end_idx > start_idx else peaks[start_idx]

            if amp >= 0.025:
                bar_h = max(2.5, amp * max_h)
                painter.drawLine(QPointF(x, mid_y - bar_h), QPointF(x, mid_y + bar_h))

            x += step

        painter.restore()

    def _draw_fallback_audio_wave(self, painter: QPainter, rect: QRectF, color: QColor, seed: int, vis_left: float, vis_right: float):
        """Đường cơ sở dự phòng trong khi dạng sóng thực đang tải ngầm."""
        painter.save()
        painter.setClipRect(rect)
        painter.setPen(QPen(color, 1.2))
        mid_y = rect.center().y()
        painter.drawLine(QPointF(max(rect.left() + 6, vis_left), mid_y), QPointF(min(rect.right() - 6, vis_right), mid_y))
        painter.restore()

    def _draw_filmstrip_perforations(self, painter: QPainter, rect: QRectF, vis_left: float, vis_right: float):
        """Vẽ các lỗ răng cưa cuộn phim cho clip video."""
        painter.save()
        painter.setClipRect(rect)
        painter.setBrush(QBrush(QColor(0, 0, 0, 70)))
        painter.setPen(Qt.PenStyle.NoPen)

        left_bound = max(rect.left() + 8.0, vis_left - 16.0)
        right_bound = min(rect.right() - 8.0, vis_right + 16.0)
        offset = left_bound - (rect.left() + 8.0)
        start_x = (rect.left() + 8.0) + math.floor(max(0.0, offset) / 16.0) * 16.0

        x = start_x
        while x < right_bound:
            painter.drawRoundedRect(QRectF(x, rect.top() + 3, 6, 4), 1.0, 1.0)
            painter.drawRoundedRect(QRectF(x, rect.bottom() - 7, 6, 4), 1.0, 1.0)
            x += 16.0

        painter.restore()

    def _draw_cut_overlay(self, painter: QPainter, width: int, height: int, vis_left: float, vis_right: float):
        """Làm tối các vùng bị loại trừ trên từng lane track và thước đo, đồng thời vẽ mốc In/Out."""
        if self._duration_sec <= 0:
            return

        dim_brush = QBrush(QColor(10, 12, 16, 185))

        # 1. Làm tối vùng bị loại trừ trên từng lane track (giới hạn trong khung nhìn)
        for i, trk in enumerate(self._tracks):
            s_idx = trk.get("stream_index", i)
            trk_in, trk_out = self._track_cut_ranges.get(s_idx, (self._in_point_sec, self._out_point_sec))
            in_x = self._sec_to_x(trk_in)
            out_x = self._sec_to_x(trk_out)
            lane_y = self.RULER_HEIGHT + self.LANE_SPACING + i * (self.LANE_HEIGHT + self.LANE_SPACING)

            # Làm tối phần trước điểm In của track này
            dim_before_end = min(in_x, vis_right)
            dim_before_start = max(0.0, vis_left)
            if dim_before_end > dim_before_start:
                painter.fillRect(QRectF(dim_before_start, lane_y, dim_before_end - dim_before_start, self.LANE_HEIGHT), dim_brush)

            # Làm tối phần sau điểm Out của track này
            dim_after_start = max(out_x, vis_left)
            dim_after_end = min(float(width), vis_right)
            if dim_after_end > dim_after_start:
                painter.fillRect(QRectF(dim_after_start, lane_y, dim_after_end - dim_after_start, self.LANE_HEIGHT), dim_brush)

            # Làm nổi bật vùng đang chọn của track (viền xanh cyan phát sáng)
            if s_idx == self._selected_stream_index:
                painter.save()
                painter.setPen(QPen(QColor("#00d2d3"), 2.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                active_w = max(4.0, out_x - in_x)
                painter.drawRoundedRect(QRectF(in_x, lane_y, active_w, self.LANE_HEIGHT), 2, 2)
                painter.restore()

            # 2. Làm tối vùng bị loại trừ trên thước đo (giới hạn trong khung nhìn)
        cur_in_x = self._sec_to_x(self._in_point_sec)
        cur_out_x = self._sec_to_x(self._out_point_sec)
        ruler_dim_brush = QBrush(QColor(10, 12, 16, 150))

        dim_r_before_end = min(cur_in_x, vis_right)
        dim_r_before_start = max(0.0, vis_left)
        if dim_r_before_end > dim_r_before_start:
            painter.fillRect(QRectF(dim_r_before_start, 0, dim_r_before_end - dim_r_before_start, self.RULER_HEIGHT), ruler_dim_brush)

        dim_r_after_start = max(cur_out_x, vis_left)
        dim_r_after_end = min(float(width), vis_right)
        if dim_r_after_end > dim_r_after_start:
            painter.fillRect(QRectF(dim_r_after_start, 0, dim_r_after_end - dim_r_after_start, self.RULER_HEIGHT), ruler_dim_brush)

        # 3. Đường gióng dọc và cờ mốc trên thước đo (chỉ vẽ khi nằm trong hoặc gần khung nhìn)
        if vis_left - 30 <= cur_in_x <= vis_right + 30:
            painter.setPen(QPen(QColor("#2ecc71"), 1.8, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(cur_in_x, self.RULER_HEIGHT), QPointF(cur_in_x, height))

            # Tay cầm cờ In trên thước đo
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

        # 4. Mốc điểm Out (Đỏ)
        if vis_left - 30 <= cur_out_x <= vis_right + 30:
            painter.setPen(QPen(QColor("#e74c3c"), 2.0, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(cur_out_x, self.RULER_HEIGHT), QPointF(cur_out_x, height))

            # Tay cầm cờ Out trên thước đo
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

    def _draw_playhead(self, painter: QPainter, height: int, vis_left: float, vis_right: float):
        """Vẽ kim con trỏ phát màu trắng trải dài qua thước đo và các track."""
        play_x = self._sec_to_x(self._current_pos_sec)
        if not (vis_left - 20 <= play_x <= vis_right + 20):
            return

        # Đường dọc của kim phát
        painter.setPen(QPen(QColor("#ffffff"), 2.0))
        painter.drawLine(QPointF(play_x, self.RULER_HEIGHT), QPointF(play_x, height))

        # Đầu kim con trỏ phát trên thước đo
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
    """Thanh bên trái hiển thị tiêu đề các track cùng công tắc bật/tắt xuất."""

    track_toggle_clicked = Signal(int, bool)  # stream_index, bật_hay_tắt
    track_selected = Signal(int)  # chỉ_số_stream

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setStyleSheet("background-color: #1a1d24; border-right: 1px solid #2c313c;")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 0, 4, 4)
        self._layout.setSpacing(4)

        # Tiêu đề phía trên khớp với chiều cao của thước đo
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
        # Xóa danh sách hiện tại
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

            # Bộ xử lý sự kiện nhấp vào thẻ track
            def _make_click_handler(idx):
                return lambda event: self._on_card_clicked(idx, event)
            card.mousePressEvent = _make_click_handler(s_idx)

            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(6, 2, 6, 2)
            card_layout.setSpacing(6)

            # Thông tin văn bản của track
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

            # Nút bật/tắt xuất track
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
                    padding: 2px 4px;
                    border-radius: 4px;
                    border: 1px solid #2ecc71;
                }
                QPushButton:hover { background-color: #2ecc71; border-color: #2ecc71; }
            """)
        else:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #252a34;
                    color: #718096;
                    font-size: 10px;
                    padding: 2px 4px;
                    border-radius: 4px;
                    border: 1px solid #3b4252;
                }
                QPushButton:hover { background-color: #2f3644; color: #a0aec0; border-color: #00d2d3; }
            """)


class TimelineWidget(QWidget):
    """Widget Timeline đa track phong cách CapCut hoàn chỉnh."""

    seek_requested = Signal(int)  # ms
    in_point_changed = Signal(float)  # sec
    out_point_changed = Signal(float)  # sec
    snap_toggled = Signal(bool)
    tracks_changed = Signal(list)  # danh sách chỉ số stream đang kích hoạt
    track_selected = Signal(int)  # chỉ số stream của track được chọn

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration_sec: float = 0.0
        self._current_pos_sec: float = 0.0
        self._in_point_sec: float = 0.0
        self._out_point_sec: float = 0.0
        self._tracks: list[dict[str, Any]] = []
        self._active_stream_indices: set[int] = set()

        # Trạng thái cắt theo từng track riêng lẻ
        self._cut_mode: str = "global"  # "global" hoặc "per_track"
        self._selected_stream_index: int | None = None
        self._track_cut_ranges: dict[int, tuple[float, float]] = {}
        self._keyframes: list[float] = []

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(2)

        # 1. Thanh điều khiển phía trên
        ctrl_bar = QWidget()
        ctrl_bar.setStyleSheet("background-color: #1e222b; border-bottom: 1px solid #2c313c;")
        ctrl_layout = QHBoxLayout(ctrl_bar)
        ctrl_layout.setContentsMargins(8, 4, 8, 4)
        ctrl_layout.setSpacing(10)

        # Hiển thị thời gian con trỏ phát hiện tại
        self.lbl_time_display = QLabel("00:00:00.000 / 00:00:00.000")
        self.lbl_time_display.setStyleSheet(
            "font-family: monospace; font-size: 13px; font-weight: bold; color: #00d2d3;"
        )
        ctrl_layout.addWidget(self.lbl_time_display)

        ctrl_layout.addSpacing(10)

        # Nút đặt và nhãn hiển thị điểm In
        self.btn_set_in = QPushButton("📍 Đặt In [I]")
        self.btn_set_in.setStyleSheet(BUTTON_SET_IN_STYLE)
        self.btn_set_in.setFixedHeight(28)
        self.btn_set_in.clicked.connect(self._set_in_current)
        self.lbl_in_val = QLabel("In: 00:00:00.000")
        self.lbl_in_val.setStyleSheet("font-family: monospace; font-weight: bold; color: #2ecc71;")

        # Nút đặt và nhãn hiển thị điểm Out
        self.btn_set_out = QPushButton("🏁 Đặt Out [O]")
        self.btn_set_out.setStyleSheet(BUTTON_SET_OUT_STYLE)
        self.btn_set_out.setFixedHeight(28)
        self.btn_set_out.clicked.connect(self._set_out_current)
        self.lbl_out_val = QLabel("Out: 00:00:00.000")
        self.lbl_out_val.setStyleSheet("font-family: monospace; font-weight: bold; color: #e74c3c;")

        # Thời lượng đoạn cắt
        self.lbl_cut_dur = QLabel("Thời lượng cắt: 00:00:00.000")
        self.lbl_cut_dur.setStyleSheet("font-family: monospace; font-weight: bold; color: #f1c40f;")

        ctrl_layout.addWidget(self.btn_set_in)
        ctrl_layout.addWidget(self.lbl_in_val)
        ctrl_layout.addSpacing(5)
        ctrl_layout.addWidget(self.btn_set_out)
        ctrl_layout.addWidget(self.lbl_out_val)
        ctrl_layout.addSpacing(5)
        ctrl_layout.addWidget(self.lbl_cut_dur)

        ctrl_layout.addStretch()

        # Bộ điều khiển thu phóng (0% = Khớp chiều rộng, 100% = Phóng to chi tiết tối đa 50 px/s)
        self.btn_zoom_out = QPushButton("-")
        self.btn_zoom_out.setFixedSize(28, 28)
        self.btn_zoom_out.setStyleSheet(UNIFIED_ICON_BUTTON_STYLE)
        self.btn_zoom_out.setToolTip("Thu nhỏ Timeline (-10%)")
        self.btn_zoom_out.clicked.connect(lambda: self._adjust_zoom(-10))

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, 100)
        self.zoom_slider.setValue(0)
        self.zoom_slider.setFixedWidth(90)
        self.zoom_slider.setToolTip("Thu phóng Timeline (0% = Thu vừa màn hình, 100% = Phóng to chi tiết)")
        self.zoom_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #252a34;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #00d2d3;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 1px solid #3b4252;
                width: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #00d2d3;
            }
        """)
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider_changed)

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedSize(28, 28)
        self.btn_zoom_in.setStyleSheet(UNIFIED_ICON_BUTTON_STYLE)
        self.btn_zoom_in.setToolTip("Phóng to Timeline (+10%)")
        self.btn_zoom_in.clicked.connect(lambda: self._adjust_zoom(10))

        self.btn_zoom_fit = QPushButton("Thu vừa")
        self.btn_zoom_fit.setFixedHeight(28)
        self.btn_zoom_fit.setStyleSheet(UNIFIED_BUTTON_STYLE)
        self.btn_zoom_fit.setToolTip("Thu vừa toàn bộ video khớp với chiều rộng màn hình")
        self.btn_zoom_fit.clicked.connect(self.fit_to_width)

        ctrl_layout.addWidget(self.btn_zoom_out)
        ctrl_layout.addWidget(self.zoom_slider)
        ctrl_layout.addWidget(self.btn_zoom_in)
        ctrl_layout.addWidget(self.btn_zoom_fit)

        main_layout.addWidget(ctrl_bar)

        # 2. Vùng hiển thị Track (Tiêu đề bên trái + Canvas bên phải)
        tracks_container = QWidget()
        tracks_layout = QHBoxLayout(tracks_container)
        tracks_layout.setContentsMargins(0, 0, 0, 0)
        tracks_layout.setSpacing(0)

        # Tiêu đề các track bên trái
        self.headers_widget = TrackHeadersWidget()
        self.headers_widget.track_toggle_clicked.connect(self._on_track_toggled)
        tracks_layout.addWidget(self.headers_widget)

        # Canvas bên phải đặt trong ScrollArea
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background-color: #16181d; }")

        self.canvas = TimelineCanvas()
        self.canvas.seek_requested.connect(self._on_seek_requested)
        self.canvas.in_point_dragged.connect(self._on_in_dragged)
        self.canvas.out_point_dragged.connect(self._on_out_dragged)
        self.canvas.drag_finished.connect(self._on_drag_finished)
        self.canvas.zoom_requested.connect(self._adjust_zoom)

        self.scroll_area.setWidget(self.canvas)
        tracks_layout.addWidget(self.scroll_area, stretch=1)

        # Kết nối tín hiệu chọn track
        self.headers_widget.track_selected.connect(self.select_track)
        self.canvas.track_clicked.connect(self.select_track)

        main_layout.addWidget(tracks_container)

    # --- API công khai cho Player & Window ---
    def select_track(self, stream_index: int):
        """Thiết lập track kích hoạt để chỉnh sửa trong chế độ per_track."""
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
        self.track_selected.emit(stream_index)

    def _on_cut_mode_toggled(self, checked: bool):
        """Chuyển đổi qua lại giữa chế độ Cắt đồng bộ và Cắt từng track."""
        if checked:
            self._cut_mode = "per_track"
            self.btn_cut_mode.setText("🎯 Cắt từng track")
            target = self._selected_stream_index if self._selected_stream_index is not None else self._get_master_video_stream_index()
            self.select_track(target)
        else:
            self._cut_mode = "global"
            self.btn_cut_mode.setText("🔗 Cắt đồng bộ")
            # Khi chuyển về cắt đồng bộ: đồng bộ tất cả các track theo mốc master [in_point_sec, out_point_sec]
            for s_idx in self._track_cut_ranges:
                self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
            self.canvas.set_track_ranges(self._track_cut_ranges)
            self.canvas.set_in_point(self._in_point_sec)
            self.canvas.set_out_point(self._out_point_sec)

        self.canvas.set_cut_mode(self._cut_mode)
        self._update_time_labels()

    def _get_video_stream_indices(self) -> list[int]:
        """Trả về danh sách chỉ số stream của tất cả các track video."""
        indices = [trk.get("stream_index", 0) for trk in self._tracks if trk.get("codec_type") == "video"]
        if not indices and self._tracks:
            # Dự phòng cho tệp chỉ có âm thanh: coi stream đầu tiên là master
            indices = [self._tracks[0].get("stream_index", 0)]
        return indices

    def _is_video_stream(self, stream_index: int) -> bool:
        """Trả về True nếu stream là track video (hoặc track master cho tệp chỉ có âm thanh)."""
        return stream_index in self._get_video_stream_indices()

    def _get_master_video_stream_index(self) -> int:
        video_indices = self._get_video_stream_indices()
        return video_indices[0] if video_indices else 0

    def _enforce_master_child_constraints(self, changed_s_idx: int):
        """Đảm bảo ràng buộc Master-Child:
        1. Mọi track video luôn đồng bộ 100% với nhau: (vid_in, vid_out).
        2. Các track âm thanh/phụ đề con bị ràng buộc: vid_in <= In_audio < Out_audio <= vid_out.
           Nếu video mở rộng sang sớm hơn, âm thanh giữ nguyên vị trí hiện tại.
           Nếu video thu hẹp vượt qua âm thanh, âm thanh được tự động đẩy/kéo để luôn nằm trọn trong video.
        """
        video_indices = self._get_video_stream_indices()
        master_v_idx = self._get_master_video_stream_index()
        if master_v_idx not in self._track_cut_ranges:
            return

        if self._is_video_stream(changed_s_idx):
            # Một track video đã bị thay đổi: đồng bộ TẤT CẢ các track video theo (vid_in, vid_out)
            vid_in, vid_out = self._track_cut_ranges.get(changed_s_idx, (self._in_point_sec, self._out_point_sec))
            for v_idx in video_indices:
                self._track_cut_ranges[v_idx] = (vid_in, vid_out)
            self._in_point_sec = vid_in
            self._out_point_sec = vid_out

            # Tự động kéo/đẩy các track con phi-video để đảm bảo luôn nằm nghiêm ngặt trong [vid_in, vid_out]
            for s_idx, (a_in, a_out) in list(self._track_cut_ranges.items()):
                if self._is_video_stream(s_idx):
                    continue
                new_in = max(vid_in, min(a_in, vid_out - 0.05))
                new_out = min(vid_out, max(a_out, new_in + 0.05))
                self._track_cut_ranges[s_idx] = (new_in, new_out)
        else:
            # Một track phi-video (âm thanh/phụ đề) bị sửa: giới hạn nghiêm ngặt bên trong [vid_in, vid_out]
            vid_in, vid_out = self._track_cut_ranges.get(master_v_idx, (self._in_point_sec, self._out_point_sec))
            a_in, a_out = self._track_cut_ranges.get(changed_s_idx, (vid_in, vid_out))
            new_in = max(vid_in, min(a_in, a_out - 0.05))
            new_out = min(vid_out, max(a_out, new_in + 0.05))
            self._track_cut_ranges[changed_s_idx] = (new_in, new_out)

    def get_track_ranges(self) -> dict[int, tuple[float, float]]:
        """Trả về ánh xạ stream_index -> (in_sec, out_sec)."""
        return dict(self._track_cut_ranges)

    def get_cut_mode(self) -> str:
        """Trả về chế độ cắt hiện tại ('global' | 'per_track')."""
        return self._cut_mode

    def clear_preview_data(self):
        """Xóa bộ nhớ đệm ảnh thu nhỏ và dạng sóng khi tải một tệp mới hoàn toàn."""
        self.canvas.clear_preview_data()

    def clear_timeline(self):
        """Đặt lại timeline và tất cả các track về trạng thái trống ban đầu."""
        self._duration_sec = 0.0
        self._current_pos_sec = 0.0
        self._in_point_sec = 0.0
        self._out_point_sec = 0.0
        self._tracks = []
        self._active_stream_indices = set()
        self._track_cut_ranges = {}
        self._selected_stream_index = None

        self._cut_mode = "global"

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
        # BẢO VỆ AN TOÀN: Tuyệt đối không ghi đè thời lượng video hợp lệ (> 0) bằng 0 hoặc âm
        # khi QMediaPlayer gặp lỗi giải mã (ResourceError/FormatError) hoặc báo 0ms
        if duration_ms <= 0:
            if self._duration_sec > 0:
                return
            duration_ms = 0
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

        # Tự động cuộn mượt mà trong khi phát nếu con trỏ phát tiến gần ranh giới khung nhìn
        if self.canvas._drag_mode is None and self._duration_sec > 0:
            vp = self.scroll_area.viewport()
            vp_w = vp.width()
            sb = self.scroll_area.horizontalScrollBar()
            cur_scroll = sb.value()
            play_x = self.canvas._sec_to_x(self._current_pos_sec)

            margin = int(vp_w * 0.15)
            if play_x > cur_scroll + vp_w - margin:
                sb.setValue(int(play_x - margin))
            elif play_x < cur_scroll:
                sb.setValue(int(max(0, play_x - margin)))

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
        """Chuyển danh sách keyframe cho timeline widget và canvas để hiển thị trực quan và hít điểm."""
        self._keyframes = sorted(keyframes or [])
        self.canvas.set_keyframes(self._keyframes)
        if self._keyframes:
            video_idx = self._get_master_video_stream_index()
            snapped_in = self.snap_to_keyframe(self._in_point_sec, force_closest=True)
            snapped_out = self.snap_to_keyframe(self._out_point_sec, force_closest=True)
            if snapped_out <= snapped_in:
                next_kfs = [k for k in self._keyframes if k > snapped_in]
                snapped_out = next_kfs[0] if next_kfs else self._duration_sec
            self._in_point_sec = snapped_in
            self._out_point_sec = snapped_out

            if self._cut_mode == "global":
                for s_idx in self._track_cut_ranges:
                    self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
                self.canvas.set_in_point(self._in_point_sec)
                self.canvas.set_out_point(self._out_point_sec)
            else:
                self._track_cut_ranges[video_idx] = (snapped_in, snapped_out)
                self._enforce_master_child_constraints(video_idx)
                target = self._selected_stream_index if self._selected_stream_index is not None else video_idx
                trk_in, trk_out = self._track_cut_ranges.get(target, (self._in_point_sec, self._out_point_sec))
                self.canvas.set_in_point(trk_in)
                self.canvas.set_out_point(trk_out)

            self.canvas.set_track_ranges(self._track_cut_ranges)
            self._update_time_labels()
            self.in_point_changed.emit(self._in_point_sec)
            self.out_point_changed.emit(self._out_point_sec)

    def snap_to_keyframe(
        self,
        target_sec: float,
        max_delta: float | None = None,
        force_closest: bool = False,
    ) -> float:
        """Hít mốc thời gian vào keyframe gần nhất.
        
        Args:
            target_sec: Mốc thời gian mục tiêu tính bằng giây.
            max_delta: Khoảng lệch tối đa tính bằng giây để hít điểm. Nếu None, tự động tính
                       dựa trên mức thu phóng timeline (khoảng 16-18 pixel trên màn hình).
            force_closest: Nếu True, luôn hít vào keyframe gần nhất bất kể khoảng cách.
        """
        if not self._keyframes:
            return target_sec
        if force_closest:
            return min(self._keyframes, key=lambda k: abs(k - target_sec))
        if max_delta is None:
            pps = max(0.1, self.canvas.get_pixels_per_sec())
            max_delta = max(0.25, min(2.5, 18.0 / pps))
        return find_nearest_keyframe(target_sec, self._keyframes, mode="closest", max_delta=max_delta)

    def set_video_thumbnails(self, thumbnails: list[dict[str, Any]]):
        """Chuyển danh sách ảnh thu nhỏ của khung hình video cho canvas."""
        self.canvas.set_thumbnails(thumbnails)

    def set_audio_waveforms(self, waveforms: dict[int, list[float]]):
        """Chuyển các đỉnh dạng sóng âm thanh thực cho canvas."""
        self.canvas.set_audio_waveforms(waveforms)

    def set_audio_waveform_stream(self, stream_index: int, peaks: list[float]):
        """Chuyển ngay các đỉnh dạng sóng của một luồng đơn cho canvas."""
        self.canvas.set_audio_waveform_stream(stream_index, peaks)

    def get_in_point(self) -> float:
        if self._keyframes:
            return self.snap_to_keyframe(self._in_point_sec, force_closest=True)
        return self._in_point_sec

    def get_out_point(self) -> float:
        if self._keyframes:
            return self.snap_to_keyframe(self._out_point_sec, force_closest=True)
        return self._out_point_sec

    def set_in_point(self, in_sec: float):
        """Thiết lập điểm In bằng mã lệnh và đồng bộ hóa canvas cùng các nhãn thời gian."""
        self._in_point_sec = max(0.0, min(in_sec, self._out_point_sec - 0.05))
        for s_idx in self._track_cut_ranges:
            self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
        self.canvas.set_in_point(self._in_point_sec)
        self.canvas.set_track_ranges(self._track_cut_ranges)
        self._update_time_labels()
        self.in_point_changed.emit(self._in_point_sec)

    def set_out_point(self, out_sec: float):
        """Thiết lập điểm Out bằng mã lệnh và đồng bộ hóa canvas cùng các nhãn thời gian."""
        self._out_point_sec = min(self._duration_sec, max(out_sec, self._in_point_sec + 0.05))
        for s_idx in self._track_cut_ranges:
            self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
        self.canvas.set_out_point(self._out_point_sec)
        self.canvas.set_track_ranges(self._track_cut_ranges)
        self._update_time_labels()
        self.out_point_changed.emit(self._out_point_sec)

    def is_snap_enabled(self) -> bool:
        return True

    def is_mix_audio_enabled(self) -> bool:
        return False

    def get_selected_stream_indices(self) -> list[int]:
        return sorted(list(self._active_stream_indices))

    def get_duration(self) -> float:
        return self._duration_sec

    def _get_fit_pps(self) -> float:
        """Tính số pixel mỗi giây sao cho toàn bộ video vừa vặn với chiều rộng hiển thị của canvas."""
        avail_w = max(400, self.scroll_area.viewport().width() - 40)
        if self._duration_sec > 0:
            return max(0.05, avail_w / self._duration_sec)
        return 10.0

    def _get_max_pps(self, fit_pps: float) -> float:
        """Mức thu phóng tối đa hợp lý (giới hạn ở 50 px/giây để tránh phóng to quá mức)."""
        return max(fit_pps, min(50.0, max(fit_pps * 8.0, 25.0)))

    def _calc_pps_from_slider(self, val: int) -> float:
        fit_pps = self._get_fit_pps()
        max_pps = self._get_max_pps(fit_pps)
        if val <= 0:
            return fit_pps
        if val >= 100:
            return max_pps
        alpha = val / 100.0
        # Thang tỉ lệ hàm mũ/hình học mượt mà
        return fit_pps * ((max_pps / fit_pps) ** alpha)

    def fit_to_width(self):
        """Thu phóng sao cho toàn bộ video vừa khít với chiều rộng canvas."""
        fit_pps = self._get_fit_pps()
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(0)
        self.zoom_slider.blockSignals(False)
        self.canvas.set_zoom(fit_pps)
        self.scroll_area.horizontalScrollBar().setValue(0)

    def sync_zoom_with_speed(self, speed: float):
        """Tự động điều chỉnh độ thu phóng của timeline cho khớp với tốc độ phát:
        Tốc độ chậm -> Phóng to gần hơn để soi rõ từng khung hình.
        Tốc độ chuẩn / nhanh -> Thu nhỏ để nhìn bao quát toàn bộ video.
        """
        if self._duration_sec <= 0:
            return
        if speed >= 1.0:
            target_val = 0
        else:
            # 1.00x -> 0% (Thu vừa màn hình)
            # 0.75x -> 33% (Phóng to 1.33x)
            # 0.50x -> 67% (Phóng to 2x)
            # 0.25x -> 100% (Phóng to 4x, chi tiết tối đa)
            target_val = int(round((1.0 - speed) / 0.75 * 100.0))
            target_val = max(0, min(100, target_val))

        self.zoom_slider.setValue(target_val)

    def _on_drag_finished(self, mode: str):
        if not self._keyframes:
            return

        if mode == "in":
            snapped = self.snap_to_keyframe(self._in_point_sec, force_closest=True)
            if snapped < self._out_point_sec:
                self._in_point_sec = snapped
                for s_idx in self._track_cut_ranges:
                    self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
                self.canvas.set_in_point(self._in_point_sec)
                self.canvas.set_track_ranges(self._track_cut_ranges)
                self._update_time_labels()
                self.in_point_changed.emit(self._in_point_sec)
        elif mode == "out":
            snapped = self.snap_to_keyframe(self._out_point_sec, force_closest=True)
            if snapped > self._in_point_sec:
                self._out_point_sec = snapped
                for s_idx in self._track_cut_ranges:
                    self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
                self.canvas.set_out_point(self._out_point_sec)
                self.canvas.set_track_ranges(self._track_cut_ranges)
                self._update_time_labels()
                self.out_point_changed.emit(self._out_point_sec)

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
        if self._keyframes:
            in_sec = self.snap_to_keyframe(in_sec)

        self._in_point_sec = min(in_sec, self._out_point_sec - 0.05)
        for s_idx in self._track_cut_ranges:
            self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
        self.canvas.set_in_point(self._in_point_sec)
        self.canvas.set_track_ranges(self._track_cut_ranges)
        self._update_time_labels()
        self.in_point_changed.emit(self._in_point_sec)

    def _on_out_dragged(self, out_sec: float):
        if self._keyframes:
            out_sec = self.snap_to_keyframe(out_sec)

        self._out_point_sec = max(out_sec, self._in_point_sec + 0.05)
        for s_idx in self._track_cut_ranges:
            self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
        self.canvas.set_out_point(self._out_point_sec)
        self.canvas.set_track_ranges(self._track_cut_ranges)
        self._update_time_labels()
        self.out_point_changed.emit(self._out_point_sec)

    def _set_in_current(self):
        pos = self._current_pos_sec
        if self._keyframes:
            pos = self.snap_to_keyframe(pos, force_closest=True)
            self._current_pos_sec = pos
            self.canvas.set_position(pos)
            self.seek_requested.emit(int(round(pos * 1000)))

        self._in_point_sec = min(pos, self._out_point_sec - 0.05)
        for s_idx in self._track_cut_ranges:
            self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
        self.canvas.set_in_point(self._in_point_sec)
        self.canvas.set_track_ranges(self._track_cut_ranges)
        self._update_time_labels()
        self.in_point_changed.emit(self._in_point_sec)

    def _set_out_current(self):
        pos = self._current_pos_sec
        if self._keyframes:
            pos = self.snap_to_keyframe(pos, force_closest=True)
            self._current_pos_sec = pos
            self.canvas.set_position(pos)
            self.seek_requested.emit(int(round(pos * 1000)))

        self._out_point_sec = max(pos, self._in_point_sec + 0.05)
        for s_idx in self._track_cut_ranges:
            self._track_cut_ranges[s_idx] = (self._in_point_sec, self._out_point_sec)
        self.canvas.set_out_point(self._out_point_sec)
        self.canvas.set_track_ranges(self._track_cut_ranges)
        self._update_time_labels()
        self.out_point_changed.emit(self._out_point_sec)

    def _update_time_labels(self):
        cur_str = format_timestamp(self._current_pos_sec)
        dur_str = format_timestamp(self._duration_sec)
        self.lbl_time_display.setText(f"{cur_str} / {dur_str}")

        act_in = self._in_point_sec
        act_out = self._out_point_sec

        self.lbl_in_val.setText(f"In: {format_timestamp(act_in)}")
        self.lbl_out_val.setText(f"Out: {format_timestamp(act_out)}")

        cut_dur = max(0.0, act_out - act_in)
        self.lbl_cut_dur.setText(f"Thời lượng cắt: {format_timestamp(cut_dur)}")

    def _on_zoom_slider_changed(self, val: int):
        # Neo vị trí thu phóng xung quanh con trỏ phát nếu đang trong tầm nhìn, ngược lại neo vào giữa khung nhìn
        vp_w = self.scroll_area.viewport().width()
        sb = self.scroll_area.horizontalScrollBar()
        cur_scroll = sb.value()
        anchor_sec = self._current_pos_sec
        play_x = self.canvas._sec_to_x(anchor_sec)
        if not (cur_scroll <= play_x <= cur_scroll + vp_w):
            anchor_sec = self.canvas._x_to_sec(cur_scroll + vp_w / 2.0)

        pps = self._calc_pps_from_slider(val)
        self.canvas.set_zoom(pps)

        # Căn giữa lại khung nhìn quanh điểm neo
        new_anchor_x = self.canvas._sec_to_x(anchor_sec)
        new_scroll = max(0, int(round(new_anchor_x - vp_w / 2.0)))
        sb.setValue(new_scroll)

    def _adjust_zoom(self, delta_step: int):
        """Điều chỉnh thanh trượt thu phóng theo bước gia số (ví dụ +10 hoặc -10)."""
        new_val = max(0, min(100, self.zoom_slider.value() + int(delta_step)))
        self.zoom_slider.setValue(new_val)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Nếu thanh trượt ở mức 0 (Thu vừa màn hình), tự động duy trì vừa vặn khi cửa sổ thay đổi kích thước/phóng to
        if self.zoom_slider.value() == 0 and self._duration_sec > 0:
            self.fit_to_width()
