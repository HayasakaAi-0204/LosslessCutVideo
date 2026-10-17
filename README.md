# Lossless Video Cutter (Python & PySide6)

Ứng dụng cắt video dành cho Windows viết hoàn toàn bằng Python, sử dụng cơ chế **FFmpeg Stream Copy (`-c copy`)** để cắt video nhanh tức thì mà **không suy hao bất kỳ 1 bit chất lượng nào** (0% re-encoding).

---

## Tính Năng Nổi Bật
- **100% Giữ nguyên chất lượng gốc:** Không encode lại video/âm thanh, giữ nguyên codec, bitrate, HDR/color profile, tất cả audio tracks và phụ đề.
- **Tốc độ xuất siêu tốc:** Xử lý file video 4K/8K trong 1 - 3 giây.
- **Tự động bám dính Keyframe (I-frame Snapping):** Tránh hiện tượng đứng hình hoặc đen khung đầu khi mở trên các trình phát video.
- **📸 Chụp ảnh khung hình độ nét gốc (Snapshot Frame):**
  - Bấm nút `📸 Chụp Ảnh` hoặc nhấn phím `C` (hoặc `Ctrl+S`).
  - Trích xuất ảnh PNG độ nét gốc 100% (4K/2K siêu sắc nét) trong nền mà không đơ giật giao diện.
  - Tự động copy ảnh vào Clipboard để paste ngay vào Zalo/Word/PowerPoint.
- **⟳ Xoay video Lossless siêu tốc (0.2s):**
  - Xoay hướng video theo các góc $90^\circ, 180^\circ, 270^\circ$ theo chiều kim đồng hồ bằng nút `⟳ Xoay` hoặc phím tắt `Ctrl+R`.
  - Không cần nén lại (re-encode), sửa trực tiếp thẻ metadata orientation của MP4/MOV/MKV chỉ trong chớp mắt.
  - Đồng bộ góc xoay tự động khi chụp ảnh khung hình (Snapshot).
- **🎵 Tự động nhận diện & Trích xuất Âm thanh Lossless:** Khi bỏ các track video trên timeline, ứng dụng tự động gợi ý định dạng âm thanh tương thích (`.m4a`, `.mp3`, `.opus`, `.flac`...) và cắt chuẩn xác từng mili-giây.
- **Giao diện PySide6 hiện đại:**
  - Kéo thả (Drag & Drop) video trực tiếp vào ứng dụng (hỗ trợ đường dẫn có dấu ngoặc và khoảng trắng).
  - Multi-track Timeline dạng CapCut hỗ trợ bật/tắt từng luồng hình ảnh và âm thanh.
  - Xem trước video với bộ điều khiển tua từng frame và tua theo Keyframe.
  - Phím tắt tiện lợi: `Phím cách` (Play/Pause), `Phím I` (Set In Point), `Phím O` (Set Out Point), `Phím C` (Chụp ảnh), `Ctrl+R` (Xoay 90°), `Phím [ / ]` (Tăng/giảm tốc độ phát).
  - Không bao giờ bị treo ứng dụng nhờ xử lý ngầm qua các worker bất đồng bộ.
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

---

## Đóng Gói Thành File Cài Đặt / Portable (.exe) Để Gửi Bạn Bè

Bạn không cần bắt bạn bè phải cài Python hay mở terminal phức tạp. Ứng dụng đã có sẵn công cụ đóng gói 1-click:

### Cách 1: Chạy file batch (Khuyên dùng - Nhanh nhất)
1. Bấm đúp chuột vào file `build_exe.bat` trong thư mục dự án.
2. Quá trình đóng gói sẽ tự động:
   - Cài đặt PyInstaller (nếu chưa có).
   - Đóng gói toàn bộ mã nguồn, PySide6, Qt Multimedia, Icon và FFmpeg/FFprobe Portable.
   - Tự động nén thành file **`dist/LosslessVideoCutter_Windows.zip`**.

### Cách 2: Chạy qua dòng lệnh (Terminal)
```powershell
# Kích hoạt venv
.\.venv\Scripts\Activate.ps1

# Chạy script đóng gói tự động
python package_app.py --mode onedir
```

### Cách gửi cho bạn bè:
1. Gửi file `dist/LosslessVideoCutter_Windows.zip` cho bạn bè (qua Zalo, Google Drive, Telegram...).
2. Bạn bè chỉ cần tải về, **Giải nén (Extract All)** và bấm đúp vào **`LosslessVideoCutter.exe`** để sử dụng ngay mà không cần cài thêm bất kỳ phần mềm nào khác!

