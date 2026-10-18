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

    # 3. Thư viện mpv (tự động sao chép hoặc tải nếu có kết nối)
    tools_dir = PROJECT_ROOT / "tools"
    mpv_dll = tools_dir / ("mpv-2.dll" if sys.platform == "win32" else "libmpv.so")
    libmpv_dll = tools_dir / "libmpv-2.dll"
    if mpv_dll.is_file() or libmpv_dll.is_file():
        dll_target = mpv_dll if mpv_dll.is_file() else libmpv_dll
        log(f"Đã tìm thấy thư viện mpv: {dll_target.name} ({dll_target.stat().st_size // (1024*1024)} MB).")
    else:
        from src.core.tool_downloader import acquire_mpv_from_system, download_and_extract_mpv
        if acquire_mpv_from_system(tools_dir):
            log("Đã tự động tìm và sao chép mpv-2.dll từ hệ thống vào tools/!")
        else:
            log("Đang tự động tải thư viện mpv-2.dll để phát AV1 mượt mà trên mọi máy tính...")
            if download_and_extract_mpv(tools_dir):
                log("Đã tải và cài đặt thành công mpv-2.dll vào tools/!")
            else:
                log("Chưa thể tải mpv-2.dll, bản đóng gói sẽ dùng bộ giải mã tương thích dự phòng.")

    # 4. App icon
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


def prune_unnecessary_files(app_folder: Path):
    """Xóa bỏ các thư mục và file rác không sử dụng do PyInstaller thu thập nhằm thu gọn tối đa dung lượng."""
    pyside_dir = app_folder / "_internal" / "PySide6"
    if not pyside_dir.is_dir():
        return

    log("Dọn dẹp các thư mục Qt thừa (QML, Designer, 3D, Translations)...")

    # 1. Thư mục QML (chỉ dùng cho QtQuick/QML, app dùng QtWidgets thuần)
    qml_dir = pyside_dir / "qml"
    if qml_dir.is_dir():
        try:
            shutil.rmtree(qml_dir)
            log("  - Đã loại bỏ thư mục QML không sử dụng (~100MB).")
        except Exception:
            pass

    # 2. Xóa các plugin phụ trợ không dùng trong plugins/
    plugins_dir = pyside_dir / "plugins"
    if plugins_dir.is_dir():
        unneeded_plugin_folders = [
            "qmltooling", "scenegraph", "renderers", "designer",
            "sensors", "position", "geoservices", "canbus",
        ]
        for f_name in unneeded_plugin_folders:
            p = plugins_dir / f_name
            if p.is_dir():
                try:
                    shutil.rmtree(p)
                except Exception:
                    pass

    # 3. Xóa các file dịch quốc tế (.qm) không cần thiết
    translations_dir = pyside_dir / "translations"
    if translations_dir.is_dir():
        try:
            shutil.rmtree(translations_dir)
            log("  - Đã loại bỏ thư mục translations ngôn ngữ thừa (~30MB).")
        except Exception:
            pass


def ensure_msvc_redist_dlls(app_folder: Path):
    """Đảm bảo các file runtime C++ cơ bản (VCRUNTIME140.dll, MSVCP140.dll) luôn có mặt trong _internal/
    để người dùng vừa cài lại Windows chưa cài Visual C++ Redistributable vẫn bấm chạy được ngay 100%."""
    dest_dir = app_folder / "_internal"
    if not dest_dir.is_dir():
        return

    msvc_dlls = ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll"]
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    python_dir = Path(sys.executable).parent

    for dll_name in msvc_dlls:
        target_f = dest_dir / dll_name
        if not target_f.exists():
            candidate_sources = [
                python_dir / dll_name,
                system32 / dll_name,
            ]
            for src in candidate_sources:
                if src.is_file():
                    try:
                        shutil.copy2(src, target_f)
                        log(f"  - Đã tích hợp {dll_name} hỗ trợ máy vừa cài lại Windows.")
                        break
                    except Exception:
                        pass


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

    # Loại trừ các module nặng không dùng đến để tối ưu kích thước gói
    unused_qt_modules = [
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQuick3D",
        "PySide6.QtDesigner",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DExtras",
        "PySide6.QtSensors",
        "PySide6.QtPositioning",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtSpatialAudio",
        "PySide6.QtVirtualKeyboard",
        "PySide6.QtDataVisualization",
        "PySide6.QtCharts",
        "PySide6.QtScxml",
        "PySide6.QtRemoteObjects",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtXml",
    ]
    for mod in unused_qt_modules:
        cmd.extend(["--exclude-module", mod])

    # Thu thập toàn bộ package python-mpv nếu có sẵn DLL mpv và package trong môi trường
    from src.core.config import has_mpv
    if has_mpv():
        try:
            import importlib.util
            if importlib.util.find_spec("mpv") is not None:
                cmd.extend(["--collect-all", "mpv"])
        except Exception:
            pass

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

        # Tạo file qt.conf ở thư mục gốc app_folder để Qt tự động nhận diện plugins
        qt_conf_file = app_folder / "qt.conf"
        if (app_folder / "_internal" / "PySide6" / "plugins").is_dir():
            qt_conf_content = "[Paths]\nPrefix = _internal/PySide6\nPlugins = plugins\n"
        elif (app_folder / "_internal" / "plugins").is_dir():
            qt_conf_content = "[Paths]\nPrefix = _internal\nPlugins = plugins\n"
        else:
            qt_conf_content = "[Paths]\nPrefix = .\nPlugins = plugins\n"
        qt_conf_file.write_text(qt_conf_content, encoding="utf-8")
        log("Đã tạo file cấu hình qt.conf cho bộ nạp runtime Qt.")

        # Dọn dẹp các thư mục rác không dùng đến do PyInstaller thu thập
        prune_unnecessary_files(app_folder)

        # Đảm bảo có sẵn các DLL C++ runtime thiết yếu để máy vừa cài Windows chạy được ngay
        ensure_msvc_redist_dlls(app_folder)

        # Sao chép mpv DLL vào _internal/ nếu có sẵn để đảm bảo Python DLL loader luôn tìm thấy
        found_mpv_src = None
        for mpv_name in ["mpv-2.dll", "libmpv-2.dll"]:
            p = tools_dir / mpv_name
            if p.is_file():
                found_mpv_src = p
                break

        if found_mpv_src is not None:
            for mpv_name in ["mpv-2.dll", "libmpv-2.dll"]:
                dst_mpv = app_folder / "_internal" / mpv_name
                if not dst_mpv.exists():
                    try:
                        shutil.copy2(found_mpv_src, dst_mpv)
                        log(f"  - Đã tích hợp {mpv_name} vào _internal/")
                    except Exception:
                        pass
                # Đồng thời đảm bảo thư mục tools/ trong bản phân phối có cả 2 tên gọi
                tools_mpv = app_folder / "tools" / mpv_name
                if (app_folder / "tools").is_dir() and not tools_mpv.exists():
                    try:
                        shutil.copy2(found_mpv_src, tools_mpv)
                    except Exception:
                        pass

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

