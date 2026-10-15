"""Automated packaging script for Lossless Video Cutter.

Builds a standalone portable distribution of the application using PyInstaller,
including all Qt Multimedia plugins, FFmpeg/FFprobe binaries, and app icons.
Finally, packs everything into a ready-to-share ZIP file.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parent


def log(msg: str):
    print(f"\n[BUILD] >>> {msg}", flush=True)


def check_prerequisites() -> bool:
    """Check that required tools and dependencies exist."""
    log("Kiểm tra điều kiện tiên quyết...")
    
    # 1. PyInstaller
    try:
        import PyInstaller
        log(f"Đã tìm thấy PyInstaller: phiên bản {PyInstaller.__version__}")
    except ImportError:
        print("\n[LỖI] Chưa cài đặt PyInstaller trong môi trường Python này!")
        print("Vui lòng chạy lệnh sau để cài đặt:")
        print("    pip install pyinstaller")
        return False

    # 2. Tools (ffmpeg & ffprobe)
    ffmpeg_exe = PROJECT_ROOT / "tools" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    ffprobe_exe = PROJECT_ROOT / "tools" / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    
    if not ffmpeg_exe.is_file() or not ffprobe_exe.is_file():
        print("\n[CẢNH BÁO] Không tìm thấy ffmpeg.exe hoặc ffprobe.exe trong thư mục tools/!")
        print(f"  - ffmpeg: {'OK' if ffmpeg_exe.is_file() else 'THIẾU'}")
        print(f"  - ffprobe: {'OK' if ffprobe_exe.is_file() else 'THIẾU'}")
        print("Vui lòng tải và đặt ffmpeg.exe, ffprobe.exe vào thư mục 'tools/' trước khi đóng gói.")
        return False
    log(f"Đã tìm thấy FFmpeg ({ffmpeg_exe.stat().st_size // (1024*1024)} MB) và FFprobe ({ffprobe_exe.stat().st_size // (1024*1024)} MB).")

    # 3. App icon
    from src.core.icon_utils import ensure_app_icons
    ico_p, png_p = ensure_app_icons()
    if ico_p and ico_p.is_file():
        log(f"Đã chuẩn bị Icon ứng dụng: {ico_p}")
    else:
        log("Không tìm thấy icon.ico, sẽ sử dụng icon mặc định.")

    return True


def clean_build_artifacts():
    """Remove previous build and dist directories."""
    log("Dọn dẹp các thư mục build cũ...")
    for folder_name in ["build", "dist"]:
        folder = PROJECT_ROOT / folder_name
        if folder.exists():
            try:
                shutil.rmtree(folder)
                print(f"  Đã xóa: {folder}")
            except Exception as e:
                print(f"  Không thể xóa {folder}: {e}")


def build_distribution(mode: str = "onedir") -> Path:
    """Run PyInstaller with optimal flags.
    
    Args:
        mode: 'onedir' (khuyên dùng - mở tức thì) hoặc 'onefile' (1 file duy nhất).
    """
    app_name = "LosslessVideoCutter"
    entry_point = PROJECT_ROOT / "src" / "main.py"
    icon_path = PROJECT_ROOT / "assets" / "icon.ico"
    tools_dir = PROJECT_ROOT / "tools"
    assets_dir = PROJECT_ROOT / "assets"

    sep = ";" if sys.platform == "win32" else ":"

    # Base PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", app_name,
        "--noconsole",                 # Ẩn màn hình cmd đen khi chạy
        "--clean",
        "--noconfirm",
        # Thêm thư viện PySide6 và các plugin Multimedia/Platforms
        "--collect-all", "PySide6",
        # Đường dẫn tìm kiếm module
        "--paths", str(PROJECT_ROOT),
    ]

    if icon_path.is_file():
        cmd.extend(["--icon", str(icon_path)])

    if mode == "onefile":
        log("Đóng gói chế độ: ONE-FILE (Tất cả gộp trong 1 file .exe duy nhất)...")
        cmd.append("--onefile")
        # Nhúng trực tiếp tools và assets vào trong file exe (_MEIPASS)
        cmd.extend(["--add-data", f"{tools_dir}{sep}tools"])
        cmd.extend(["--add-data", f"{assets_dir}{sep}assets"])
    else:
        log("Đóng gói chế độ: ONE-DIR (Thư mục Portable hoàn chỉnh - Khởi động siêu tốc)...")
        cmd.append("--onedir")

    cmd.append(str(entry_point))

    log(f"Đang thực thi PyInstaller (quá trình này có thể mất 1 - 3 phút)...")
    print(f"Lệnh: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"PyInstaller thất bại với mã lỗi {result.returncode}")

    dist_dir = PROJECT_ROOT / "dist"
    
    if mode == "onedir":
        app_folder = dist_dir / app_name
        # Đảm bảo tools/ và assets/ được copy vào thư mục ứng dụng
        target_tools = app_folder / "tools"
        if not target_tools.exists() and tools_dir.exists():
            log(f"Copy thư mục tools/ vào {target_tools}...")
            shutil.copytree(tools_dir, target_tools)

        target_assets = app_folder / "assets"
        if not target_assets.exists() and assets_dir.exists():
            log(f"Copy thư mục assets/ vào {target_assets}...")
            shutil.copytree(assets_dir, target_assets)

        return app_folder
    else:
        exe_path = dist_dir / f"{app_name}.exe"
        return exe_path


def create_zip_package(target_path: Path) -> Path:
    """Create a compressed .zip file ready for distribution."""
    dist_dir = PROJECT_ROOT / "dist"
    zip_path = dist_dir / "LosslessVideoCutter_Windows.zip"
    
    log(f"Đang nén toàn bộ thành file ZIP để gửi bạn bè: {zip_path.name}...")
    
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        if target_path.is_dir():
            for root, _, files in os.walk(target_path):
                for file in files:
                    full_p = Path(root) / file
                    rel_p = full_p.relative_to(target_path.parent)
                    zf.write(full_p, rel_p)
        else:
            zf.write(target_path, target_path.name)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    log(f"Tạo file ZIP thành công! Dung lượng: {size_mb:.1f} MB")
    return zip_path


def main():
    parser = argparse.ArgumentParser(description="Đóng gói ứng dụng Lossless Video Cutter")
    parser.add_argument(
        "--mode",
        choices=["onedir", "onefile"],
        default="onedir",
        help="Chế độ đóng gói: 'onedir' (Thư mục portable, chạy ngay không trễ - mặc định) hoặc 'onefile' (1 file .exe duy nhất)."
    )
    args = parser.parse_args()

    print("=" * 70)
    print("   TRÌNH ĐÓNG GÓI TỰ ĐỘNG - LOSSLESS VIDEO CUTTER FOR WINDOWS")
    print("=" * 70)

    if not check_prerequisites():
        sys.exit(1)

    clean_build_artifacts()

    try:
        output_path = build_distribution(mode=args.mode)
        zip_file = create_zip_package(output_path)
        
        print("\n" + "=" * 70)
        print("🎉 HOÀN THÀNH ĐÓNG GÓI XUẤT SẮC!")
        print("=" * 70)
        print(f"📁 Thư mục kết quả: {PROJECT_ROOT / 'dist'}")
        print(f"📦 File gửi cho bạn bè: {zip_file}")
        print("\nCách gửi cho bạn bè:")
        print("1. Gửi file 'LosslessVideoCutter_Windows.zip' qua Zalo, Google Drive, hoặc Telegram.")
        print("2. Bạn bè chỉ cần giải nén (Extract All) và bấm đúp vào 'LosslessVideoCutter.exe' là dùng được ngay!")
        print("=" * 70 + "\n")

    except Exception as e:
        print(f"\n[LỖI QUÁ TRÌNH BUILD] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

