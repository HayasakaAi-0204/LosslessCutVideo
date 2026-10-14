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

    # 1. Kiểm tra công cụ FFmpeg / FFprobe
    ffmpeg_exe = tools_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    ffprobe_exe = tools_dir / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
    if not ffmpeg_exe.is_file() or not ffprobe_exe.is_file():
        print("⚠️ CẢNH BÁO: Chưa tìm thấy ffmpeg.exe hoặc ffprobe.exe trong thư mục 'tools/'!")
        print("   Vui lòng đảm bảo đã copy 2 file này vào 'tools/' trước khi gửi app cho bạn bè.")

    # 2. Kiểm tra hoặc cài đặt PyInstaller
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("\n📦 Đang cài đặt PyInstaller vào môi trường hiện tại...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 3. Chạy PyInstaller
    print("\n🚀 Bắt đầu quá trình Build (Vui lòng đợi 1-2 phút)...")
    app_name = "LosslessCutVideo"
    main_py = root_dir / "main.py"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",  # Không hiện màn hình đen cmd
        "--name",
        app_name,
        str(main_py),
    ]

    result = subprocess.run(cmd, cwd=str(root_dir))
    if result.returncode != 0:
        print("\n❌ Build thất bại! Vui lòng kiểm tra thông báo lỗi bên trên.")
        return

    # 4. Copy tools (ffmpeg, ffprobe) vào thư mục dist
    output_app_dir = dist_dir / app_name
    target_tools_dir = output_app_dir / "tools"
    target_tools_dir.mkdir(parents=True, exist_ok=True)

    copied_tools = 0
    for f in tools_dir.glob("*"):
        if f.is_file() and not f.name.startswith("."):
            dest = target_tools_dir / f.name
            shutil.copy2(f, dest)
            print(f" -> Đã copy {f.name} vào bản xuất")
            copied_tools += 1

    if copied_tools == 0:
        print("⚠️ Chú ý: Chưa có file nào trong thư mục 'tools/' được copy.")

    # 5. Tự động nén ZIP để gửi cho bạn bè
    zip_path = dist_dir / f"{app_name}_Portable"
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

