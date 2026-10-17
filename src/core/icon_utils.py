"""Tiện ích tạo và quản lý biểu tượng (icon) cho ứng dụng Lossless Video Cutter.

Tự động trích xuất khối squircle bo góc tối màu từ ảnh thiết kế gốc,
khử răng cưa viền bo góc trong suốt, và đóng gói chuẩn file .ico đa độ phân giải cho Windows
cùng định dạng ảnh .png sắc nét.
"""

import io
from pathlib import Path
import shutil
import struct
import sys
from typing import Optional


SOURCE_IMAGE_HINTS = [
    Path(r"C:\Users\HayasakaAi\.gemini\antigravity\brain\03a6e83d-f59b-4671-9388-bc114bc56e3c\losslesscut_icon_concept2_film_scissors_1791998111844.jpg"),
]


def qimage_to_ico_dib(qimg) -> bytes:
    """Chuyển đổi QImage thành cấu trúc Win32 ICO DIB chuẩn (BITMAPINFOHEADER + BGRA + AND mask).
    
    Tương thích 100% với định dạng tài nguyên icon của Windows Explorer, GDI và PyInstaller.
    """
    from PySide6.QtGui import QImage
    w = qimg.width()
    h = qimg.height()
    converted = qimg.convertToFormat(QImage.Format.Format_ARGB32)
    # BITMAPINFOHEADER (40 bytes): biHeight gấp đôi h (XOR mask + AND mask)
    bih = struct.pack("<IIIHHIIIIII", 40, w, h * 2, 1, 32, 0, w * h * 4, 0, 0, 0, 0)

    xor_bytes = bytearray()
    and_stride = ((w + 31) // 32) * 4
    and_bytes = bytearray()

    for y in range(h - 1, -1, -1):
        row_and = bytearray(and_stride)
        for x in range(w):
            c = converted.pixelColor(x, y)
            xor_bytes.extend([c.blue(), c.green(), c.red(), c.alpha()])
            if c.alpha() == 0:
                row_and[x // 8] |= (1 << (7 - (x % 8)))
        and_bytes.extend(row_and)

    return bih + bytes(xor_bytes) + bytes(and_bytes)


def create_ico_from_pngs(png_data_list: list[tuple[int, bytes]]) -> bytes:
    """Tạo dữ liệu nhị phân Windows .ico đa kích thước từ danh sách (kích_thước, dữ_liệu_bytes)."""
    count = len(png_data_list)
    header = struct.pack("<HHH", 0, 1, count)

    offset = 6 + 16 * count
    directory_entries = []
    image_payloads = []

    for size, data in png_data_list:
        width_byte = 0 if size >= 256 else size
        height_byte = 0 if size >= 256 else size
        data_len = len(data)

        entry = struct.pack(
            "<BBBBHHII",
            width_byte,
            height_byte,
            0,       # bColorCount
            0,       # bReserved
            1,       # wPlanes
            32,      # wBitCount
            data_len,
            offset,
        )
        directory_entries.append(entry)
        image_payloads.append(data)
        offset += data_len

    return header + b"".join(directory_entries) + b"".join(image_payloads)


def extract_transparent_squircle_qimage(src_file: Path) -> Optional[tuple[bytes, bytes]]:
    """Cắt khối squircle bo góc, xóa phông nền sáng và tạo nền trong suốt mượt mà bằng PySide6."""
    try:
        from PySide6.QtGui import QImage, QPainter, QPainterPath
        from PySide6.QtCore import Qt, QBuffer, QIODevice
    except ImportError:
        return None

    qimg = QImage(str(src_file))
    if qimg.isNull():
        return None

    w = qimg.width()
    h = qimg.height()

    bg_c = qimg.pixelColor(5, 5)
    bg_r, bg_g, bg_b = bg_c.red(), bg_c.green(), bg_c.blue()

    min_x, max_x = w, 0
    min_y, max_y = h, 0

    # Quét để phát hiện khung viền (bounding box) của khối squircle tối
    step = 2
    for y in range(0, h, step):
        for x in range(0, w, step):
            c = qimg.pixelColor(x, y)
            r, g, b = c.red(), c.green(), c.blue()
            dist = ((r - bg_r) ** 2 + (g - bg_g) ** 2 + (b - bg_b) ** 2) ** 0.5
            if dist > 45 and (r + g + b) / 3 < 185:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y

    if min_x >= max_x or min_y >= max_y or (max_x - min_x) < 100:
        min_x = int(w * 0.22)
        max_x = int(w * 0.78)
        min_y = int(h * 0.22)
        max_y = int(h * 0.78)

    # Thu vào trong 4px để loại bỏ hoàn toàn viền đổ bóng mờ
    min_x += 4
    max_x -= 4
    min_y += 4
    max_y -= 4

    side = max(max_x - min_x, max_y - min_y)
    cx = (min_x + max_x) // 2
    cy = (min_y + max_y) // 2
    crop_x = max(0, min(w - side, cx - side // 2))
    crop_y = max(0, min(h - side, cy - side // 2))

    cropped = qimg.copy(crop_x, crop_y, side, side)

    # Khởi tạo canvas 512x512 với 4 góc trong suốt 100%
    target_side = 512
    result = QImage(target_side, target_side, QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(Qt.GlobalColor.transparent)

    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    path = QPainterPath()
    radius = float(target_side) * 0.225
    path.addRoundedRect(0.0, 0.0, float(target_side), float(target_side), radius, radius)

    painter.setClipPath(path)
    painter.drawImage(result.rect(), cropped)
    painter.end()

    png_buf = QBuffer()
    png_buf.open(QIODevice.OpenModeFlag.WriteOnly)
    result.save(png_buf, "PNG")
    png_bytes = bytes(png_buf.data())
    png_buf.close()

    # 1. Ưu tiên hàng đầu: Nếu có thư viện Pillow, dùng Pillow để đóng gói file ICO đa kích thước chuẩn
    try:
        from PIL import Image
        pil_img = Image.open(io.BytesIO(png_bytes))
        ico_io = io.BytesIO()
        icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
        pil_img.save(ico_io, format="ICO", sizes=icon_sizes)
        return ico_io.getvalue(), png_bytes
    except Exception:
        pass

    # 2. Phương án dự phòng thuần PySide6: DIB chuẩn cho kích thước <=128 và PNG cho 256
    target_sizes = [256, 128, 64, 48, 32, 16]
    ico_entries: list[tuple[int, bytes]] = []

    for s in target_sizes:
        scaled = result.scaled(
            s, s,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        if s >= 256:
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            scaled.save(buf, "PNG")
            ico_entries.append((s, bytes(buf.data())))
            buf.close()
        else:
            ico_entries.append((s, qimage_to_ico_dib(scaled)))

    ico_bytes = create_ico_from_pngs(ico_entries)
    return ico_bytes, png_bytes


def extract_transparent_squircle_pil(src_file: Path) -> Optional[tuple[bytes, bytes]]:
    """Cắt khối squircle bo góc, xóa phông nền sáng và tạo nền trong suốt bằng Pillow."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    try:
        img = Image.open(src_file).convert("RGBA")
        w, h = img.size
        pixels = img.load()
        bg_r, bg_g, bg_b, _ = pixels[5, 5]

        min_x, max_x = w, 0
        min_y, max_y = h, 0

        for y in range(0, h, 2):
            for x in range(0, w, 2):
                r, g, b, _ = pixels[x, y]
                dist = ((r - bg_r) ** 2 + (g - bg_g) ** 2 + (b - bg_b) ** 2) ** 0.5
                if dist > 45 and (r + g + b) / 3 < 185:
                    if x < min_x: min_x = x
                    if x > max_x: max_x = x
                    if y < min_y: min_y = y
                    if y > max_y: max_y = y

        if min_x >= max_x or min_y >= max_y or (max_x - min_x) < 100:
            min_x, max_x = int(w * 0.22), int(w * 0.78)
            min_y, max_y = int(h * 0.22), int(h * 0.78)

        min_x += 4
        max_x -= 4
        min_y += 4
        max_y -= 4

        side = max(max_x - min_x, max_y - min_y)
        cx = (min_x + max_x) // 2
        cy = (min_y + max_y) // 2
        crop_box = (
            max(0, min(w - side, cx - side // 2)),
            max(0, min(h - side, cy - side // 2)),
            max(0, min(w - side, cx - side // 2)) + side,
            max(0, min(h - side, cy - side // 2)) + side,
        )
        cropped = img.crop(crop_box).resize((512, 512), Image.Resampling.LANCZOS)

        mask = Image.new("L", (512, 512), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle([0, 0, 512, 512], radius=int(512 * 0.225), fill=255)
        cropped.putalpha(mask)

        png_io = io.BytesIO()
        cropped.save(png_io, "PNG")
        png_bytes = png_io.getvalue()

        ico_io = io.BytesIO()
        icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
        cropped.save(ico_io, format="ICO", sizes=icon_sizes)
        ico_bytes = ico_io.getvalue()

        return ico_bytes, png_bytes
    except Exception:
        return None


def ensure_app_icons(force: bool = False) -> tuple[Optional[Path], Optional[Path]]:
    """Đảm bảo các file assets/icon.ico và assets/icon.png luôn sẵn sàng với nền trong suốt 100%.
    
    Tham số:
        force: Nếu True, trích xuất và tạo lại dù file đã tồn tại.
        
    Trả về:
        tuple (ico_path, png_path)
    """
    from src.core.config import get_assets_dir
    
    assets_dir = get_assets_dir()
    ico_path = assets_dir / "icon.ico"
    png_path = assets_dir / "icon.png"
    local_source = assets_dir / "icon_source.jpg"

    if not force and ico_path.is_file() and png_path.is_file():
        return ico_path, png_path

    # Locate source image
    src_file: Optional[Path] = None
    if local_source.is_file():
        src_file = local_source
    else:
        for p in SOURCE_IMAGE_HINTS:
            if p.is_file():
                src_file = p
                try:
                    shutil.copy2(p, local_source)
                except Exception:
                    pass
                break

    if not src_file or not src_file.is_file():
        return None, None

    # 1. Try PySide6 QImage extraction
    result = extract_transparent_squircle_qimage(src_file)
    if not result:
        # 2. Try Pillow extraction
        result = extract_transparent_squircle_pil(src_file)

    if result:
        ico_bytes, png_bytes = result
        ico_path.write_bytes(ico_bytes)
        png_path.write_bytes(png_bytes)
        return ico_path, png_path

    return None, None
