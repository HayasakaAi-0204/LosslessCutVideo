"""Module quản lý cấu hình cho ứng dụng CutVideo.

Quản lý đường dẫn tới các công cụ portable (ffmpeg, ffprobe) và thiết lập ứng dụng.
"""

import os
from pathlib import Path
import shutil
import sys


def get_project_root() -> Path:
    """Trả về đường dẫn tuyệt đối tới thư mục gốc của dự án."""
    if getattr(sys, "frozen", False):
        # Đang chạy dưới dạng file thực thi đóng gói bằng PyInstaller (.exe)
        return Path(sys.executable).resolve().parent
    # src/core/config.py -> src/core -> src -> thư mục gốc dự án
    return Path(__file__).resolve().parent.parent.parent


def get_tools_dir() -> Path:
    """Trả về đường dẫn tới thư mục tools chứa các file thực thi portable."""
    # 1. Kiểm tra thư mục tạm của PyInstaller (_MEIPASS) nếu đóng gói bằng cờ --add-data
    if hasattr(sys, "_MEIPASS"):
        meipass_tools = Path(sys._MEIPASS) / "tools"
        if meipass_tools.is_dir():
            return meipass_tools

    # 2. Kiểm tra thư mục tools/ nằm cạnh file .exe hoặc trong thư mục gốc dự án
    tools_dir = get_project_root() / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    return tools_dir


def get_ffmpeg_path() -> Path:
    """Trả về đường dẫn tới file thực thi ffmpeg.
    
    Ưu tiên sử dụng tools/ffmpeg.exe nội bộ trong dự án theo quy định GEMINI.md.
    Tự động dự phòng sang ffmpeg hệ thống nếu không tìm thấy trong tools/.
    """
    tools_ffmpeg = get_tools_dir() / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if tools_ffmpeg.is_file():
        return tools_ffmpeg
    
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return Path(system_ffmpeg)
    
    return tools_ffmpeg


def get_ffprobe_path() -> Path:
    """Trả về đường dẫn tới file thực thi ffprobe.
    
    Ưu tiên sử dụng tools/ffprobe.exe nội bộ trong dự án theo quy định GEMINI.md.
    Tự động dự phòng sang ffprobe hệ thống nếu không tìm thấy trong tools/.
    """
    tools_ffprobe = get_tools_dir() / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    if tools_ffprobe.is_file():
        return tools_ffprobe
    
    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        return Path(system_ffprobe)
    
    return tools_ffprobe


def get_mpv_path() -> Path:
    """Trả về đường dẫn tới file thư viện mpv-2.dll hoặc libmpv-2.dll.

    Ưu tiên tìm trong thư mục tools/ nội bộ của dự án.
    Nếu không có, kiểm tra các biến thể tên gọi phổ biến.
    """
    tools_dir = get_tools_dir()
    candidates = (
        "mpv-2.dll",
        "libmpv-2.dll",
        "mpv-1.dll",
        "libmpv.so",
        "libmpv.dylib",
    )
    for name in candidates:
        p = tools_dir / name
        if p.is_file():
            return p

    # Kiểm tra thêm tại thư mục gốc dự án hoặc thư mục _internal (khi đóng gói exe)
    root_dir = get_project_root()
    for name in candidates:
        p = root_dir / name
        if p.is_file():
            return p
        p_int = root_dir / "_internal" / name
        if p_int.is_file():
            return p_int

    return tools_dir / ("mpv-2.dll" if sys.platform == "win32" else "libmpv.so")


def has_mpv() -> bool:
    """Kiểm tra xem thư viện mpv đã sẵn sàng hay chưa."""
    return get_mpv_path().is_file()


def validate_tools() -> dict[str, bool]:
    """Kiểm tra tính sẵn sàng của ffmpeg, ffprobe và mpv.
    
    Returns:
        dict chứa trạng thái boolean cho 'ffmpeg', 'ffprobe' và 'mpv'.
    """
    ffmpeg_p = get_ffmpeg_path()
    ffprobe_p = get_ffprobe_path()
    return {
        "ffmpeg": ffmpeg_p.is_file(),
        "ffprobe": ffprobe_p.is_file(),
        "mpv": has_mpv(),
    }


