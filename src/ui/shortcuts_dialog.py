"""Hộp thoại hiển thị danh sách phím tắt nhanh cho ứng dụng Lossless Video Cutter."""

from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFont, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
)

from src.core.config import get_app_icon_path
from src.ui.styles import UNIFIED_BUTTON_STYLE


def _create_badge_html(keys: list[str]) -> str:
    """Tạo chuỗi HTML hiển thị các phím tắt dạng badge hiện đại."""
    badge_style = (
        "background-color: #252a34; color: #00d2d3; border: 1px solid #3b4252; "
        "border-radius: 4px; padding: 2px 7px; font-family: 'Segoe UI', Consolas, monospace; "
        "font-size: 11px; font-weight: bold;"
    )
    separator = " <span style='color: #6c757d; font-size: 11px;'>+</span> "
    badges = [f"<span style='{badge_style}'>{k}</span>" for k in keys]
    return separator.join(badges)


class ShortcutRow(QWidget):
    """Một dòng hiển thị mô tả hành động bên trái và tổ hợp phím bên phải."""

    def __init__(self, description: str, key_combos: list[list[str]], parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)

        lbl_desc = QLabel(description, self)
        lbl_desc.setStyleSheet("color: #e2e8f0; font-size: 12px;")

        # Tạo chuỗi HTML cho một hoặc nhiều tổ hợp phím thay thế (ví dụ phím này HOẶC phím kia)
        combo_htmls = [_create_badge_html(combo) for combo in key_combos]
        keys_html = " <span style='color: #6c757d; font-size: 11px;'>hoặc</span> ".join(combo_htmls)

        lbl_keys = QLabel(self)
        lbl_keys.setTextFormat(Qt.TextFormat.RichText)
        lbl_keys.setText(keys_html)
        lbl_keys.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(lbl_desc, stretch=1)
        layout.addWidget(lbl_keys)


