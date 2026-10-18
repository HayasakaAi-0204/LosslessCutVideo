"""Hệ thống giao diện Dark Theme đồng nhất cho ứng dụng Lossless Video Cutter."""

# -----------------------------------------------------------------------------
# Hằng số bảng màu giao diện
# -----------------------------------------------------------------------------
COLOR_BG_BASE = "#16181d"
COLOR_BG_CARD = "#1e222b"
COLOR_BG_BUTTON = "#252a34"
COLOR_BG_BUTTON_HOVER = "#2f3644"
COLOR_BG_BUTTON_PRESSED = "#1c2028"
COLOR_BG_BUTTON_DISABLED = "#1a1e26"

COLOR_BORDER_BUTTON = "#3b4252"
COLOR_BORDER_HOVER = "#00d2d3"
COLOR_BORDER_DISABLED = "#262c37"

COLOR_TEXT_MAIN = "#e2e8f0"
COLOR_TEXT_HOVER = "#00d2d3"
COLOR_TEXT_DISABLED = "#555e6d"

# -----------------------------------------------------------------------------
# 1. Nút bấm thao tác chuẩn đồng nhất
# (Dùng cho Điều khiển Player, Công cụ, Snapshot, Xoay, Zoom Fit, Mở File)
# -----------------------------------------------------------------------------
UNIFIED_BUTTON_STYLE = """
QPushButton {
    background-color: #252a34;
    color: #e2e8f0;
    font-weight: bold;
    font-size: 12px;
    padding: 4px 12px;
    border-radius: 5px;
    border: 1px solid #3b4252;
}
QPushButton:hover {
    background-color: #2f3644;
    color: #00d2d3;
    border-color: #00d2d3;
}
QPushButton:pressed {
    background-color: #1c2028;
    color: #00b4b5;
    border-color: #00b4b5;
}
QPushButton:disabled {
    background-color: #1a1e26;
    color: #555e6d;
    border-color: #262c37;
}
"""

# -----------------------------------------------------------------------------
# 2. Nút bấm icon thu gọn / Bộ tăng giảm bước
# (Dùng cho Tốc độ ➖/➕ và Thu phóng ➖/➕)
# -----------------------------------------------------------------------------
UNIFIED_ICON_BUTTON_STYLE = """
QPushButton {
    background-color: #252a34;
    color: #e2e8f0;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 16px;
    font-weight: bold;
    padding: 0px;
    margin: 0px;
    text-align: center;
    border-radius: 5px;
    border: 1px solid #3b4252;
}
QPushButton:hover {
    background-color: #2f3644;
    color: #00d2d3;
    border-color: #00d2d3;
}
QPushButton:pressed {
    background-color: #1c2028;
    color: #00b4b5;
    border-color: #00b4b5;
}
QPushButton:disabled {
    background-color: #1a1e26;
    color: #555e6d;
    border-color: #262c37;
}
"""

# -----------------------------------------------------------------------------
# 3. Nút bấm đặt mốc In & Out
# (Đồng nhất kích thước với điểm nhấn màu ngọc lục bảo / đỏ thẫm)
# -----------------------------------------------------------------------------
BUTTON_SET_IN_STYLE = """
QPushButton {
    background-color: #252a34;
    color: #e2e8f0;
    font-weight: bold;
    font-size: 12px;
    padding: 4px 12px;
    border-radius: 5px;
    border: 1px solid #3b4252;
}
QPushButton:hover {
    background-color: #2f3644;
    color: #2ecc71;
    border-color: #2ecc71;
}
QPushButton:pressed {
    background-color: #1c2028;
    color: #27ae60;
    border-color: #27ae60;
}
QPushButton:disabled {
    background-color: #1a1e26;
    color: #555e6d;
    border-color: #262c37;
}
"""

BUTTON_SET_OUT_STYLE = """
QPushButton {
    background-color: #252a34;
    color: #e2e8f0;
    font-weight: bold;
    font-size: 12px;
    padding: 4px 12px;
    border-radius: 5px;
    border: 1px solid #3b4252;
}
QPushButton:hover {
    background-color: #2f3644;
    color: #e74c3c;
    border-color: #e74c3c;
}
QPushButton:pressed {
    background-color: #1c2028;
    color: #c0392b;
    border-color: #c0392b;
}
QPushButton:disabled {
    background-color: #1a1e26;
    color: #555e6d;
    border-color: #262c37;
}
"""

