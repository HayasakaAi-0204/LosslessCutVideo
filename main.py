"""Điểm khởi chạy nhanh cho ứng dụng CutVideo từ thư mục gốc."""

import sys
from pathlib import Path

# Đảm bảo thư mục gốc của dự án luôn nằm trong sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main import apply_system_stability_protections, main

if __name__ == "__main__":
    apply_system_stability_protections()
    main()

