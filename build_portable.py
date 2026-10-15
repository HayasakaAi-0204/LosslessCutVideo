"""Script tự động đóng gói ứng dụng thành bản Portable độc lập (.exe).

Chạy script này bằng lệnh:
    python build_portable.py

Sau khi chạy xong, thư mục 'dist/LosslessCutVideo' và file nén
'dist/LosslessCutVideo_Portable.zip' sẽ được tạo ra.
Bạn bè chỉ cần tải về, giải nén và bấm chạy 'LosslessCutVideo.exe'
mà không cần cài đặt Python hay bất kỳ môi trường nào!
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    root_dir = Path(__file__).resolve().parent
    tools_dir = root_dir / "tools"
    dist_dir = root_dir / "dist"
    build_dir = root_dir / "build"

    print("=" * 60)
    print("   ĐÓNG GÓI ỨNG DỤNG LOSSLESS VIDEO CUTTER (PORTABLE)")
    print("=" * 60)

    # 1. Kiểm tra và tự động chuẩn bị công cụ FFmpeg / FFprobe Portable
    print("🔍 Đang kiểm tra công cụ FFmpeg và FFprobe portable...")
    from src.core.tool_downloader import download_and_extract_tools

    def cli_progress(percent: int, text: str):
        print(f"\r   [{percent:3d}%] {text}", end="", flush=True)

    has_tools = download_and_extract_tools(tools_dir, progress_callback=cli_progress)
    print()  # newline

    ffmpeg_exe = tools_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    ffprobe_exe = tools_dir / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    if not has_tools or not ffmpeg_exe.is_file() or not ffprobe_exe.is_file():
        print("\n❌ LỖI NGHIÊM TRỌNG: Chưa có ffmpeg.exe hoặc ffprobe.exe trong thư mục 'tools/'!")
        print("   Vui lòng kết nối mạng để script tự tải, hoặc copy thủ công 2 file này vào thư mục 'tools/'.")
        return

    ff_sz = ffmpeg_exe.stat().st_size // (1024 * 1024)
    fp_sz = ffprobe_exe.stat().st_size // (1024 * 1024)
    print(f"✅ Đã có đầy đủ công cụ: ffmpeg.exe ({ff_sz} MB), ffprobe.exe ({fp_sz} MB).")

    # 2. Kiểm tra hoặc cài đặt PyInstaller
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("\n📦 Đang cài đặt PyInstaller vào môi trường hiện tại...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 3. Đảm bảo App Icon đã được tạo sẵn từ Concept 2 (đã cắt bỏ hoàn toàn viền trắng mockup)
    from src.core.icon_utils import ensure_app_icons
    ico_path, png_path = ensure_app_icons(force=True)
    if ico_path and ico_path.is_file():
        print(f"🎨 Sử dụng App Icon trong suốt: {ico_path.name}")

    # 4. Chạy PyInstaller
    print("\n🚀 Bắt đầu quá trình Build (Vui lòng đợi 1-2 phút)...")
    app_name = "LosslessCutVideo"
    main_py = root_dir / "main.py"
    assets_dir = root_dir / "assets"
    output_app_dir = dist_dir / app_name

    # Dọn dẹp triệt để thư mục build và dist cũ để đảm bảo icon.ico mới được nạp sạch sẽ
    if build_dir.is_dir():
        print("🧹 Đang dọn dẹp thư mục build cũ để tránh cache icon...")
        shutil.rmtree(build_dir, ignore_errors=True)
    if output_app_dir.is_dir():
        print(f"🧹 Đang dọn dẹp thư mục {output_app_dir.name} cũ...")
        shutil.rmtree(output_app_dir, ignore_errors=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",  # Không hiện màn hình đen cmd
        "--paths",
        str(root_dir),
        "--name",
        app_name,
    ]

    if ico_path and ico_path.is_file():
        cmd.extend(["--icon", str(ico_path)])

    if assets_dir.is_dir():
        # Embed assets into PyInstaller package
        sep = ";" if sys.platform == "win32" else ":"
        cmd.extend(["--add-data", f"{assets_dir}{sep}assets"])

    cmd.append(str(main_py))

    result = subprocess.run(cmd, cwd=str(root_dir))
    if result.returncode != 0:
        print("\n❌ Build thất bại! Vui lòng kiểm tra thông báo lỗi bên trên.")
        return

    # 5. Copy tools (ffmpeg, ffprobe) và assets vào thư mục dist
    output_app_dir = dist_dir / app_name
    target_tools_dir = output_app_dir / "tools"
    target_tools_dir.mkdir(parents=True, exist_ok=True)

    copied_tools = 0
    for f in tools_dir.glob("*"):
        if f.is_file() and not f.name.startswith("."):
            dest = target_tools_dir / f.name
            shutil.copy2(f, dest)
            sz_mb = f.stat().st_size / (1024 * 1024)
            print(f" -> Đã copy {f.name} ({sz_mb:.1f} MB) vào bản xuất")
            copied_tools += 1

    dist_ffmpeg = target_tools_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    dist_ffprobe = target_tools_dir / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    if not dist_ffmpeg.is_file() or not dist_ffprobe.is_file():
        print("\n❌ LỖI: Chưa có ffmpeg.exe hoặc ffprobe.exe trong thư mục dist!")
        return

    # Copy assets folder into output dir
    target_assets_dir = output_app_dir / "assets"
    target_assets_dir.mkdir(parents=True, exist_ok=True)
    if assets_dir.is_dir():
        for f in assets_dir.glob("*"):
            if f.is_file():
                shutil.copy2(f, target_assets_dir / f.name)
        print(" -> Đã copy thư mục 'assets/' vào bản xuất")

    # 6. Tự động nén ZIP để gửi cho bạn bè
    zip_path = dist_dir / f"{app_name}_Portable"
    old_zip = dist_dir / f"{app_name}_Portable.zip"
    if old_zip.is_file():
        try:
            old_zip.unlink()
        except Exception:
            pass
    print(f"\n📦 Đang nén thành file '{zip_path.name}.zip' để tiện gửi cho bạn bè...")
    shutil.make_archive(str(zip_path), "zip", root_dir=str(dist_dir), base_dir=app_name)

    print("\n" + "=" * 60)
    print("🎉 ĐÓNG GÓI HOÀN TẤT THÀNH CÔNG!")
    print(f"📁 Thư mục chạy thử: {output_app_dir}")
    print(f"   (Bấm vào '{output_app_dir / (app_name + '.exe')}' để mở)")
    print(f"📦 File ZIP gửi bạn bè: {dist_dir / (zip_path.name + '.zip')}")
    print("=" * 60)


if __name__ == "__main__":
    main()

