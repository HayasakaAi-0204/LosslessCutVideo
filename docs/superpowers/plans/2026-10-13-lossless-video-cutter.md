# Lossless Video Cutter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây dựng ứng dụng desktop Python với giao diện PySide6 cho phép cắt video đơn (Single Cut) theo phương pháp Stream Copy 100% Lossless, không suy hao chất lượng và tốc độ xử lý tức thì.

**Architecture:** Kiến trúc module hóa tách biệt: tầng công cụ (`tools/`), tầng xử lý media lõi (`src/core/`), tầng luồng ngầm (`QThread` worker), và tầng giao diện người dùng (`src/ui/`). FFmpeg/FFprobe portable xử lý trích xuất keyframe và stream copy.

**Tech Stack:** Python 3.10+, PySide6, FFmpeg/FFprobe portable.

**Spec:** `docs/superpowers/specs/2026-10-13-lossless-video-cutter-design.md`

## Global Constraints
- Mọi dữ liệu dự án nằm trọn trong thư mục gốc `CutVideo/`.
- Python dependencies cài đặt và chạy trong môi trường ảo `.venv/`.
- FFmpeg và FFprobe portable bắt buộc đặt trong thư mục `tools/`.
- Giữ giao diện người dùng luôn phản hồi mượt mà, không đơ lag khi xử lý media.
- Luôn xuất ra file mới, không bao giờ ghi đè hoặc sửa đổi video gốc.

## Review Focus
1. Video không có I-frame ở mốc bắt đầu: Cần tự động tìm Keyframe gần nhất trước điểm chọn để tránh hiện tượng đứng hình hoặc đen khung đầu.
2. File đích trùng tên file nguồn: Phải tự sinh tên mới có hậu tố `_cut_...` hoặc báo lỗi, tuyệt đối không ghi đè.
3. Người dùng chọn mốc `End` <= `Start`: Phải có validation ngăn chặn và cảnh báo người dùng trước khi gọi FFmpeg.
4. Đường dẫn file chứa ký tự đặc biệt hoặc tiếng Việt có dấu: Phải xử lý chuỗi UTF-8 an toàn khi truyền tham số cho subprocess/FFmpeg.
5. Tiến trình cắt bị hủy giữa chừng hoặc gặp lỗi: Phải dọn dẹp file tạm/file dở dang và giải phóng tiến trình ngầm.

---

### Task 1: Cấu hình môi trường & Quản lý công cụ Portable
**Files:**
- Create: `requirements.txt`
- Create: `src/core/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `get_ffmpeg_path() -> str`, `get_ffprobe_path() -> str`, `validate_tools() -> dict[str, bool]`

- [ ] **Step 1: Viết test cho `config.py`**
```python
def test_config_paths():
    from src.core.config import get_ffmpeg_path, get_ffprobe_path
    assert "tools" in get_ffmpeg_path()
    assert "tools" in get_ffprobe_path()
