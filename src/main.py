"""Entry point for Lossless Video Cutter application."""

from datetime import datetime
import os
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def apply_system_stability_protections():
    """Apply stability protections and configure optimal multimedia backends.

    1. Disables third-party overlay injection hooks (NVIDIA ShadowPlay, Discord,
       RTSS, OBS) to prevent DirectX swapchain hooking crashes and TDR resets.
    2. Enforces QT_MEDIA_BACKEND=ffmpeg so PySide6 QMediaPlayer can natively decode
       all modern formats (AV1, HEVC, VP9, H.264, AAC, Opus, etc.) without relying on
       Windows Media Foundation (WMF) which fails on AV1/MKV with error 0x80004001.
    """
    # 1. Environment flags to disable third-party hooks and overlays cooperatively
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

    # Always enforce FFmpeg backend for Qt 6 Multimedia to support AV1, HEVC, VP9, etc.
    os.environ["QT_MEDIA_BACKEND"] = "ffmpeg"

    # Disable buggy D3D11VA/DXVA2 GPU hardware surface mapping in Qt 6 FFmpeg backend.
    # Forces Qt to use FFmpeg's robust multi-threaded software decoder (libdav1d),
    # eliminating the black screen bug on AV1/HEVC videos across all GPUs.
    os.environ["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"] = ""

    # 2. Set Windows AppUserModelID for taskbar pinning and identity isolation
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "antigravity.losslesscutvideo.1.0"
            )
        except Exception:
            pass


def setup_exception_handler():
    """Set up global unhandled exception handler to log errors gracefully."""

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


# Apply stability protections before any GUI or graphics modules are loaded
apply_system_stability_protections()
setup_exception_handler()

from PySide6.QtWidgets import QApplication
from src.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Lossless Video Cutter")
    app.setOrganizationName("Antigravity")

    # Set application icon (affects taskbar, window title, dialogs)
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
