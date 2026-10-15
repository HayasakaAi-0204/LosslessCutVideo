"""Automatic downloader and extractor for portable FFmpeg & FFprobe binaries.

Downloads official static Windows builds and extracts ffmpeg.exe and ffprobe.exe
directly into the project's tools/ directory.
"""

from pathlib import Path
import shutil
import ssl
import sys
import urllib.request
import zipfile
from typing import Callable, Optional

# Reliable download mirrors for Windows 64-bit static FFmpeg builds
FFMPEG_WINDOWS_URLS = [
    # yt-dlp GitHub release (fast, robust CDN, GPL full features)
    "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    # Official gyan.dev release essentials build recommended by ffmpeg.org
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
]


def acquire_tools_from_system(target_dir: Path) -> dict[str, bool]:
    """Check if ffmpeg/ffprobe exist in system PATH, and copy them to target_dir.

    Returns:
        dict with boolean status for 'ffmpeg' and 'ffprobe'.
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
    """Download portable FFmpeg/FFprobe archive and extract binaries to target_dir.

    Args:
        target_dir: Directory where ffmpeg.exe and ffprobe.exe should be placed.
        progress_callback: Optional callable(percent: int, status_text: str).
        cancel_check: Optional callable returning True if download should abort.

    Returns:
        True if both ffmpeg and ffprobe are successfully placed in target_dir.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_dest = target_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    ffprobe_dest = target_dir / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")

    # 1. First, check if already present and valid in target_dir
    if ffmpeg_dest.is_file() and ffprobe_dest.is_file():
        if ffmpeg_dest.stat().st_size > 1024 * 1024 and ffprobe_dest.stat().st_size > 1024 * 1024:
            if progress_callback:
                progress_callback(100, "Công cụ FFmpeg & FFprobe đã sẵn sàng trong tools/.")
            return True

    # 2. Try copying from system PATH if available
    sys_status = acquire_tools_from_system(target_dir)
    if sys_status["ffmpeg"] and sys_status["ffprobe"]:
        if progress_callback:
            progress_callback(100, "Đã sao chép công cụ từ hệ thống vào thư mục tools.")
        return True

    # 3. Download from mirrors
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
                block_size = 1024 * 256  # 256 KB chunks

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

            # Extract ffmpeg.exe and ffprobe.exe from zip
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

            # Cleanup temp zip
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

