"""Module quản lý lịch sử thao tác (Undo / Redo History) cho Lossless Video Cutter.

Lưu trữ trạng thái biên tập dưới dạng snapshot để cho phép hoàn tác (Undo - Ctrl+Z)
và làm lại (Redo - Ctrl+Y / Ctrl+Shift+Z) tức thì mà không gây rò rỉ bộ nhớ.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EditState:
    """Ảnh chụp nhanh trạng thái biên tập tại một thời điểm."""

    in_sec: float
    out_sec: float
    active_stream_indices: set[int] = field(default_factory=set)
    rotation: int = 0
    render_mode: str = "copy"  # "copy" | "smart"
    track_cut_ranges: dict[int, tuple[float, float]] = field(default_factory=dict)

    def is_equal_to(self, other: "EditState") -> bool:
        """So sánh hai trạng thái có tương đồng nội dung hay không."""
        if not isinstance(other, EditState):
            return False
        return (
            abs(self.in_sec - other.in_sec) < 0.001
            and abs(self.out_sec - other.out_sec) < 0.001
            and self.active_stream_indices == other.active_stream_indices
            and (self.rotation % 360) == (other.rotation % 360)
            and self.render_mode == other.render_mode
            and self.track_cut_ranges == other.track_cut_ranges
        )


class HistoryManager:
    """Quản lý hai ngăn xếp Undo và Redo cho toàn bộ ứng dụng."""

    def __init__(self, max_depth: int = 50):
        self._max_depth = max(5, int(max_depth))
        self._undo_stack: list[EditState] = []
        self._redo_stack: list[EditState] = []
        self._is_applying_history = False

    @property
    def is_applying_history(self) -> bool:
        """Đang trong quá trình khôi phục trạng thái (tránh ghi đè sự kiện trùng lặp)."""
        return self._is_applying_history

    def set_applying(self, val: bool):
        self._is_applying_history = bool(val)

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def clear(self):
        """Xóa sạch ngăn xếp lịch sử khi nạp video mới hoặc đóng video."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._is_applying_history = False

    def push_state(self, state: EditState):
        """Ghi nhận một trạng thái mới vào ngăn xếp Undo.

        Nếu trạng thái mới hoàn toàn trùng khớp với đỉnh ngăn xếp, bỏ qua để tránh rác bộ nhớ.
        """
        if self._is_applying_history:
            return

        if self._undo_stack and self._undo_stack[-1].is_equal_to(state):
            return

        self._undo_stack.append(state)
        if len(self._undo_stack) > self._max_depth:
            self._undo_stack.pop(0)

        # Mọi thao tác chỉnh sửa mới đều làm mới ngăn xếp Redo
        self._redo_stack.clear()

    def undo(self, current_state: EditState) -> Optional[EditState]:
        """Hoàn tác về trạng thái trước đó.

        Trả về EditState cần khôi phục, hoặc None nếu không thể hoàn tác.
        """
        if not self.can_undo():
            return None

        # Đẩy trạng thái hiện tại sang ngăn xếp Redo
        self._redo_stack.append(current_state)
        # Lấy trạng thái gần nhất từ ngăn xếp Undo
        previous_state = self._undo_stack.pop()
        return previous_state

    def redo(self, current_state: EditState) -> Optional[EditState]:
        """Làm lại thao tác vừa hoàn tác.

        Trả về EditState cần khôi phục, hoặc None nếu không thể làm lại.
        """
        if not self.can_redo():
            return None

        # Đẩy trạng thái hiện tại vào ngăn xếp Undo
        self._undo_stack.append(current_state)
        # Lấy trạng thái từ ngăn xếp Redo
        next_state = self._redo_stack.pop()
        return next_state

