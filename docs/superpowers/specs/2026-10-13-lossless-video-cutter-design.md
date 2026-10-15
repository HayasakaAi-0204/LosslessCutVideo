# Thiết Kế Kỹ Thuật: Ứng Dụng Cắt Video Lossless (Python & PySide6)

## 1. Mục Tiêu Dự Án
Xây dựng ứng dụng desktop chạy trên Windows bằng ngôn ngữ Python, cho phép người dùng cắt một đoạn video từ mốc `Start` đến mốc `End` mà **không làm suy hao chất lượng video dù chỉ 1 bit** (Lossless), đồng thời giữ nguyên toàn bộ các luồng âm thanh, phụ đề và metadata.

## 2. Ràng Buộc & Nguyên Tắc (Theo GEMINI.md)
- Mọi dữ liệu và file thực thi nằm trọn trong thư mục gốc dự án `c:\Users\HayasakaAi\Downloads\Code\CutVideo`.
- Môi trường ảo Python: `.venv/`.
- Công cụ FFmpeg & FFprobe portable: nằm trong thư mục `tools/`.
- Không can thiệp Registry, PATH hệ thống hay Git config toàn cục.
- Giao diện người dùng: Viết bằng `PySide6`, giữ UI luôn phản hồi mượt mà trong quá trình xử lý.
- An toàn dữ liệu: Luôn xuất ra file mới, không bao giờ ghi đè hoặc can thiệp vào video nguồn.

## 3. Kiến Trúc Hệ Thống

### 3.1 Cấu Trúc Thư Mục
```text
CutVideo/
├── .venv/                      # Môi trường ảo Python
├── tools/                      # Portable binaries
│   ├── ffmpeg.exe
│   └── ffprobe.exe
├── src/
│   ├── __init__.py
│   ├── main.py                 # Khởi động ứng dụng
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py           # Quản lý đường dẫn tools/, cấu hình app
│   │   ├── probe.py            # ffprobe runner: đọc metadata, duration, keyframes
│   │   ├── cutter.py           # Lossless Stream Copy engine
│   │   └── worker.py           # QThread / QProcess worker chạy ngầm
│   └── ui/
│       ├── __init__.py
│       ├── main_window.py      # Cửa sổ chính
│       ├── player_widget.py    # Xem trước video (QMediaPlayer + QVideoWidget)
│       └── timeline_widget.py  # Thanh điều khiển thời gian, mốc In/Out
├── tests/                      # Unit tests & verification
├── docs/                       # Tài liệu thiết kế & kế hoạch
│   └── superpowers/specs/
│       └── 2026-10-13-lossless-video-cutter-design.md
├── requirements.txt            # Danh sách dependencies: PySide6
└── GEMINI.md                   # Bộ quy tắc dự án
```

### 3.2 Các Module Chính

#### A. Core Engine (`src/core/`)
1. **`config.py`**:
   - Xác định đường dẫn tương đối tới `tools/ffmpeg.exe` và `tools/ffprobe.exe`.
   - Kiểm tra tính sẵn sàng của công cụ.
2. **`probe.py` (`VideoProbe`)**:
   - Gọi `ffprobe -v error -show_entries format=duration,size,bit_rate -show_streams -of json <input>` để trích xuất thông tin video.
   - Hàm `get_keyframes(video_path)`: Quét danh sách các Keyframe (I-frame) `pkt_dts_time` để phục vụ chức năng nhảy Keyframe / Snap Keyframe.
3. **`cutter.py` (`LosslessCutter`)**:
   - Thực thi lệnh Stream Copy:
     `ffmpeg -y -ss <start> -to <end> -i <input> -c copy -map 0 -avoid_negative_ts make_zero <output>`
   - Hỗ trợ chế độ Snap Keyframe (tìm Keyframe gần nhất trước `start` để tránh lỗi đen hình ở container nén liên khung).
4. **`worker.py` (`CutWorker(QThread)`)**:
   - Thực thi tiến trình FFmpeg trong background thread.
   - Bắt tín hiệu thời gian từ FFmpeg stderr (`time=HH:MM:SS.xx`) và phát `progress_updated(float)`.
   - Báo `finished(str output_path)` hoặc `error(str message)`.

#### B. Giao Diện Người Dùng (`src/ui/`)
1. **`main_window.py`**:
   - Layout tổng quan: Menu/Top bar (Mở file), Center (Player + Timeline), Bottom (Thông số cắt, nút Xuất video, Progress bar).
   - Kéo thả file video vào cửa sổ.
2. **`player_widget.py`**:
   - Tích hợp `QMediaPlayer` và `QVideoWidget` (hoặc `QAudioOutput`).
   - Các nút cơ bản: Play/Pause, Step 1 frame forward/backward, Step to prev/next Keyframe.
3. **`timeline_widget.py`**:
   - Thanh trượt hiển thị vị trí hiện tại.
   - Đánh dấu vùng chọn `[In Point, Out Point]`.
   - Phím tắt tiện lợi: `Space` (Play/Pause), `I` (Set In), `O` (Set Out).

## 4. Chiến Lược Xử Lý Lỗi & Toàn Vẹn Dữ Liệu
- Kiểm tra dung lượng ổ đĩa đích trước khi xuất.
- Đảm bảo tên file đầu ra luôn khác tên file gốc (tự động thêm hậu tố `_cut_<start>_<end>`).
- Bắt lỗi khi người dùng chọn mốc `End` nhỏ hơn hoặc bằng `Start`.
- Thông báo rõ ràng nếu file video không có luồng video hoặc định dạng không được FFmpeg hỗ trợ.

## 5. Chiến Lược Kiểm Thử
1. Kiểm tra unit test cho `probe.py`: Trích xuất chính xác duration và codec từ video mẫu.
2. Kiểm tra unit test cho `cutter.py`: Cắt một đoạn từ video mẫu, đối chiếu codec gốc và codec sau khi cắt đảm bảo trùng khớp 100% (không bị re-encode).
3. Kiểm tra UI: Khởi động cửa sổ PySide6, nạp video và kiểm tra các nút tương tác.

