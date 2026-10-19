"""Điểm khởi chạy ứng dụng Lossless Video Cutter."""

from datetime import datetime
import os
from pathlib import Path
import sys

# Đảm bảo thư mục gốc dự án luôn nằm trong sys.path
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def setup_mpv_dll_directory():
    """Cấu hình Windows DLL Loader để nạp mpv-2.dll từ thư mục tools/ hoặc các thư mục dự án."""
    candidates = [
        PROJECT_ROOT / "tools",
        PROJECT_ROOT,
    ]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([
            exe_dir / "tools",
            exe_dir / "_internal",
            exe_dir / "_internal" / "PySide6",
            exe_dir,
        ])
    for d in candidates:
        if d.is_dir():
            d_str = str(d.resolve())
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(d_str)
                except Exception:
                    pass
            if sys.platform == "win32":
                try:
                    import ctypes
                    if (d / "libmpv-2.dll").is_file() or (d / "mpv-2.dll").is_file():
                        ctypes.windll.kernel32.SetDllDirectoryW(d_str)
                except Exception:
                    pass
            cur_path = os.environ.get("PATH", "")
            if d_str not in cur_path:
                os.environ["PATH"] = d_str + os.pathsep + cur_path


def apply_system_stability_protections():
    """Áp dụng các biện pháp bảo vệ ổn định hệ thống và cấu hình backend đa phương tiện tối ưu.

    1. Vô hiệu hóa các hook chèn overlay từ bên thứ ba (NVIDIA ShadowPlay, Discord,
       RTSS, OBS) nhằm ngăn ngừa sự cố xung đột swapchain DirectX và lỗi TDR reset.
    2. Cấu hình Windows DLL loader để nhận diện mpv-2.dll trong thư mục tools/ và các thư mục liên quan.
    3. Thiết lập QT_MEDIA_BACKEND=ffmpeg làm backend dự phòng an toàn khi thiếu thư viện mpv.
    """
    # 1. Cấu hình đường dẫn nạp thư viện DLL cho mpv
    setup_mpv_dll_directory()

    # 2. Thiết lập biến môi trường vô hiệu hóa hook và overlay từ phần mềm bên thứ ba
    overlay_env_vars = {
        "NV_DISABLE_OVERLAY": "1",
        "DISABLE_NV_OVERLAY": "1",
        "GFE_DISABLE_OVERLAY": "1",
        "SP_DISABLE_OVERLAY": "1",
        "DISABLE_OVERLAYS": "1",
        "DISCORD_NO_HOOK": "1",
        "DISABLE_DISCORD_HOOK": "1",
        "OBS_DISABLE_HOOK": "1",
        "RTSS_DISABLE_HOOK": "1",
    }
    for k, v in overlay_env_vars.items():
        if k not in os.environ:
            os.environ[k] = v

    # Luôn ép Qt 6 Multimedia sử dụng backend FFmpeg để hỗ trợ giải mã đa định dạng (AV1, HEVC, VP9...)
    os.environ["QT_MEDIA_BACKEND"] = "ffmpeg"

    # 2. Tự động định vị đường dẫn Qt Plugins và thư viện DLL khi chạy dưới dạng file đóng gói .exe (PyInstaller)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        internal_pyside = exe_dir / "_internal" / "PySide6"
        internal_dir = exe_dir / "_internal"

        # Sử dụng Win32 Kernel32 API để nạp trực tiếp đường dẫn DLL vào Windows DLL Loader
        if sys.platform == "win32":
            import ctypes
            for d in [internal_pyside, internal_dir, exe_dir]:
                if d.is_dir():
                    try:
                        ctypes.windll.kernel32.AddDllDirectory(str(d))
                    except Exception:
                        pass
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(str(d))
                        except Exception:
                            pass
            if internal_pyside.is_dir():
                try:
                    ctypes.windll.kernel32.SetDllDirectoryW(str(internal_pyside))
                except Exception:
                    pass

        candidates = []
        if hasattr(sys, "_MEIPASS"):
            meipass = Path(sys._MEIPASS)
            candidates.extend([
                meipass / "PySide6" / "plugins",
                meipass / "_internal" / "PySide6" / "plugins",
                meipass / "_internal" / "PySide6" / "Qt" / "plugins",
                meipass / "plugins",
            ])
        candidates.extend([
            exe_dir / "plugins",
            exe_dir / "_internal" / "PySide6" / "plugins",
            exe_dir / "_internal" / "PySide6" / "Qt" / "plugins",
            exe_dir / "PySide6" / "plugins",
            exe_dir / "PySide6" / "Qt" / "plugins",
            exe_dir / "_internal" / "plugins",
            exe_dir / "_internal" / "Qt" / "plugins",
        ])

        found_primary = False
        for p_dir in candidates:
            if p_dir.is_dir():
                if not found_primary:
                    os.environ["QT_PLUGIN_PATH"] = str(p_dir)
                    found_primary = True
                try:
                    from PySide6.QtCore import QCoreApplication
                    QCoreApplication.addLibraryPath(str(p_dir))
                except Exception:
                    pass
                pyside_dir = p_dir.parent
                if pyside_dir.is_dir():
                    cur_path = os.environ.get("PATH", "")
                    if str(pyside_dir) not in cur_path:
                        os.environ["PATH"] = str(pyside_dir) + os.pathsep + cur_path

    # 3. Đặt Windows AppUserModelID để ghim taskbar và đồng bộ danh tính icon ứng dụng
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "antigravity.losslesscutvideo.1.0"
            )
        except Exception:
            pass


def setup_exception_handler():
    """Thiết lập bộ bắt ngoại lệ toàn cục để ghi log lỗi hệ thống ổn định."""

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        import traceback

        err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        print(f"[CutVideo Unhandled Exception]\n{err_msg}", file=sys.stderr)
        try:
            log_dir = PROJECT_ROOT / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "app_error.log"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n--- {datetime.now().isoformat()} ---\n{err_msg}\n")
        except Exception:
            pass

    sys.excepthook = handle_exception


# Áp dụng các biện pháp bảo vệ ổn định hệ thống trước khi nạp module đồ họa GUI
apply_system_stability_protections()
setup_exception_handler()

from PySide6.QtWidgets import QApplication
from src.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Lossless Video Cutter")
    app.setOrganizationName("Antigravity")

    # Cài đặt biểu tượng ứng dụng (áp dụng cho taskbar, thanh tiêu đề và hộp thoại)
    from src.core.config import get_app_icon_path
    from PySide6.QtGui import QIcon

    icon_path = get_app_icon_path()
    if icon_path and icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    if icon_path and icon_path.is_file():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