def get_assets_dir() -> Path:
    """Trả về đường dẫn tới thư mục assets chứa icon và tài nguyên đồ họa."""
    if hasattr(sys, "_MEIPASS"):
        meipass_assets = Path(sys._MEIPASS) / "assets"
        if meipass_assets.is_dir():
            return meipass_assets
    assets_dir = get_project_root() / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    return assets_dir


def get_app_icon_path() -> Path:
    """Trả về đường dẫn tới biểu tượng ứng dụng (.ico hoặc .png)."""
    from src.core.icon_utils import ensure_app_icons

    ico_path, png_path = ensure_app_icons()
    if sys.platform == "win32" and ico_path and ico_path.is_file():
        return ico_path
    if png_path and png_path.is_file():
        return png_path

    assets = get_assets_dir()
    for ext in (".ico", ".png"):
        p = assets / f"icon{ext}"
        if p.is_file():
            return p
    return assets / "icon.png"


def has_hardware_av1_decode() -> bool:
    """Kiểm tra xem phần cứng GPU của hệ thống hiện tại có hỗ trợ giải mã phần cứng video AV1 hay không.

    Hỗ trợ giải mã phần cứng AV1 bản địa:
    - NVIDIA: Thế hệ RTX 30 series, RTX 40 series, RTX 50 series (RTX 3050+, 4060+, Ampere/Ada Lovelace...).
      Lưu ý: RTX 20 series (như RTX 2070 Super), GTX 16 series, GTX 10 series KHÔNG có chip giải mã phần cứng AV1.
    - Intel: Intel Iris Xe (thế hệ 11 Tiger Lake trở lên), Intel Arc Alchemist/Battlemage, Intel Core Ultra.
      Lưu ý: Intel UHD 630 / thế hệ 10 Comet Lake trở xuống KHÔNG hỗ trợ AV1 phần cứng.
    - AMD: Kiến trúc RDNA2 trở lên (Radeon RX 6600 trở lên, RX 7000 series).

    Trả về:
        True nếu GPU hỗ trợ giải mã phần cứng AV1, False nếu GPU cũ cần giải mã bằng CPU an toàn (libdav1d).
    """
    if sys.platform != "win32":
        return True

    try:
        import winreg

        key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        gpu_names: list[str] = []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as base_key:
            num_subkeys = winreg.QueryInfoKey(base_key)[0]
            for i in range(min(num_subkeys, 12)):
                sub_name = winreg.EnumKey(base_key, i)
                try:
                    with winreg.OpenKey(base_key, sub_name) as sub_key:
                        desc, _ = winreg.QueryValueEx(sub_key, "DriverDesc")
                        if desc:
                            gpu_names.append(str(desc).strip().lower())
                except Exception:
                    continue

        if not gpu_names:
            return True

        has_capable_gpu = False
        for g in gpu_names:
            # Kiểm tra card NVIDIA
            if "nvidia" in g or "geforce" in g:
                # RTX 30xx, 40xx, 50xx, RTX A series mới
                for kw in ["rtx 30", "rtx 40", "rtx 50", "a2000", "a4000", "a5000", "a6000"]:
                    if kw in g:
                        has_capable_gpu = True
                        break
                # Các dòng cũ như RTX 2060, RTX 2070, RTX 2080, GTX... không hỗ trợ AV1
                continue

            # Kiểm tra card Intel
            if "intel" in g:
                if any(kw in g for kw in ["iris xe", "arc", "ultra", "xe graphics"]):
                    has_capable_gpu = True
                    break
                continue

            # Kiểm tra card AMD
            if "amd" in g or "radeon" in g:
                if any(kw in g for kw in ["rx 6", "rx 7", "radeon 7", "radeon 8"]):
                    has_capable_gpu = True
                    break
                continue

        return has_capable_gpu
    except Exception:
        # Nếu không truy vấn được Registry, mặc định coi như hỗ trợ để thử nghiệm trước
        return True

