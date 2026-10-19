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
    exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"

    # 1. Ưu tiên thư mục tools/ nằm cạnh file .exe hoặc trong thư mục gốc dự án
    root_tools = get_project_root() / "tools"
    if root_tools.is_dir() and (root_tools / exe_name).is_file():
        return root_tools

    # 2. Kiểm tra thư mục tạm của PyInstaller (_MEIPASS) nếu đóng gói bằng cờ --add-data
    if hasattr(sys, "_MEIPASS"):
        meipass_tools = Path(sys._MEIPASS) / "tools"
        if meipass_tools.is_dir() and (meipass_tools / exe_name).is_file():
            return meipass_tools

    root_tools.mkdir(parents=True, exist_ok=True)
    return root_tools


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


def is_gpu_av1_capable(name: str) -> bool:
    """Kiểm tra một tên card đồ họa cụ thể có chip giải mã phần cứng AV1 hay không."""
    g = name.strip().lower()

    # 1. Card NVIDIA: Phải là RTX 30, RTX 40, RTX 50 hoặc dòng máy trạm Ada/Ampere
    if "nvidia" in g or "geforce" in g:
        if any(bad in g for bad in ["gtx", "rtx 20", "gt ", "mx", "quadro"]):
            return False
        if any(good in g for good in ["rtx 30", "rtx 40", "rtx 50", "a2000", "a3000", "a4000", "a5000", "a6000", "rtx a"]):
            return True
        return False

    # 2. Card Intel:
    if "intel" in g:
        # Intel Arc (A310, A380, A580, A750, A770, Arc 130V, Arc 140V...)
        if "arc" in g:
            return True
        # Intel Core Ultra
        if "ultra" in g:
            return True
        # Intel Iris Xe
        if "iris xe" in g or "xe graphics" in g:
            return True
        # Intel UHD Graphics thế hệ 11 trở lên có chip AV1: UHD 730, 750, 770
        if any(uhd in g for uhd in ["730", "750", "770"]):
            return True
        return False

    # 3. Card AMD:
    if "amd" in g or "radeon" in g:
        if any(bad in g for bad in ["rx 5", "rx 4", "vega", "r9", "r7", "r5"]):
            return False
        if any(good in g for good in ["rx 6", "rx 7", "rx 8", "radeon 7", "radeon 8", "rdna", "680m", "780m", "760m", "880m", "890m"]):
            return True
        return False

    return False


_AV1_DECODE_CAPABLE_CACHE: bool | None = None


def has_hardware_av1_decode() -> bool:
    """Kiểm tra xem phần cứng GPU của hệ thống hiện tại có hỗ trợ giải mã phần cứng video AV1 hay không.

    Hỗ trợ giải mã phần cứng AV1 bản địa (Native ASIC decode):
    - NVIDIA: Thế hệ RTX 30 series, RTX 40 series, RTX 50 series (RTX 3050+, 4060+...).
    - Intel: Intel Iris Xe (thế hệ 11 Tiger Lake trở lên), Intel Arc, Intel Core Ultra, Intel UHD 730/750/770.
    - AMD: Kiến trúc RDNA2 trở lên (Radeon RX 6000 series trở lên, RX 7000 series, Radeon 700M/800M).

    Trả về:
        True nếu trong máy có ít nhất một GPU hỗ trợ giải mã phần cứng AV1, False nếu toàn bộ GPU đều là dòng cũ.
    """
    global _AV1_DECODE_CAPABLE_CACHE
    if _AV1_DECODE_CAPABLE_CACHE is not None:
        return _AV1_DECODE_CAPABLE_CACHE

    if sys.platform != "win32":
        _AV1_DECODE_CAPABLE_CACHE = True
        return True

    try:
        import winreg

        key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        gpu_names: list[str] = []
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as base_key:
            num_subkeys = winreg.QueryInfoKey(base_key)[0]
            for i in range(min(num_subkeys, 16)):
                sub_name = winreg.EnumKey(base_key, i)
                try:
                    with winreg.OpenKey(base_key, sub_name) as sub_key:
                        desc, _ = winreg.QueryValueEx(sub_key, "DriverDesc")
                        if desc:
                            gpu_names.append(str(desc).strip())
                except Exception:
                    continue

        if not gpu_names:
            _AV1_DECODE_CAPABLE_CACHE = True
            return True

        # Nếu có ít nhất 1 GPU trên máy tính hỗ trợ giải mã AV1 phần cứng
        _AV1_DECODE_CAPABLE_CACHE = any(is_gpu_av1_capable(name) for name in gpu_names)
        return _AV1_DECODE_CAPABLE_CACHE
    except Exception:
        _AV1_DECODE_CAPABLE_CACHE = True
        return True


