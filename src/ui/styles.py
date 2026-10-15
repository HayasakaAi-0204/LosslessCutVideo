"""Unified Dark Theme Styling & Design System for Lossless Video Cutter."""

# -----------------------------------------------------------------------------
# Color Palette Constants
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
# 1. Standard Unified Action Button
# (Used across Player controls, Tools, Snapshot, Rotate, Zoom Fit, Open File)
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
# 2. Unified Compact / Icon Stepper Button
# (Used for Speed ➖/➕ and Zoom ➖/➕ buttons)
# -----------------------------------------------------------------------------
UNIFIED_ICON_BUTTON_STYLE = """
QPushButton {
    background-color: #252a34;
    color: #e2e8f0;
    font-size: 12px;
    font-weight: bold;
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
# 3. In & Out Point Buttons
# (Unified base geometry with subtle emerald / crimson identity)
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
# 4. Cancel / Close Button
# (Unified base geometry with soft crimson warning hover)
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
# 5. Hero Export Button (Special CapCut Blue - Preserved uniquely per user request)
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
# 6. Global Window Stylesheet (Ensures full default consistency for unstyled buttons)
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

