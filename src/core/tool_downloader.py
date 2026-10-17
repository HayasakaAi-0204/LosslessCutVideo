"""Bộ tải và giải nén tự động cho các tệp thực thi FFmpeg & FFprobe portable.

Tải các bản dựng tĩnh Windows chính thức và giải nén ffmpeg.exe và ffprobe.exe
trực tiếp vào thư mục tools/ của dự án.
"""

from pathlib import Path
import shutil
import ssl
import sys
import urllib.request
import zipfile
from typing import Callable, Optional

# Các máy chủ tải về đáng tin cậy cho bản dựng FFmpeg 64-bit Windows tĩnh
FFMPEG_WINDOWS_URLS = [
    # Bản phát hành GitHub của yt-dlp (nhanh, CDN ổn định, đầy đủ tính năng GPL)
    "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    # Bản phát hành chính thức gyan.dev essentials do ffmpeg.org khuyên dùng
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
]


def acquire_tools_from_system(target_dir: Path) -> dict[str, bool]:
    """Kiểm tra xem ffmpeg/ffprobe có trong PATH hệ thống không và sao chép vào target_dir.

    Trả về:
        dict chứa trạng thái boolean cho 'ffmpeg' và 'ffprobe'.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_dest = target_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    ffprobe_dest = target_dir / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")

    if not ffmpeg_dest.is_file():
        sys_ffmpeg = shutil.which("ffmpeg")
        if sys_ffmpeg:
            try:
                shutil.copy2(sys_ffmpeg, ffmpeg_dest)
            except Exception:
                pass

    if not ffprobe_dest.is_file():
        sys_ffprobe = shutil.which("ffprobe")
        if sys_ffprobe:
            try:
                shutil.copy2(sys_ffprobe, ffprobe_dest)
            except Exception:
                pass

    return {
        "ffmpeg": ffmpeg_dest.is_file() and ffmpeg_dest.stat().st_size > 1024 * 1024,
        "ffprobe": ffprobe_dest.is_file() and ffprobe_dest.stat().st_size > 1024 * 1024,
    }


def download_and_extract_tools(
    target_dir: Path,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> bool:
    """Tải tệp nén FFmpeg/FFprobe portable và giải nén các tệp thực thi vào target_dir.

    Tham số:
        target_dir: Thư mục chứa ffmpeg.exe và ffprobe.exe.
        progress_callback: Hàm gọi tùy chọn callable(percent: int, status_text: str).
        cancel_check: Hàm gọi tùy chọn trả về True nếu cần hủy tải.

    Trả về:
        True nếu cả ffmpeg và ffprobe được đưa vào target_dir thành công.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_dest = target_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    ffprobe_dest = target_dir / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")

    # 1. Đầu tiên, kiểm tra xem đã tồn tại và hợp lệ trong target_dir chưa
    if ffmpeg_dest.is_file() and ffprobe_dest.is_file():
        if ffmpeg_dest.stat().st_size > 1024 * 1024 and ffprobe_dest.stat().st_size > 1024 * 1024:
            if progress_callback:
                progress_callback(100, "Công cụ FFmpeg & FFprobe đã sẵn sàng trong tools/.")
            return True

    # 2. Thử sao chép từ PATH hệ thống nếu có sẵn
    sys_status = acquire_tools_from_system(target_dir)
    if sys_status["ffmpeg"] and sys_status["ffprobe"]:
        if progress_callback:
            progress_callback(100, "Đã sao chép công cụ từ hệ thống vào thư mục tools.")
        return True

    # 3. Tải từ các máy chủ dự phòng (mirrors)
    ssl_context = ssl.create_default_context()
    try:
        import certifi
        ssl_context.load_verify_locations(cafile=certifi.where())
    except Exception:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    last_error = None
    for url in FFMPEG_WINDOWS_URLS:
        if cancel_check and cancel_check():
            return False

        server_name = url.split("/")[2]
        if progress_callback:
            progress_callback(5, f"Đang kết nối tới máy chủ tải FFmpeg ({server_name})...")

        temp_zip = target_dir / "ffmpeg_download_temp.zip"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, context=ssl_context, timeout=30) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                block_size = 1024 * 256  # Từng khối 256 KB

                with open(temp_zip, "wb") as out_file:
                    while True:
                        if cancel_check and cancel_check():
                            out_file.close()
                            if temp_zip.is_file():
                                temp_zip.unlink(missing_ok=True)
                            return False

                        chunk = resp.read(block_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback:
                            if total_size > 0:
                                percent = min(90, 5 + int((downloaded / total_size) * 85))
                                mb_down = downloaded / (1024 * 1024)
                                mb_total = total_size / (1024 * 1024)
                                progress_callback(
                                    percent,
                                    f"Đang tải FFmpeg ({server_name}): {mb_down:.1f} MB / {mb_total:.1f} MB ({percent}%)"
                                )
                            else:
                                mb_down = downloaded / (1024 * 1024)
                                progress_callback(40, f"Đang tải FFmpeg: {mb_down:.1f} MB...")

            # Giải nén ffmpeg.exe và ffprobe.exe từ tệp zip
            if progress_callback:
                progress_callback(92, "Đang giải nén ffmpeg.exe và ffprobe.exe...")

            with zipfile.ZipFile(temp_zip, "r") as zf:
                for member in zf.namelist():
                    name_lower = member.lower()
                    if name_lower.endswith("/ffmpeg.exe") or name_lower == "ffmpeg.exe":
                        with zf.open(member) as src, open(ffmpeg_dest, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                    elif name_lower.endswith("/ffprobe.exe") or name_lower == "ffprobe.exe":
                        with zf.open(member) as src, open(ffprobe_dest, "wb") as dst:
                            shutil.copyfileobj(src, dst)

            # Dọn dẹp tệp zip tạm thời
            if temp_zip.is_file():
                temp_zip.unlink(missing_ok=True)

            if ffmpeg_dest.is_file() and ffprobe_dest.is_file():
                if ffmpeg_dest.stat().st_size > 1024 * 1024 and ffprobe_dest.stat().st_size > 1024 * 1024:
                    if progress_callback:
                        progress_callback(100, "Đã cài đặt thành công FFmpeg và FFprobe!")
                    return True
        except Exception as e:
            last_error = e
            if temp_zip.is_file():
                try:
                    temp_zip.unlink(missing_ok=True)
                except Exception:
                    pass
            continue

    if progress_callback:
        progress_callback(0, f"Không thể tải tự động FFmpeg: {last_error}")
    return False


MPV_WINDOWS_URLS = [
    # Gói libmpv x86_64 chính thức từ shinchiro / zhongfly
    "https://github.com/zhongfly/mpv-winbuild/releases/download/2024-03-31-01f6ec0/mpv-dev-x86_64-20240331-git-01f6ec0.7z",
    "https://sourceforge.net/projects/mpv-player-windows/files/libmpv/mpv-dev-x86_64-latest.7z/download",
]


def acquire_mpv_from_system(target_dir: Path) -> bool:
    """Tìm mpv-2.dll hoặc libmpv-2.dll từ hệ thống (PATH, scoop, chocolatey) và sao chép vào target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)
    mpv_dest = target_dir / ("mpv-2.dll" if sys.platform == "win32" else "libmpv.so")
    if mpv_dest.is_file() and mpv_dest.stat().st_size > 512 * 1024:
        return True

    search_names = ["mpv-2.dll", "libmpv-2.dll", "mpv-1.dll", "libmpv.so"]
    import os
    search_dirs = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        Path(os.environ.get("USERPROFILE", "")) / "scoop" / "apps" / "mpv" / "current",
        Path(r"C:\ProgramData\chocolatey\lib\mpv.install\tools"),
        Path(r"C:\Program Files\mpv"),
        Path(r"C:\Program Files (x86)\mpv"),
    ]
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if p.strip():
            search_dirs.append(Path(p.strip()))

    for d in search_dirs:
        if not d.is_dir():
            continue
        for name in search_names:
            candidate = d / name
            if candidate.is_file() and candidate.stat().st_size > 512 * 1024:
                try:
                    shutil.copy2(candidate, mpv_dest)
                    alias_dest = target_dir / "libmpv-2.dll"
                    if not alias_dest.exists():
                        shutil.copy2(candidate, alias_dest)
                    return True
                except Exception:
                    pass
    return False


def download_and_extract_mpv(
    target_dir: Path,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> bool:
    """Tải và đưa thư viện mpv-2.dll vào target_dir (tools/)."""
    target_dir.mkdir(parents=True, exist_ok=True)
    mpv_dest = target_dir / ("mpv-2.dll" if sys.platform == "win32" else "libmpv.so")
    alias_dest = target_dir / "libmpv-2.dll"

    if mpv_dest.is_file() and mpv_dest.stat().st_size > 512 * 1024:
        if not alias_dest.is_file():
            try:
                shutil.copy2(mpv_dest, alias_dest)
            except Exception:
                pass
        if progress_callback:
            progress_callback(100, "Thư viện mpv đã sẵn sàng.")
        return True

    # 1. Thử tìm từ hệ thống
    if acquire_mpv_from_system(target_dir):
        if progress_callback:
            progress_callback(100, "Đã sao chép mpv từ hệ thống vào thư mục tools.")
        return True

    # 2. Tải từ mirror nếu có kết nối mạng
    ssl_context = ssl.create_default_context()
    try:
        import certifi
        ssl_context.load_verify_locations(cafile=certifi.where())
    except Exception:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    last_error = None
    for url in MPV_WINDOWS_URLS:
        if cancel_check and cancel_check():
            return False
        try:
            if progress_callback:
                progress_callback(10, f"Đang kết nối tải mpv...")
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            temp_file = target_dir / "mpv_temp_archive"
            with urllib.request.urlopen(req, context=ssl_context, timeout=30) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                block_size = 1024 * 256
                with open(temp_file, "wb") as out_file:
                    while True:
                        if cancel_check and cancel_check():
                            out_file.close()
                            temp_file.unlink(missing_ok=True)
                            return False
                        chunk = resp.read(block_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            p = min(90, 10 + int((downloaded / total_size) * 80))
                            progress_callback(p, f"Đang tải mpv: {downloaded // (1024*1024)} MB...")

            # 1. Thử giải nén bằng zipfile (nếu là định dạng zip)
            extracted = False
            try:
                with zipfile.ZipFile(temp_file, "r") as zf:
                    for member in zf.namelist():
                        name_lower = member.lower()
                        if name_lower.endswith("mpv-2.dll") or name_lower.endswith("libmpv-2.dll"):
                            with zf.open(member) as src, open(mpv_dest, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                                extracted = True
            except Exception:
                pass

            # 2. Thử giải nén bằng tar.exe có sẵn trên Windows 10/11 (hỗ trợ cả định dạng .7z và .zip)
            if not extracted:
                import subprocess
                tar_exe = shutil.which("tar")
                if tar_exe:
                    try:
                        temp_extract_dir = target_dir / "_temp_mpv_extract"
                        temp_extract_dir.mkdir(parents=True, exist_ok=True)
                        res = subprocess.run([tar_exe, "-xf", str(temp_file), "-C", str(temp_extract_dir)], capture_output=True)
                        if res.returncode == 0:
                            for root, _, files in os.walk(temp_extract_dir):
                                for f in files:
                                    if f.lower() in ("mpv-2.dll", "libmpv-2.dll"):
                                        shutil.copy2(Path(root) / f, mpv_dest)
                                        extracted = True
                        shutil.rmtree(temp_extract_dir, ignore_errors=True)
                    except Exception:
                        pass

            if temp_file.is_file():
                temp_file.unlink(missing_ok=True)

            if mpv_dest.is_file() and mpv_dest.stat().st_size > 512 * 1024:
                if not alias_dest.is_file():
                    shutil.copy2(mpv_dest, alias_dest)
                if progress_callback:
                    progress_callback(100, "Đã cài đặt thành công mpv-2.dll!")
                return True
        except Exception as e:
            last_error = e
            continue

    if progress_callback:
        progress_callback(0, f"Chưa thể tải mpv tự động: {last_error}")
    return False


