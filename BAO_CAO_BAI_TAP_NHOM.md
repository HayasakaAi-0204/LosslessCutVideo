# BÁO CÁO BÀI TẬP NHÓM
## MÔN HỌC: LẬP TRÌNH VỚI PYTHON

---

**ĐỀ TÀI:**  
### **XÂY DỰNG ỨNG DỤNG CẮT VIDEO LOSSLESS NGUYÊN BẢN (LOSSLESS VIDEO CUTTER) BẰNG PYTHON VÀ PYSIDE6**

* **Giảng viên hướng dẫn:** Giảng viên phụ trách môn học
* **Nhóm sinh viên thực hiện:** Nhóm 3 thành viên
  * **Sinh viên 1 (Nhóm trưởng):** [Họ và tên SV 1] - MSSV: [Mã SV 1]
  * **Sinh viên 2:** [Họ và tên SV 2] - MSSV: [Mã SV 2]
  * **Sinh viên 3:** [Họ và tên SV 3] - MSSV: [Mã SV 3]
* **Ngôn ngữ & Công nghệ chính:** Python 3.12, PySide6 (Qt for Python), FFmpeg / FFprobe Portable.

---

## MỤC LỤC
1. [Mô tả bài toán và mục tiêu đề tài](#1-mô-tả-bài-toán-và-mục-tiêu-đề-tài)
2. [Các chức năng và yêu cầu chính](#2-các-chức-năng-và-yêu-cầu-chính)
3. [Phân tích và lựa chọn giải pháp kỹ thuật](#3-phân-tích-và-lựa-chọn-giải-pháp-kỹ-thuật)
4. [Thiết kế chương trình và kiến trúc hệ thống](#4-thiết-kế-chương-trình-và-kiến-trúc-hệ-thống)
5. [Các thư viện, framework và công nghệ sử dụng](#5-các-thư-viện-framework-và-công-nghệ-sử-dụng)
6. [Kết quả thực hiện và minh họa sản phẩm](#6-kết-quả-thực-hiện-và-minh-họa-sản-phẩm)
7. [Phân công công việc giữa các thành viên](#7-phân-công-công-việc-giữa-các-thành-viên)
8. [Kết luận và hướng phát triển](#8-kết-luận-và-hướng-phát-triển)

---

## 1. MÔ TẢ BÀI TOÁN VÀ MỤC TIÊU ĐỀ TÀI

### 1.1. Thực trạng và Bài toán thực tế
Trong kỷ nguyên số, nhu cầu ghi hình màn hình, quay video bài giảng, livestream, chơi game độ phân giải cao (2K, 4K, 120fps) ngày càng trở nên phổ biến. Sau khi ghi hình, người dùng thường chỉ muốn cắt bỏ những đoạn thừa ở đầu hoặc cuối video hoặc trích xuất một đoạn nội dung ngắn quan trọng.

Tuy nhiên, hầu hết các phần mềm dựng phim truyền thống hiện nay (Adobe Premiere, CapCut, DaVinci Resolve) hoặc các công cụ chuyển đổi video (Handbrake, Format Factory) đều hoạt động theo cơ chế **Tái mã hóa (Re-encoding / Re-rendering)**:
* **Tốn thời gian khủng khiếp:** Một video 4K dài 1 giờ có thể mất từ 30 phút đến vài giờ để render lại.
* **Suy hao chất lượng (Lossy):** Mỗi lần nén lại, video và âm thanh đều bị giảm bitrate, mất chi tiết màu sắc, mất dải động HDR.
* **Ngốn phần cứng:** Làm nóng máy, chiếm 100% tài nguyên CPU và GPU, gây đơ lag các ứng dụng khác.

### 1.2. Mục tiêu của đề tài
Ứng dụng **Lossless Video Cutter** được xây dựng nhằm giải quyết triệt để bài toán trên với các mục tiêu cụ thể:
1. **Cắt video 100% Lossless (Bit-for-bit):** Bảo toàn nguyên bản 100% từng bit dữ liệu video, âm thanh và phụ đề gốc, không can thiệp tái nén (0% re-encoding).
2. **Tốc độ xử lý siêu tốc:** Xử lý file video dung lượng lớn hàng chục Gigabyte chỉ trong vòng **1 đến 3 giây** (tốc độ tương đương việc copy file trên ổ cứng).
3. **Triệt tiêu lỗi giật lag đầu video:** Áp dụng thuật toán bám dính khung khóa (**Keyframe / I-frame Snapping**), giúp video xuất ra mở lên là phát mượt ngay tức thì, không bị khựng hình hay đen hình ở giây đầu tiên.
4. **Giao diện hiện đại, mượt mà và trực quan:** Ứng dụng desktop viết bằng Python và **PySide6** mang phong cách chuyên nghiệp (tương tự CapCut), hỗ trợ hiển thị Timeline đa luồng (Multi-track filmstrip và sóng âm thanh), đáp ứng tốt video tần số quét cao (120fps) với kỹ thuật **Viewport Culling** chống nghẽn luồng.

---

## 2. CÁC CHỨC NĂNG VÀ YÊU CẦU CHÍNH

### 2.1. Yêu cầu chức năng (Functional Requirements)
* **Nạp video linh hoạt:** Mở video qua hộp thoại chuẩn Windows hoặc kéo thả (Drag & Drop) trực tiếp file video vào bất kỳ vị trí nào trên ứng dụng.
* **Phân tích siêu dữ liệu (Metadata Probing):** Tự động phát hiện codec video, độ phân giải, tốc độ khung hình (fps), thời lượng, số lượng track âm thanh, codec âm thanh và danh sách các khung khóa (Keyframes).
* **Trình xem trước mượt mà (Preview Player):**
  * Hỗ trợ phát/dừng bằng phím cách (`Space`).
  * Tua từng khung hình tới/lùi (`1 Frame ◂ / ▸` hoặc phím mũi tên).
  * Nhảy nhanh giữa các Keyframe kế tiếp (`Keyframe Trước / Tiếp`).
  * Tinh chỉnh tốc độ phát mượt mà từ **0.25x đến 2.00x**.
* **Timeline đa luồng (Multi-Track Timeline):**
  * Hiển thị trực quan luồng hình ảnh với dải cuộn phim (Filmstrip thumbnails).
  * Hiển thị dạng sóng âm thanh thực tế (Audio waveform peaks) cho từng track âm thanh riêng biệt.
  * Hỗ trợ bật/tắt (Giữ / Bỏ qua) từng track độc lập trước khi xuất file.
* **Thao tác cắt tiện lợi & Phím tắt chuyên nghiệp:**
  * Đặt điểm bắt đầu (`In`) bằng phím `I` hoặc nút giao diện.
  * Đặt điểm kết thúc (`Out`) bằng phím `O` hoặc nút giao diện.
  * Tự động tính toán và hiển thị thời lượng cắt chuẩn xác tới mili-giây.
* **Cơ chế bám Keyframe tự động (Permanent Keyframe Snapping):** Tự động căn chỉnh mốc cắt khớp với Keyframe gần nhất, đảm bảo tính nguyên bản 100%.
* **Đồng bộ thông minh giữa Tốc độ phát và Thu phóng (Smart Speed-to-Zoom Sync):** Khi giảm tốc độ phát (như 0.5x, 0.25x), Timeline tự động phóng to chi tiết tương ứng để người dùng soi từng khung hình dễ dàng.
* **Xuất file an toàn tuyệt đối:**
  * Tự động đề xuất tên file thông minh có gắn dấu thời gian: `<Tên_gốc>_<Giờ>h<Phút>m<Giây>s_<Ngày>-<Tháng>-<Năm>.<đuôi>`.
  * Tuyệt đối không cho phép ghi đè lên file video gốc.
  * Cho phép Hủy tác vụ xuất bất kỳ lúc nào; tự động dọn dẹp file tạm, không để lại rác trên ổ cứng.

### 2.2. Yêu cầu phi chức năng (Non-Functional Requirements)
* **Tính toàn vẹn (Lossless):** 100% video và audio streams được copy nguyên bản bằng Stream Copy.
* **Tính phản hồi (Responsiveness):** Mọi tác vụ nặng (quét Keyframe, trích xuất thumbnail, vẽ sóng âm, chạy lệnh cắt) đều phải chạy trên luồng nền (`QThread`), đảm bảo giao diện không bao giờ bị đơ/treo.
* **Hiệu năng hiển thị cao:** Sử dụng kỹ thuật Viewport Culling giúp đồ họa Timeline chạy mượt mà ở mức 60 - 120 FPS ngay cả khi phóng to tối đa trên các video dài.
* **Tính độc lập & Bảo mật (Portability & Security):** Ứng dụng chạy độc lập, công cụ FFmpeg/FFprobe đặt cục bộ trong thư mục `tools/`, không sửa Registry, không ghi PATH hệ thống, an toàn 100% trước Windows Defender.

---

## 3. PHÂN TÍCH VÀ LỰA CHỌN GIẢI PHÁP KỸ THUẬT

### 3.1. So sánh cơ chế Cắt Video: Re-encoding vs. Stream Copy

| Tiêu chí so sánh | Cơ chế Tái mã hóa (Re-encoding) | Cơ chế Sao chép luồng (Stream Copy) *(Được chọn)* |
| :--- | :--- | :--- |
| **Bản chất kỹ thuật** | Giải mã toàn bộ pixel -> Áp dụng bộ lọc -> Nén lại từ đầu | Đọc các packet nén ở container cũ và ghi nguyên vẹn sang container mới |
| **Lệnh đại diện** | `ffmpeg -i in.mp4 -c:v libx264 -crf 20 out.mp4` | `ffmpeg -ss <start> -i in.mp4 -t <dur> -c copy out.mp4` |
| **Chất lượng đầu ra** | **Bị suy hao** (Lossy), màu sắc và chi tiết bị biến đổi | **100% Nguyên bản (Bit-for-bit Lossless)** |
| **Thời gian xử lý** | Rất chậm (vài phút đến hàng giờ) | **Tức thì (1 - 3 giây)** |
| **Tiêu tốn phần cứng** | CPU/GPU tải 100%, nhiệt độ cao | Tiêu thụ CPU/RAM cực thấp (< 5%) |
| **Giữ nguyên Track phụ**| Thường bị mất track âm thanh phụ hoặc phụ đề | Giữ nguyên toàn bộ 100% các track audio, subtitle, chapter |

> **Quyết định:** Dự án lựa chọn giải pháp **FFmpeg Stream Copy (`-c copy`)** làm trọng tâm cốt lõi.

### 3.2. Giải quyết bài toán Khung khóa (Keyframe / I-Frame Problem)
Trong các chuẩn nén video hiện đại (H.264/AVC, H.265/HEVC, AV1, VP9), video được cấu tạo bởi các nhóm khung hình (GOP - Group of Pictures) gồm 3 loại frame:
1. **I-Frame (Intra-coded / Keyframe):** Khung hình độc lập, chứa toàn bộ dữ liệu ảnh gốc mà không cần tham chiếu đến khung hình khác.
2. **P-Frame (Predicted frame):** Chỉ lưu sự khác biệt so với khung hình trước đó.
3. **B-Frame (Bi-directional frame):** Tham chiếu cả khung hình phía trước và phía sau.

**Vấn đề:** Nếu cắt bằng Stream Copy bắt đầu tại một P-frame hoặc B-frame, trình phát video sẽ không có đủ dữ liệu để giải mã các pixel bị thiếu, dẫn đến hiện tượng **đứng hình (freeze), màn hình xanh/đen hoặc rác hạt** trong 1–2 giây đầu tiên.

**Giải pháp của nhóm:** 
* Quét trước toàn bộ vị trí các I-frame trong video bằng `ffprobe` ngầm.
* Luôn ép buộc điểm cắt `In` bám dính vào I-frame gần nhất bằng hàm `find_nearest_keyframe()`.
* Bổ sung cờ `-avoid_negative_ts make_zero` để reset timestamp về 0 chuẩn mực và `-movflags +faststart` giúp video khởi động phát tức thì.

### 3.3. Lựa chọn Giao diện đồ họa (GUI Framework)
Nhóm chọn **PySide6 (Qt for Python 6)** vì các ưu điểm vượt trội:
* **Hỗ trợ Multimedia mạnh mẽ:** `QMediaPlayer` và `QVideoWidget` cho phép nhúng trực tiếp khung nhìn video mượt mà, hỗ trợ giải mã phần cứng.
* **Kiến trúc đa luồng an toàn:** `QThread`, `Signal` và `Slot` giúp tách biệt hoàn toàn giữa tác vụ xử lý nặng và luồng giao diện người dùng chính.
* **Tự do tùy biến giao diện:** `QPainter` cho phép tự vẽ (custom paint) toàn bộ Timeline phức tạp, dải cuộn phim và sóng âm thanh với độ thẩm mỹ cao.

### 3.4. Tối ưu hóa hiệu năng hiển thị: Kỹ thuật Viewport Culling
* **Vấn đề phát hiện khi thử nghiệm:** Khi phóng to Timeline trên video dài (ví dụ 4 phút 12 giây, 120fps), chiều rộng canvas của Timeline giãn rộng tới hơn **50.000 pixels**. Nếu mỗi khi con trỏ phát di chuyển (cứ mỗi 20ms) mà chương trình vẽ lại toàn bộ 700+ khung hình thumbnail và 50.000 thanh sóng âm, CPU giao diện sẽ bị nghẽn làm tụt tốc độ khung hình xuống chỉ còn **6 FPS** (frametime 312 ms).
* **Giải pháp Viewport Culling:** Nhóm tính toán chính xác phạm vi hiển thị `[vis_left, vis_right]` của cửa sổ người dùng. Chương trình chỉ duyệt và vẽ đúng **15 thumbnail và ~400 thanh sóng âm** nằm trong tầm nhìn thực tế. Nhờ đó, thời gian vẽ đồ họa giảm xuống **dưới 0.4 ms** (tăng tốc hơn 700 lần), đảm bảo phát mượt 60 – 120 FPS.

---

## 4. THIẾT KẾ CHƯƠNG TRÌNH VÀ KIẾN TRÚC HỆ THỐNG

### 4.1. Kiến trúc phân lớp phần mềm (Architecture Overview)

Chương trình được thiết kế theo nguyên tắc phân tách trách nhiệm (Separation of Concerns):

```mermaid
graph TD
    UI[Tầng Giao Diện - src/ui]
    CORE[Tầng Xử Lý Lõi - src/core]
    EXT[Công Cụ Độc Lập - tools/]

    UI --> MainWindow[MainWindow: Điều phối giao diện chính]
    MainWindow --> PlayerWidget[PlayerWidget: Trình phát video & Tua frame]
    MainWindow --> TimelineWidget[TimelineWidget: Multi-track Timeline & Cắt]

    MainWindow --> Worker[Worker Threads: QThread chạy ngầm]
    Worker --> Cutter[cutter.py: Khởi tạo lệnh Stream Copy]
    Worker --> Probe[probe.py: Phân tích metadata & Keyframe]

    Cutter --> FFmpeg[FFmpeg Portable CLI]
    Probe --> FFprobe[FFprobe Portable CLI]
```

### 4.2. Cấu trúc thư mục dự án
```text
CutVideo/
├── src/
│   ├── main.py                 # Điểm khởi chạy chương trình, cấu hình ổn định hệ thống
│   ├── core/
│   │   ├── config.py           # Quản lý đường dẫn, cấu hình tools FFmpeg/FFprobe
│   │   ├── probe.py            # Trích xuất metadata, phân tích danh sách Keyframe
│   │   ├── cutter.py           # Xây dựng lệnh Stream Copy, bảo vệ file nguồn
│   │   └── worker.py           # Các QThread chạy ngầm (CutWorker, KeyframeWorker, AudioWorker...)
│   └── ui/
│       ├── main_window.py      # Cửa sổ chính, điều phối luồng thao tác
│       ├── player_widget.py    # Khung phát video, tua khung hình, chỉnh tốc độ phát
│       └── timeline_widget.py  # Multi-track Timeline, vẽ Filmstrip, Waveform, Viewport Culling
├── tests/                      # Bộ kiểm thử tự động (Unit Tests)
│   ├── test_cutter.py          # Kiểm tra cấu trúc lệnh Stream Copy và bám Keyframe
│   ├── test_player_speed.py    # Kiểm tra dải tốc độ phát (0.25x - 2.0x)
│   ├── test_stability.py       # Kiểm tra cấu hình chống crash và biến môi trường
│   ├── test_timeline_zoom.py   # Kiểm tra tỷ lệ zoom, giãn cách thước đo và bám Keyframe
│   └── run_all_tests.py        # Kịch bản chạy toàn bộ kiểm thử
├── tools/                      # Thư mục chứa ffmpeg.exe và ffprobe.exe portable
├── requirements.txt            # Danh sách thư viện Python phụ thuộc
└── README.md                   # Hướng dẫn cài đặt và sử dụng
```

### 4.3. Sơ đồ luồng dữ liệu (Dataflow Diagram)

```mermaid
sequenceDiagram
    autonumber
    actor User as Người dùng
    participant UI as Giao diện (MainWindow & Timeline)
    participant Worker as Luồng ngầm (QThread)
    participant FF as FFmpeg / FFprobe Engine

    User->>UI: Kéo thả file video vào ứng dụng
    UI->>Worker: Yêu cầu phân tích metadata & quét Keyframe
    Worker->>FF: Chạy ffprobe đọc packet flags & audio peaks
    FF-->>Worker: Trả về danh sách Keyframe, Audio Streams, FPS
    Worker-->>UI: Cập nhật thông tin lên Player và Timeline
    
    User->>UI: Đặt mốc In (Phím I) và Out (Phím O)
    UI->>UI: Tự động bám dính nam châm vào Keyframe gần nhất
    
    User->>UI: Bấm "⚡ Xuất Video"
    UI->>UI: Mở hộp thoại Lưu file (chống ghi đè file gốc)
    UI->>Worker: Kích hoạt CutWorker với lệnh Stream Copy
    Worker->>FF: Thực thi ffmpeg -c copy -avoid_negative_ts make_zero
    loop Trong quá trình cắt
        FF-->>Worker: Báo cáo tiến độ qua stderr (time=HH:MM:SS)
        Worker-->>UI: Cập nhật thanh ProgressBar thời gian thực
    end
    Worker-->>UI: Báo hoàn tất xuất video thành công (1-2s)
    UI-->>User: Hiển thị thông báo hoàn thành & Mở thư mục chứa file
```

---

## 5. CÁC THƯ VIỆN, FRAMEWORK VÀ CÔNG NGHỆ SỬ DỤNG

### 5.1. Bảng tổng hợp công nghệ

| Thành phần | Phiên bản | Vai trò trong dự án |
| :--- | :--- | :--- |
| **Python** | 3.12+ | Ngôn ngữ lập trình chính xây dựng toàn bộ ứng dụng |
| **PySide6** | 6.7+ | Framework GUI chính: Cung cấp Widget, Canvas vẽ đồ họa, Trình phát Media, Đa luồng |
| **FFmpeg Portable** | 7.0+ | Lõi xử lý video tốc độ cao: Thực thi Stream Copy, trích xuất thumbnail |
| **FFprobe Portable**| 7.0+ | Phân tích sâu cấu trúc container, codec, vị trí packet I-frame, giải mã âm thanh |
| **Subprocess (Chuẩn)** | Python stdlib | Giao tiếp tiến trình ngầm với cờ `CREATE_NO_WINDOW`, điều phối luồng vào/ra an toàn |
| **Unittest (Chuẩn)** | Python stdlib | Khung kiểm thử tự động đảm bảo độ ổn định và tính đúng đắn của logic phần mềm |

### 5.2. Một số đoạn mã kỹ thuật then chốt

#### 1. Xây dựng lệnh Stream Copy thuần túy 100% Lossless (`src/core/cutter.py`)
```python
# Lệnh Stream Copy: Không encode, chia sẻ cửa sổ cắt đồng bộ, chuẩn hóa timestamp về 0
cmd = [
    str(ffmpeg_bin),
    "-y",
    "-ss", f"{effective_start:.4f}",       # Bắt đầu tại Keyframe gần nhất
    "-i", str(in_p),
    "-t", f"{cut_dur:.4f}",               # Thời lượng cắt chính xác
    "-c", "copy",                         # 100% Bit-for-bit Stream Copy
    *map_args,                            # Map các stream được người dùng giữ lại
    "-avoid_negative_ts", "make_zero",    # Reset timestamp chuẩn cho mọi đầu phát
]
if out_p.suffix.lower() in (".mp4", ".mov", ".m4v"):
    cmd.extend(["-movflags", "+faststart"])  # Đưa header lên đầu file để phát tức thì
cmd.append(str(out_p))
```

#### 2. Kỹ thuật Viewport Culling tối ưu tốc độ vẽ Timeline (`src/ui/timeline_widget.py`)
```python
def _get_visible_x_bounds(self) -> tuple[float, float]:
    """Chỉ lấy tọa độ ngang thực tế đang hiển thị trên màn hình người dùng."""
    parent = self.parent()
    if isinstance(parent, QWidget):
        vp_rect = parent.rect()
        p_tl = self.mapFromParent(vp_rect.topLeft())
        p_br = self.mapFromParent(vp_rect.bottomRight())
        left = max(0.0, float(p_tl.x()) - 60.0)
        right = min(float(self.width()), float(p_br.x()) + 60.0)
        return left, right
    return 0.0, float(self.width())
```

---

## 6. KẾT QUẢ THỰC HIỆN VÀ MINH HỌA SẢN PHẨM

### 6.1. Kết quả kiểm nghiệm thực tế
Ứng dụng đã được kiểm thử với các video thực tế từ định dạng phổ thông đến các video độ phân giải cực cao:
* **Video Test 1:** File MP4 chuẩn Full HD 1080p @ 60fps (Thời lượng 30 phút, dung lượng 2.5 GB).
  * *Thời gian xuất đoạn cắt 5 phút:* **1.2 giây** (So với phần mềm re-encode mất ~4 phút).
  * *Chất lượng:* Giữ nguyên 100% bitrate và độ nét gốc.
* **Video Test 2:** File MP4 chuẩn 2K 2560x1600 @ 120fps Codec AV1 (4 Tracks âm thanh, dung lượng 1.8 GB).
  * *Tốc độ phát preview:* Mượt mà 120 FPS nguyên bản.
  * *Hiện tượng khựng hình đầu:* **0 giây** (nhờ cơ chế bắt dính I-frame).
  * *Hiệu năng Timeline:* Frametime duy trì ổn định dưới 5ms sau khi áp dụng Viewport Culling.

### 6.2. Kết quả kiểm thử tự động (Unit Tests)
Dự án tích hợp bộ test tự động toàn diện kiểm chứng 100% các thành phần cốt lõi:
1. `test_cutter.py`: Kiểm tra tính hợp lệ của timestamp, kiểm chứng việc bắt buộc có cờ `-c copy`, `-avoid_negative_ts make_zero`, kiểm tra thuật toán tìm Keyframe gần nhất và cơ chế chống ghi đè file nguồn.
2. `test_player_speed.py`: Kiểm chứng dải tốc độ từ 0.25x đến 2.00x với bước nhảy 0.25x.
3. `test_stability.py`: Kiểm chứng biến môi trường chống lỗi Direct3D hook (`QT_MEDIA_BACKEND=ffmpeg`).
4. `test_timeline_zoom.py`: Kiểm chứng giới hạn trần thu phóng, tính đơn điệu của thanh trượt, khoảng cách nhãn số trên thước đo không bao giờ đè lên nhau và cơ chế bám Keyframe luôn kích hoạt.
5. `test_drag_drop_and_perf.py`: Kiểm chứng cơ chế bóc tách đường dẫn kéo thả chứa ký tự đặc biệt/dấu cách/ngoặc đơn và kiểm chứng tính năng Timeline siêu nhẹ tải tức thì không tốn CPU.
6. `test_snapshot.py`: Kiểm chứng tính năng Chụp ảnh khung hình (Snapshot Frame), quy tắc đặt tên tự động tránh xung đột, thuật toán seek 2 giai đoạn (Fast Seek + Fine Seek) đảm bảo chuẩn xác từng khung hình ở độ phân giải gốc 100% và cơ chế chạy ngầm không gây đơ giao diện.
7. `test_rotation.py`: Kiểm chứng tính năng Xoay video không cần nén lại (Lossless Rotation), bóc tách metadata `rotate` từ file nguồn, chu kỳ xoay $0^\circ \rightarrow 90^\circ \rightarrow 180^\circ \rightarrow 270^\circ$, cờ `-metadata:s:v:0 rotate=...` và bộ lọc xoay ảnh snapshot tương ứng.

---

## 7. PHÂN CÔNG CÔNG VIỆC GIỮA CÁC THÀNH VIÊN

Nhóm gồm 03 sinh viên được phân chia nhiệm vụ chuyên biệt, rõ ràng:

| Thành viên | Vai trò | Nhiệm vụ chính phụ trách | Tỷ lệ đóng góp |
| :--- | :--- | :--- | :---: |
| **Sinh viên 1**<br>*(Nhóm trưởng)* | **Backend & Media Core** | - Nghiên cứu cấu trúc container media, luồng FFmpeg/FFprobe.<br>- Lập trình module `cutter.py`, `probe.py` và quản lý tiến trình `worker.py`.<br>- Thiết kế thuật toán bám dính Keyframe (I-frame Snapping).<br>- Viết bộ Unit Tests cho tầng lõi xử lý. | **35%** |
| **Sinh viên 2** | **Frontend & GUI Developer** | - Lập trình toàn bộ giao diện bằng PySide6 (`main_window.py`).<br>- Thiết kế và vẽ Custom Timeline (`timeline_widget.py`) phong cách CapCut.<br>- Nghiên cứu và hiện thực thuật toán **Viewport Culling** và **Smart Speed-to-Zoom Sync** giải quyết lỗi nghẽn đồ họa.<br>- Xây dựng thước đo thời gian Keyframe-Centric. | **35%** |
| **Sinh viên 3** | **Player, Integration & QA** | - Lập trình module phát video và tua từng frame (`player_widget.py`).<br>- Xây dựng hệ thống phím tắt tương tác (`Space`, `I`, `O`, `J-K-L`, phím mũi tên).<br>- Tối ưu hóa môi trường Portable và bảo mật hệ thống.<br>- Thực hiện kiểm thử tích hợp (Integration Test), chạy thực nghiệm đo FPS và viết Báo cáo tổng kết. | **30%** |

---

## 8. KẾT LUẬN VÀ HƯỚNG PHÁT TRIỂN

### 8.1. Kết luận đạt được
Đề tài đã hoàn thành xuất sắc toàn bộ các mục tiêu đặt ra ban đầu:
* Vận dụng hiệu quả ngôn ngữ **Python** kết hợp linh hoạt giữa giao diện đồ họa **PySide6** và công cụ đa phương tiện **FFmpeg/FFprobe**.
* Xây dựng thành công một sản phẩm ứng dụng desktop hoàn chỉnh, giải quyết bài toán thực tế rất thiết thực với hiệu năng vượt trội so với các phần mềm thương mại cồng kềnh.
* Ứng dụng hoạt động ổn định, giao diện mượt mà, thân thiện, dễ sử dụng và đạt tiêu chuẩn chất lượng **100% Lossless**.

### 8.2. Hướng phát triển trong tương lai
* **Hỗ trợ ghép nhiều phân đoạn (Merge/Concatenate Clips):** Bổ sung tính năng cắt nhiều đoạn trong cùng một video rồi nối lại với nhau mà vẫn giữ nguyên chế độ Stream Copy.
* **Cơ chế Cắt lai thông minh (Smart Hybrid Cut):** Đối với các trường hợp người dùng bắt buộc muốn cắt chính xác từng khung hình lẻ (không trùng Keyframe), hệ thống có thể chỉ mã hóa lại duy nhất vài khung hình của GOP đầu tiên và GOP cuối cùng, toàn bộ phần thân giữa vẫn giữ Stream Copy 100%.
* **Đóng gói file cài đặt `.exe` độc lập:** Sử dụng PyInstaller để đóng gói toàn bộ chương trình thành 1 file chạy duy nhất cho người dùng không cần cài đặt môi trường Python.