# -----------------------------------------------------------------------------
# 4. Nút Hủy / Đóng
# (Đồng nhất kích thước với hiệu ứng cảnh báo màu đỏ nhẹ khi hover)
# -----------------------------------------------------------------------------
BUTTON_CANCEL_STYLE = """
QPushButton {
    background-color: #252a34;
    color: #e2e8f0;
    font-weight: bold;
    font-size: 12px;
    padding: 5px 14px;
    border-radius: 5px;
    border: 1px solid #3b4252;
}
QPushButton:hover {
    background-color: #e74c3c;
    color: #ffffff;
    border-color: #c0392b;
}
QPushButton:pressed {
    background-color: #c0392b;
    color: #ffffff;
    border-color: #962d22;
}
QPushButton:disabled {
    background-color: #1a1e26;
    color: #555e6d;
    border-color: #262c37;
}
"""

# -----------------------------------------------------------------------------
# 5. Nút bấm Xuất Video nổi bật (Màu xanh dương phong cách CapCut đặc trưng)
# -----------------------------------------------------------------------------
BUTTON_EXPORT_STYLE = """
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
QPushButton:pressed {
    background-color: #0052a3;
}
QPushButton:disabled {
    background-color: #3a3f4b;
    color: #718096;
}
"""

# -----------------------------------------------------------------------------
# 6. Stylesheet toàn cục ứng dụng (Đảm bảo độ đồng nhất cho mọi widget)
# -----------------------------------------------------------------------------
GLOBAL_APP_QSS = f"""
QMainWindow {{
    background-color: {COLOR_BG_BASE};
}}

QPushButton {{
    background-color: #252a34;
    color: #e2e8f0;
    font-weight: bold;
    font-size: 12px;
    padding: 4px 12px;
    border-radius: 5px;
    border: 1px solid #3b4252;
}}
QPushButton:hover {{
    background-color: #2f3644;
    color: #00d2d3;
    border-color: #00d2d3;
}}
QPushButton:pressed {{
    background-color: #1c2028;
    color: #00b4b5;
    border-color: #00b4b5;
}}
QPushButton:disabled {{
    background-color: #1a1e26;
    color: #555e6d;
    border-color: #262c37;
}}

QToolTip {{
    background-color: #1e222b;
    color: #e2e8f0;
    border: 1px solid #3b4252;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}}
"""

# -----------------------------------------------------------------------------
# 7. Nút trạng thái giải mã H/W (GPU) và S/W (CPU) phong cách PotPlayer
# -----------------------------------------------------------------------------
BUTTON_HW_STYLE = """
QPushButton {
    background-color: #252a34;
    color: #f1c40f;
    font-family: 'Segoe UI', monospace;
    font-weight: bold;
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 5px;
    border: 1px solid #f1c40f;
}
QPushButton:hover {
    background-color: #2f3644;
    color: #f39c12;
    border-color: #f39c12;
}
QPushButton:pressed {
    background-color: #1c2028;
    color: #d68910;
    border-color: #d68910;
}
QPushButton:disabled {
    background-color: #1a1e26;
    color: #555e6d;
    border-color: #262c37;
}
"""

BUTTON_SW_STYLE = """
QPushButton {
    background-color: #252a34;
    color: #00d2d3;
    font-family: 'Segoe UI', monospace;
    font-weight: bold;
    font-size: 11px;
    padding: 3px 8px;
    border-radius: 5px;
    border: 1px solid #00d2d3;
}
QPushButton:hover {
    background-color: #2f3644;
    color: #00ffff;
    border-color: #00ffff;
}
QPushButton:pressed {
    background-color: #1c2028;
    color: #00b4b5;
    border-color: #00b4b5;
}
QPushButton:disabled {
    background-color: #1a1e26;
    color: #555e6d;
    border-color: #262c37;
}
"""