class ShortcutCategoryCard(QFrame):
    """Khung nhóm phím tắt theo từng phân loại (Card)."""

    def __init__(self, title: str, icon: str, shortcuts: list[tuple[str, list[list[str]]]], parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QFrame {
                background-color: #1e222b;
                border-radius: 8px;
                border: 1px solid #2c313c;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Tiêu đề nhóm
        lbl_title = QLabel(f"{icon}  {title}", self)
        lbl_title.setStyleSheet("color: #00d2d3; font-weight: bold; font-size: 13px; border: none;")
        layout.addWidget(lbl_title)

        # Đường kẻ phân cách nhẹ
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("border: none; border-top: 1px solid #2c313c; max-height: 1px;")
        layout.addWidget(line)

        # Danh sách phím tắt trong nhóm
        for desc, combos in shortcuts:
            row = ShortcutRow(desc, combos, self)
            layout.addWidget(row)


class ShortcutsDialog(QDialog):
    """Cửa sổ thông tin bảng phím tắt chuẩn Lossless Video Cutter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bảng Phím Tắt Nhanh - Lossless Video Cutter")
        self.setModal(True)
        self.setMinimumSize(660, 560)
        self.resize(680, 580)

        # Đặt biểu tượng ứng dụng
        icon_path = get_app_icon_path()
        if icon_path and icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setStyleSheet("""
            QDialog {
                background-color: #16181d;
            }
        """)

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 14)
        main_layout.setSpacing(12)

        # 1. Phần Đầu (Header): Tiêu đề và chú thích
        header_widget = QWidget(self)
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(4, 0, 4, 4)
        header_layout.setSpacing(3)

        lbl_header = QLabel("⌨️ Bảng Phím Tắt Tiện Ích", header_widget)
        lbl_header.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: bold;")
        lbl_sub = QLabel(
            "Cắt ghép video, tua frame và xoay video nhanh gấp 5 lần mà không cần thao tác chuột.",
            header_widget,
        )
        lbl_sub.setStyleSheet("color: #8b949e; font-size: 12px;")

        header_layout.addWidget(lbl_header)
        header_layout.addWidget(lbl_sub)
        main_layout.addWidget(header_widget)

        # 2. Vùng cuộn danh sách (Scroll Area)
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: #16181d;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #2c313c;
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: #00d2d3;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(2, 2, 2, 2)
        container_layout.setSpacing(10)

        # Nhóm 1: Phát & Tua Video
        playback_shortcuts = [
            ("Phát / Tạm dừng video (Play / Pause)", [["Space"]]),
            ("Lùi / Tiến 1 khung hình (~0.033s)", [["←"], ["→"]], ),
            ("Tua từng khung hình chính xác (Frame Step)", [[","], ["."]]),
            ("Nhảy tới Keyframe (I-frame) Trước / Sau", [["Ctrl", "←"], ["Ctrl", "→"]]),
            ("Nhảy nhanh Keyframe (phím tắt LosslessCut)", [["J"], ["L"]]),
            ("Tăng / Giảm tốc độ phát (0.25x – 2.00x)", [["["], ["]"]]),
            ("Đặt lại tốc độ phát về 1.00x chuẩn", [["R"]]),
            ("Chuyển đổi giải mã phần cứng GPU và CPU (*H/W ↔ S/W)", [["H"]]),
        ]
        container_layout.addWidget(
            ShortcutCategoryCard("Điều Khiển Phát & Tua Video", "🎬", playback_shortcuts, container)
        )

        # Nhóm 2: Đặt Mốc Cắt & Đoạn Video
        cutting_shortcuts = [
            ("Đặt mốc Bắt Đầu cắt (In Point - Bám Keyframe)", [["I"]]),
            ("Đặt mốc Kết Thúc cắt (Out Point - Bám Keyframe)", [["O"]]),
            ("Xuất video Lossless đã cắt (100% nguyên bản)", [["Enter"], ["Ctrl", "E"]]),
        ]
        container_layout.addWidget(
            ShortcutCategoryCard("Điểm Cắt & Xuất File", "✂️", cutting_shortcuts, container)
        )

        # Nhóm 3: Công Cụ & Thao Tác Hệ Thống
        tool_shortcuts = [
            ("Chụp ảnh khung hình độ nét gốc (Lưu PNG & chép Clipboard)", [["C"], ["Ctrl", "S"]]),
            ("Xoay video 90° theo chiều kim đồng hồ (Metadata Lossless)", [["Ctrl", "R"]]),
            ("Mở video mới từ máy tính", [["Ctrl", "O"]]),
            ("Hủy tiến trình / Đóng video đang mở", [["Esc"]]),
            ("Bật / Tắt bảng phím tắt này", [["F1"], ["?"]]),
        ]
        container_layout.addWidget(
            ShortcutCategoryCard("Công Cụ, Chụp Ảnh & Tiện Ích", "📸", tool_shortcuts, container)
        )

        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area, stretch=1)

        # 3. Thanh Đáy (Footer): Hướng dẫn nhanh và Nút Đóng
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(4, 4, 4, 0)

        lbl_footer_tip = QLabel("💡 Mẹo: Bấm phím <b>F1</b> hoặc <b>Esc</b> bất kỳ lúc nào để đóng bảng này.", self)
        lbl_footer_tip.setStyleSheet("color: #8b949e; font-size: 12px;")
        lbl_footer_tip.setTextFormat(Qt.TextFormat.RichText)

        btn_close = QPushButton("Đóng (Esc)", self)
        btn_close.setStyleSheet(UNIFIED_BUTTON_STYLE + " QPushButton { min-width: 90px; }")
        btn_close.setFixedHeight(32)
        btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_close.clicked.connect(self.accept)

        footer_layout.addWidget(lbl_footer_tip, stretch=1)
        footer_layout.addWidget(btn_close)
        main_layout.addLayout(footer_layout)

    def keyPressEvent(self, event: QKeyEvent):
        """Bấm Esc hoặc F1 để đóng bảng phím tắt."""
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F1):
            self.accept()
            return
        super().keyPressEvent(event)

