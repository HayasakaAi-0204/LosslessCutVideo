# Lossless Video Cutter (Python & PySide6)

Ứng dụng cắt video dành cho Windows viết hoàn toàn bằng Python, sử dụng cơ chế **FFmpeg Stream Copy (`-c copy`)** để cắt video nhanh tức thì mà **không suy hao bất kỳ 1 bit chất lượng nào** (0% re-encoding).

---

## Tính Năng Nổi Bật
- **100% Giữ nguyên chất lượng gốc:** Không encode lại video/âm thanh, giữ nguyên codec, bitrate, HDR/color profile, tất cả audio tracks và phụ đề.
- **Tốc độ xuất siêu tốc:** Xử lý file video 4K/8K trong 1 - 3 giây.
- **Tự động bám dính Keyframe (I-frame Snapping):** Tránh hiện tượng đứng hình hoặc đen khung đầu khi mở trên các trình phát video.
- **Giao diện PySide6 hiện đại:**
  - Kéo thả (Drag & Drop) video trực tiếp vào ứng dụng.
  - Xem trước video với bộ điều khiển tua từng frame và tua theo Keyframe.
  - Phím tắt tiện lợi: `Phím cách` (Play/Pause), `Phím I` (Set In Point), `Phím O` (Set Out Point).
  - Không bao giờ bị treo ứng dụng nhờ xử lý ngầm qua luồng `CutWorker`.
- **Tuyệt đối an toàn cho file gốc:** Tự động tạo file mới, không bao giờ ghi đè file nguồn.

---

## Hướng Dẫn Cài Đặt & Khởi Chạy

### 1. Chuẩn bị môi trường Python
Mở Terminal tại thư mục dự án và chạy:
```powershell
# Tạo môi trường ảo
python -m venv .venv

# Kích hoạt môi trường ảo
.\.venv\Scripts\Activate.ps1

# Cài đặt thư viện giao diện PySide6
pip install -r requirements.txt
```

### 2. Chuẩn bị FFmpeg & FFprobe Portable
Theo quy tắc của dự án, tải bản build portable cho Windows của FFmpeg (ví dụ từ [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)):
1. Giải nén và copy 2 file:
   - `ffmpeg.exe`
   - `ffprobe.exe`
2. Đặt vào thư mục: `tools/` bên trong dự án:
   ```text
   CutVideo/
   └── tools/
       ├── ffmpeg.exe
       └── ffprobe.exe
   ```

### 3. Chạy Ứng Dụng
```powershell
python src/main.py
```

### 4. Chạy Kiểm Thử Tự Động (Unit Tests)
```powershell
python tests/run_all_tests.py
```

