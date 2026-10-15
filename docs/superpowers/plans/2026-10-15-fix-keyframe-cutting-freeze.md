# Khắc phục lỗi đứng hình đầu video và lệch thời lượng khi cắt Video (Keyframe Freeze Fix)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khắc phục triệt để lỗi video xuất bị đen màn hình / đứng hình 2.166 giây đầu và sai lệch thời lượng (11s thay vì 8.33s) khi cắt video bằng cách đồng bộ hóa khóa hút Keyframe trên Timeline và chuẩn hóa câu lệnh FFmpeg Stream Copy / Smart Cut.

**Architecture:**
1. **Timeline Magnetic Snap:** Chuẩn hóa thuật toán bám dính nam châm (Magnetic Snap) trên TimelineWidget: Khi bật "Bám Keyframe", điểm `In` và `Out` sẽ khóa chặt vào mốc Keyframe (I-frame) chính xác, hiển thị ngay trên thước đo và màn hình preview để người dùng biết chính xác khung hình xuất phát.
2. **Cutter Timestamp & Duration Alignment:** Cập nhật `build_cut_command` trong `src/core/cutter.py` để tính toán chính xác `effective_start` và `effective_end` theo Keyframe thực tế, đảm bảo `cut_duration` trong câu lệnh FFmpeg khớp 100% với khoảng thời gian đã chọn, loại bỏ hoàn toàn hiện tượng lệch 3 giây.
3. **FFmpeg Lossless Pipeline Optimization:** Tối ưu các tham số FFmpeg (`-ss`, `-t`, `-avoid_negative_ts`, `-movflags +faststart`) để đảm bảo packet đầu tiên của file xuất luôn là Keyframe hoàn chỉnh có PTS = 0, giúp mọi trình phát (PotPlayer, VLC, Windows Media Player) mở lên là chạy mượt ngay lập tức từ mili-giây đầu tiên.
4. **Smart Cut Fallback (Tùy chọn cắt chính xác từng khung hình):** Hỗ trợ cơ chế cắt ghép thông minh khi người dùng muốn cắt tại mốc không phải Keyframe mà không bị đen hình.

**Tech Stack:** Python 3.10+, PySide6 (Qt GUI), FFmpeg/FFprobe portable (Win64).

**Spec:** Phân tích từ video `bug.mp4` và yêu cầu bảo toàn chất lượng 100% nguyên bản của `GEMINI.md`.

---

## Global Constraints
- Tuân thủ nghiêm ngặt quy tắc trong `GEMINI.md`: Mọi thay đổi trong thư mục gốc dự án, bảo vệ tuyệt đối video nguồn, không ghi đè video gốc.
- Mặc định là cắt Lossless 100% (Stream Copy `-c copy`), không giảm chất lượng hình ảnh/âm thanh và xuất video siêu tốc (< 1-2 giây).
- Không chạy lệnh terminal nếu bị hạn chế; dùng các tool chỉnh sửa file và kiểm thử đơn vị.

---

## Review Focus
1. Video có B-frames và audio offset (như video ghi bằng OBS trong `bug.mp4`) phải phát ngay lập tức từ giây 00:00 mà không bị đen hay drop frame (`CPS`).
2. Thời lượng của file video xuất ra phải bằng đúng `Out - In` hiển thị trên giao diện, không bị kéo dài thêm 2-3 giây.
3. Khi người dùng kéo thả thanh trượt `In`/`Out` với checkbox `Bám Keyframe`, con trỏ phải hút chính xác vào mốc Keyframe gần nhất và hiển thị thời gian chính xác của Keyframe đó.
4. Nếu video chưa quét xong Keyframe hoặc không có Keyframe khả dụng, ứng dụng phải xử lý an toàn (graceful fallback).
5. File video xuất ra phải tương thích hoàn hảo với PotPlayer, VLC và Windows Media Player.

---

### Task 1: Chuẩn hóa tính năng Bám Keyframe và hiển thị đồng bộ trên Timeline

**Files:**
- Modify: `src/ui/timeline_widget.py:1175-1290`
- Test: `tests/test_timeline_snap.py`

**Interfaces:**
- Consumes: `self._keyframes: list[float]` từ `KeyframeWorker`.
- Produces: `timeline_widget.get_in_point() -> float`, `timeline_widget.get_out_point() -> float` luôn là giá trị đã bám đúng Keyframe khi `chk_snap.isChecked() == True`.

- [x] **Step 1: Viết test kiểm tra logic bám Keyframe nam châm**
Tạo file `tests/test_timeline_snap.py` kiểm tra:
```python
def test_snap_to_keyframe_magnetic():
    keyframes = [0.0, 2.5, 5.0, 7.5, 10.0]
    # Khi target ở 2.166, snap_to_keyframe với chế độ bám phải hút về 2.5 hoặc 2.0 tùy cấu hình
    ...
```

