"""Điểm khởi chạy nhanh cho ứng dụng CutVideo từ thư mục gốc."""

import sys
from pathlib import Path

# Đảm bảo thư mục gốc của dự án luôn nằm trong sys.path
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 1. Ghi log khởi động để kiểm tra và chẩn đoán
log_dir = PROJECT_ROOT / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
launch_log_file = log_dir / "launch.log"
try:
    from datetime import datetime
    with open(launch_log_file, "w", encoding="utf-8") as f:
        f.write(f"=== CutVideo Launch at {datetime.now().isoformat()} ===\n")
        f.write(f"Python Executable: {sys.executable}\n")
        f.write(f"Python Version: {sys.version}\n")
except Exception:
    pass

# 2. Kiểm tra thư viện PySide6 trước khi khởi chạy
try:
    import PySide6
    try:
        with open(launch_log_file, "a", encoding="utf-8") as f:
            f.write(f"PySide6 Version: {getattr(PySide6, '__version__', 'unknown')}\n")
    except Exception:
        pass
except ImportError:
    print("[*] Phat hien chua cai dat thu vien do hoa PySide6.")
    req_file = PROJECT_ROOT / "requirements.txt"
    if req_file.is_file():
        import subprocess
        print("[*] Dang tu dong cai dat cac thu vien can thiet tu requirements.txt...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_file)])
            print("[*] Cai dat thu vien thanh cong! Dang khoi dong ung dung...")
        except Exception as e:
            err_text = f"[!] Loi khi cai dat thu vien: {e}"
            print(err_text)
            print("[!] Vui long kiem tra ket noi mang va thu lai.")
            try:
                with open(launch_log_file, "a", encoding="utf-8") as f:
                    f.write(f"\n{err_text}\n")
            except Exception:
                pass
            input("\nNhan phim Enter de thoat...")
            sys.exit(1)

# 3. Khởi chạy ứng dụng chính với bộ bắt lỗi toàn diện
try:
    from src.main import apply_system_stability_protections, main
    try:
        with open(launch_log_file, "a", encoding="utf-8") as f:
            f.write("Imported src.main successfully. Starting application...\n")
    except Exception:
        pass

    if __name__ == "__main__":
        apply_system_stability_protections()
        main()
except Exception as e:
    import traceback
    err_msg = traceback.format_exc()
    try:
        with open(launch_log_file, "a", encoding="utf-8") as f:
            f.write(f"\n[FATAL STARTUP ERROR]\n{err_msg}\n")
    except Exception:
        pass
    print("\n" + "=" * 60)
    print("[LOI KHOI DONG UNG DUNG]")
    print(err_msg)
    print("=" * 60)
    input("\nNhan Enter de thoat...")
    sys.exit(1)

