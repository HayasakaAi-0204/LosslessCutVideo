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

    Nguyên tắc Fail-Safe (An toàn là trên hết):
    - Mặc định trả về False nếu có bất kỳ nghi ngờ, lỗi truy vấn, hoặc phát hiện GPU tích hợp đời cũ (Intel UHD/HD).
    - Chỉ trả về True khi phát hiện chắc chắn 100% GPU thuộc danh sách hỗ trợ phần cứng AV1 và không bị nghẽn bởi iGPU cũ.

    Hỗ trợ giải mã phần cứng AV1 bản địa (Native ASIC decode):
    - NVIDIA: Thế hệ RTX 30 series, RTX 40 series, RTX 50 series (Ampere/Ada Lovelace: RTX 3050+, 4060+...).
      Lưu ý: RTX 20 series, GTX 16 series, GTX 10 series, MX series KHÔNG có chip giải mã phần cứng AV1.
    - Intel: Intel Iris Xe (thế hệ 11 Tiger Lake trở lên), Intel Arc Alchemist/Battlemage, Intel Core Ultra.
      Lưu ý: Intel UHD 630 / 620 / HD Graphics thế hệ 10 Comet Lake trở xuống KHÔNG hỗ trợ AV1 phần cứng.
    - AMD: Kiến trúc RDNA2 trở lên (Radeon RX 6000 series trở lên, RX 7000 series, Radeon 700M/800M).

    Trả về:
        True nếu GPU hỗ trợ giải mã phần cứng AV1 chắc chắn, False nếu GPU cũ cần giải mã bằng CPU an toàn (libdav1d).
    """
    if sys.platform != "win32":
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
                            gpu_names.append(str(desc).strip().lower())
                except Exception:
                    continue

        if not gpu_names:
            return False

        # Kiểm tra trường hợp Laptop Optimus card kép:
        # Nếu có Card Onboard Intel đời cũ (Intel UHD 620, UHD 630, HD Graphics),
        # màn hình laptop nối trực tiếp vào iGPU này. Direct3D 11 trên Windows sẽ route qua iGPU và gây crash TDR 2s!
        has_old_intel_igpu = any(
            ("uhd graphics" in g or "hd graphics" in g or "iris plus" in g or "iris pro" in g)
            for g in gpu_names
        )
        if has_old_intel_igpu:
            return False

        has_capable_gpu = False
        for g in gpu_names:
            # 1. Card NVIDIA: Phải là RTX 30, 40, 50 hoặc RTX Professional A2000+
            if "nvidia" in g or "geforce" in g:
                if any(old_kw in g for old_kw in ["gtx", "rtx 20", "gt ", "mx", "quadro"]):
                    continue
                for kw in ["rtx 30", "rtx 40", "rtx 50", "a2000", "a4000", "a5000", "a6000", "rtx a"]:
                    if kw in g:
                        has_capable_gpu = True
                        break

            # 2. Card Intel: Phải là Iris Xe, Arc, hoặc Core Ultra
            elif "intel" in g:
                if any(kw in g for kw in ["iris xe", "arc", "ultra", "xe graphics"]):
                    has_capable_gpu = True
                    break

            # 3. Card AMD: Phải là RX 6000+, 7000+, Radeon 700M/800M
            elif "amd" in g or "radeon" in g:
                if any(kw in g for kw in ["rx 6", "rx 7", "radeon 7", "radeon 8", "rdna"]):
                    has_capable_gpu = True
                    break

        return has_capable_gpu
    except Exception:
        # Nguyên tắc Fail-Safe: Có lỗi hoặc không xác định được thì trả về False để chạy CPU an toàn
        return False