- [x] **Step 2: Nâng cấp `snap_to_keyframe` và sự kiện kéo thả trong `timeline_widget.py`**
  - Tăng phạm vi hút bám thông minh (magnetic snapping range) khi người dùng rê chuột gần vạch Keyframe.
  - Khi người dùng buông chuột hoặc gán điểm In bằng nút `[ I ]`, tự động căn chỉnh `_in_point_sec` và `_current_pos_sec` về đúng mốc Keyframe thực tế.
  - Cập nhật nhãn hiển thị `lbl_time_display` và thanh trượt hiển thị đúng thời gian của Keyframe vừa bám, tránh tình trạng giao diện hiện `00:00:02.166` nhưng ngầm định lại xuất ở `00:00:00.000`.

- [x] **Step 3: Vẽ rõ ràng các vạch Keyframe trên Time Ruler và Canvas**
  - Đảm bảo các vạch chia Keyframe màu xanh ngọc (emerald) hiển thị nổi bật trên thanh thước để người dùng dễ dàng nhìn thấy các điểm cắt an toàn không bị giật.

---

### Task 2: Cải tiến bộ sinh lệnh cắt `build_cut_command` trong `src/core/cutter.py`

**Files:**
- Modify: `src/core/cutter.py:80-195`
- Test: `tests/test_cutter.py`

**Interfaces:**
- Consumes: `start_sec: float`, `end_sec: float`, `snap_keyframe: bool`, `keyframes: list[float]`.
- Produces: `(cmd: list[str], effective_start: float, effective_end: float)`.

- [x] **Step 1: Viết test kiểm tra thời lượng cắt và cờ FFmpeg stream copy**
Thêm test trong `tests/test_cutter.py`:
```python
def test_build_cut_command_exact_duration_and_no_freeze(self):
    keyframes = [0.0, 2.5, 5.0, 10.0]
    cmd, eff_start, eff_end = build_cut_command(
        input_path=dummy_in,
        output_path=dummy_out,
        start_sec=2.166,
        end_sec=10.5,
        snap_keyframe=True,
        keyframes=keyframes,
        cut_mode="global",
    )
    # eff_start phải bám về keyframe hợp lý (2.5), eff_end = 10.5 (hoặc snap)
    self.assertAlmostEqual(eff_end - eff_start, 8.0, delta=0.5)
    # Lệnh FFmpeg phải có -ss và -t khớp chính xác
```

- [x] **Step 2: Chuẩn hóa tham số FFmpeg cho chế độ Lossless Stream Copy**
  - Đặt `-ss` trước `-i` với mốc thời gian Keyframe chính xác: `-ss <exact_kf> -i <input>`.
  - Đặt `-t <cut_duration>` sau `-i` với thời lượng tính đúng: `cut_duration = effective_end - effective_start`.
  - Cấu hình `-avoid_negative_ts make_zero` kết hợp `-movflags +faststart` để phần đầu file MP4 có đầy đủ header atom `moov` ở đầu file và PTS của video/audio bắt đầu đồng bộ tại 0.
  - Ngăn chặn triệt để tình trạng lùi âm thanh về 0s trong khi video lùi về điểm khác.

---

### Task 3: Kết nối đồng bộ giữa Giao diện chính `main_window.py` và Exporter

**Files:**
- Modify: `src/ui/main_window.py:470-545`
- Test: Kiểm tra luồng gọi hàm từ `_start_cut`

- [x] **Step 1: Cập nhật `_start_cut` trong `main_window.py`**
  - Trước khi mở hộp thoại Save As, nếu `snap` đang bật, cập nhật điểm `In` và `Out` trên giao diện thành giá trị đã bám Keyframe để người dùng xác nhận trực quan.
  - Hiển thị thời lượng dự kiến chính xác trên nhãn trạng thái: `Dự kiến xuất: XX.X giây (Từ mốc Keyframe A đến mốc B)`.
  - Truyền `snap_mode="closest"` hoặc `"prev"` phù hợp để không bao giờ bị nhảy về `0.0s` nếu người dùng chọn đoạn ở xa giây số 0.

- [x] **Step 2: Đảm bảo luồng quét Keyframe `KeyframeWorker` hoàn tất trước khi xuất**
  - Nếu người dùng bấm Xuất ngay khi vừa mở video mà Keyframe đang quét ngầm, ứng dụng sẽ hiện trạng thái chờ quét xong (thường < 1 giây) để đảm bảo có đầy đủ danh sách Keyframe chuẩn xác.

---

### Task 4: Kiểm thử toàn diện và xác minh chất lượng

**Files:**
- Run: `tests/test_cutter.py`, `tests/test_probe.py`, `tests/test_timeline_snap.py`, `tests/test_config.py`.

- [x] **Step 1: Chạy toàn bộ test suites hiện có**
  - Xác minh tất cả các unit tests đều đạt (PASSED 100%).
- [ ] **Step 2: Hướng dẫn người dùng test thử nghiệm thực tế với video `[105-100]New Record...mp4`**
  - Mở app, chọn đoạn cắt từ mốc ~2.16s đến ~10.5s.
  - Quan sát thanh trượt tự động hút dính vào Keyframe gần nhất.
  - Bấm Xuất Video và mở lại trong PotPlayer: Kiểm tra video bắt đầu ngay tức khắc từ frame đầu tiên, không có màn hình đen, không drop frame CPS và thời lượng khớp đúng 100%.