```

- [ ] **Step 2: Viết `requirements.txt` với `PySide6`**
- [ ] **Step 3: Cài đặt `src/core/config.py` định vị đường dẫn binary `ffmpeg.exe` và `ffprobe.exe` trong `tools/`**
- [ ] **Step 4: Chạy kiểm thử xác minh `config.py`**

---

### Task 2: Module phân tích Video & Trích xuất Keyframe
**Files:**
- Create: `src/core/probe.py`
- Test: `tests/test_probe.py`

**Interfaces:**
- Consumes: `get_ffprobe_path() -> str` từ `src/core/config.py`
- Produces: `probe_video_info(video_path: str) -> dict`, `get_keyframe_timestamps(video_path: str) -> list[float]`

- [ ] **Step 1: Viết test cho `probe.py` với cấu trúc JSON mô phỏng của `ffprobe`**
- [ ] **Step 2: Cài đặt hàm `probe_video_info(video_path)` sử dụng `ffprobe` đọc duration, fps, resolution, audio/video streams**
- [ ] **Step 3: Cài đặt hàm `get_keyframe_timestamps(video_path)` để lấy danh sách timestamp của tất cả các I-frame**
- [ ] **Step 4: Chạy test xác minh dữ liệu bóc tách chính xác**

---

### Task 3: Core Engine Cắt Video Lossless (Stream Copy)
**Files:**
- Create: `src/core/cutter.py`
- Test: `tests/test_cutter.py`

**Interfaces:**
- Consumes: `get_ffmpeg_path()` từ `src/core/config.py`
- Produces: `build_cut_command(input_path: str, output_path: str, start_sec: float, end_sec: float, keyframe_snap: bool, keyframes: list[float]) -> list[str]`

- [ ] **Step 1: Viết test xác minh câu lệnh FFmpeg được sinh ra với các cờ `-c copy`, `-avoid_negative_ts make_zero`, `-map 0`**
- [ ] **Step 2: Cài đặt logic snap Keyframe: tìm `start_sec` hợp lệ gần nhất trong danh sách `keyframes`**
- [ ] **Step 3: Xử lý an toàn đường dẫn và kiểm tra validation `start_sec < end_sec`**
- [ ] **Step 4: Chạy test xác minh câu lệnh chuẩn xác**

---

### Task 4: Background Worker & Theo dõi Tiến trình
**Files:**
- Create: `src/core/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `build_cut_command(...)` từ `src/core/cutter.py`
- Produces: Class `CutWorker(QThread)` với Signals: `progress_changed(float)`, `finished(str)`, `failed(str)`

- [ ] **Step 1: Viết test cho hàm parse tiến trình từ dòng log stderr của FFmpeg: `parse_ffmpeg_progress(stderr_line: str, total_duration: float) -> float`**
- [ ] **Step 2: Cài đặt `CutWorker` kế thừa `QThread`, thực thi tiến trình con qua `subprocess.Popen` không làm block giao diện**
- [ ] **Step 3: Bổ sung khả năng hủy tiến trình (`cancel()`) và dọn dẹp file dở dang**
- [ ] **Step 4: Chạy test xác minh tính ổn định của worker**

---

### Task 5: Component Player & Timeline Widget (PySide6)
**Files:**
- Create: `src/ui/timeline_widget.py`
- Create: `src/ui/player_widget.py`

**Interfaces:**
- Produces:
  - `TimelineWidget`: hiển thị thanh thời gian, mốc In (bắt đầu), mốc Out (kết thúc), signal `in_point_changed(float)`, `out_point_changed(float)`
  - `PlayerWidget`: hiển thị khung video với `QMediaPlayer` + `QVideoWidget`, các nút Play, Pause, Step frame

- [ ] **Step 1: Tạo `TimelineWidget` với thanh trượt kép hoặc thanh trượt có đánh dấu mốc In/Out**
- [ ] **Step 2: Tạo `PlayerWidget` hỗ trợ xem trước video và đồng bộ thời gian với `TimelineWidget`**
- [ ] **Step 3: Bổ sung phím tắt: `Space` (Play/Pause), `I` (Đặt mốc In), `O` (Đặt mốc Out)**

---

### Task 6: Cửa sổ chính & Ghép nối Hoàn chỉnh Ứng dụng
**Files:**
- Create: `src/ui/main_window.py`
- Create: `src/main.py`

**Interfaces:**
- Ghép nối `PlayerWidget`, `TimelineWidget`, `CutWorker` vào cửa sổ chính `MainWindow`

- [ ] **Step 1: Xây dựng bố cục `MainWindow`: Thanh công cụ mở file / kéo thả video, khu vực Player, khu vực Timeline, khu vực Thiết lập xuất file**
- [ ] **Step 2: Kết nối tín hiệu nút "Xuất Video (Lossless)" với `CutWorker`**
- [ ] **Step 3: Hiển thị thanh tiến trình thực tế (Progress Bar) và hộp thoại thông báo kết quả**
- [ ] **Step 4: Viết file khởi chạy ứng dụng `src/main.py`**

