# Thiết Kế Chi Tiết: Tính Năng Cắt Từng Track Độc Lập (Per-Track Cutting)

- **Ngày tạo**: 2026-10-14
- **Trạng thái**: Bản thảo thiết kế chờ xác nhận (Draft for Review)
- **Hệ thống áp dụng**: Lossless Video Cutter (PySide6 + FFmpeg)

---

## 1. Bối cảnh & Mục tiêu

### 1.1. Hiện trạng
Hiện tại, ứng dụng Lossless Video Cutter hoạt động theo cơ chế **Cắt Đồng Bộ (Global Cut)**:
- Người dùng đặt một cặp mốc duy nhất: **Điểm Bắt Đầu (In)** và **Điểm Kết Thúc (Out)** trên thước đo thời gian (Ruler).
- Tất cả các track được chọn giữ lại (Video, Audio #1, Audio #2, Audio #3,...) đều bị cắt cùng một khoảng thời gian $[In, Out]$ với tùy chọn bám Keyframe.

### 1.2. Nhu cầu người dùng
Người dùng muốn có khả năng **cắt từng track với mốc thời gian độc lập** (ví dụ: Track Video cắt từ `00:10` đến `00:40`, nhưng Track Audio #2 chỉ lấy từ `00:15` đến `00:30`), đồng thời:
1. **Giữ nguyên 100% đồng bộ thời gian (Sync Timeline)**: Trong video xuất ra, Audio #2 sẽ im lặng ở 5 giây đầu (`00:00 - 00:05` của file mới), phát từ giây thứ 5 đến giây thứ 20 (khớp với `00:15 - 00:30` của video gốc), và im lặng ở phần còn lại.
2. **Bảo toàn 100% chất lượng Video Lossless**: Không re-encode lại video (giữ nguyên codec AV1, HEVC, H.264,... độ phân giải 2K+ @ 120 FPS không mất chất lượng).
3. **Thao tác đơn giản, trực quan**: Dễ dàng chuyển đổi giữa chế độ Cắt Chung và Cắt Từng Track mà không làm rối giao diện.

---

## 2. Mô hình Ràng buộc Cốt lõi: Master-Child Constraint

Để giải quyết triệt để vấn đề âm thanh bắt đầu trước hình ảnh (khiến video bị hụt frame hoặc bắt buộc phải re-encode để chèn hình đen), hệ thống áp dụng mô hình **Master-Child Constraint**:

```
        00:00        00:10                  00:30             00:40        00:53
Timeline: ----------------------------------------------------------------------
Video:               [======= 100% LOSSLESS VIDEO =======]       (Master: 10s -> 40s)
Audio #1:            [======= Âm thanh khớp 100% =======]       (10s -> 40s: Lossless)
Audio #2:                   [=== Chỉ lấy đoạn này ===]           (15s -> 30s: Chèn lặng đầu/cuối)
                     ↑                                   ↑
                     In_Video                            Out_Video
```

### 2.1. Quy tắc Master (Track Video)
1. **Khung thời gian gốc**: Mốc $[In_{video}, Out_{video}]$ của Track Video là khung giới hạn bao phủ (Bounding Box) cho toàn bộ file xuất ra. Thời lượng video xuất ra:
   $$T_{output} = Out_{video} - In_{video}$$
2. **Lossless Stream Copy**: Video luôn được cắt 100% Lossless bằng `-c:v copy` và bám Keyframe mượt mà.

### 2.2. Quy tắc Child (Các Track Audio)
1. **Giới hạn phạm vi**: Mọi track Audio luôn thỏa mãn bất đẳng thức:
   $$In_{video} \le In_{audio} < Out_{audio} \le Out_{video}$$
2. **Cơ chế Kéo dồn tự động (Auto-Pull / Cascade Clamping)**:
   - Khi người dùng tăng $In_{video}$ (thu hẹp đầu video): Bất kỳ track audio nào có $In_{audio} < In_{video}$ sẽ tự động bị kéo dồn lên bằng $In_{video}$.
   - Khi người dùng giảm $Out_{video}$ (thu hẹp đuôi video): Bất kỳ track audio nào có $Out_{audio} > Out_{video}$ sẽ tự động bị kéo lùi về bằng $Out_{video}$.
   - Khi người dùng mở rộng $In_{video}$ hoặc $Out_{video}$: Các track audio giữ nguyên mốc độc lập đã cấu hình trước đó, không bị xáo trộn.

---

## 3. Thiết kế Giao diện Người dùng (UI / UX)

### 3.1. Thanh công cụ Timeline (Timeline Controls Bar)
Bổ sung một nút chuyển đổi chế độ cắt ngay cạnh cụm nút In/Out:
- **`[ 🔗 Cắt đồng bộ ]`** *(Mặc định)*:
  - Màu xám/xanh dịu (`#2c313c`).
  - Thao tác đặt In/Out hoặc kéo mốc trên ruler sẽ áp dụng cho tất cả các track cùng lúc.
- **`[ 🎯 Cắt từng track ]`**:
  - Khi được bật, nút đổi sang màu xanh nổi bật (`#0084ff`).
  - Hiển thị nhãn trạng thái track đang chọn: `Đang chỉnh: [🎬 Video]` hoặc `Đang chỉnh: [🎵 Audio #2]`.

### 3.2. Tương tác chọn track (Track Selection)
- Trong danh sách `TRACKS` bên trái hoặc trên từng hàng của Timeline:
  - Nhấp chuột vào hàng nào thì hàng đó được viền sáng màu Cyan (`#00d2d3`) và trở thành **Track Đang Chọn (Active Track)**.
  - Các nút `📍 Đặt In [I]`, `🏁 Đặt Out [O]` và nhãn `In: ...`, `Out: ...` sẽ hiển thị và thay đổi giá trị riêng cho track đang chọn đó.
  - Phím tắt bàn phím `I` và `O` sẽ tác động trực tiếp lên track đang chọn.

### 3.3. Hiển thị rãnh đa tầng trên TimelineCanvas
- **Trên Thước đo (Ruler)**: Hiển thị cờ `I` và `O` của Master Track (Video).
- **Trên từng rãnh track (Lanes)**:
  - **Đoạn được chọn $[In_{track}, Out_{track}]$**: Hiển thị đầy đủ màu sắc rực rỡ (Video filmstrip, Waveform sóng âm).
  - **Đoạn bị loại trừ** ($t < In_{track}$ hoặc $t > Out_{track}$): Phủ một lớp làm mờ bán trong suốt `rgba(10, 12, 16, 185)` kèm họa tiết sọc chéo tinh tế và biểu tượng Mute mờ.
  - Người dùng chỉ cần nhìn lướt qua Timeline là nhận diện ngay track nào bắt đầu ở đâu và kết thúc ở đâu.

---

## 4. Thiết kế Engine Xử lý FFmpeg (`src/core/cutter.py`)

### 4.1. Cấu trúc hàm `build_cut_command`
Nâng cấp hàm `build_cut_command` nhận thêm tham số `track_ranges`:
```python
def build_cut_command(
    input_path: str | Path,
    output_path: str | Path,
    start_sec: float,
    end_sec: float,
    snap_keyframe: bool = True,
    keyframes: list[float] | None = None,
    selected_stream_indices: list[int] | None = None,
    track_ranges: dict[int, tuple[float, float]] | None = None,
) -> tuple[list[str], float, float]:
```

### 4.2. Thuật toán phân luồng Smart Hybrid Sync
1. **Xác định mốc Master**:
   - $base\_start = start\_sec$ (mốc In của video).
   - $base\_end = end\_sec$ (mốc Out của video).
   - Nếu `snap_keyframe=True`, bám Keyframe cho $base\_start$: $eff\_start = find\_nearest\_keyframe(base\_start, keyframes)$.
   - $eff\_end = base\_end$.
   - Thời lượng video chuẩn: $dur = eff\_end - eff\_start$.

2. **Phân tích từng Track âm thanh**:
   - Với mỗi track audio có `stream_index`:
     - Lấy khoảng cắt của track: $(in_a, out_a) = track\_ranges.get(stream\_index, (eff\_start, eff\_end))$.
     - Giới hạn: $in_a = \max(eff\_start, in_a)$, $out_a = \min(eff\_end, out_a)$.
     - **Trường hợp A (Khớp hoàn toàn với video: $in_a == eff\_start$ và $out_a == eff\_end$)**:
       - Áp dụng **100% Lossless Stream Copy**: `-c:a:<N> copy`.
     - **Trường hợp B (Bị cắt ngắn hoặc lệch mốc so với video)**:
       - Tính độ trễ đầu: $\Delta t_{delay} = \max(0.0, in_a - eff\_start)$ (giây).
       - Tính độ dài đoạn audio: $dur_a = out_a - in_a$ (giây).
       - Chuỗi Filter âm thanh:
         `atrim=start={in_a:.4f}:end={out_a:.4f},asetpts=PTS-STARTPTS,adelay={delay_ms}|{delay_ms}:all=1,apad`
       - Mã hóa luồng audio đó với chất lượng tối đa: `-c:a:<N> aac -b:a:<N> 320k`.
       - *Thời gian xử lý*: Cực nhanh (<0.2 giây cho luồng audio), không ảnh hưởng đến tốc độ của ứng dụng.

3. **Luồng Video**:
   - Luôn sử dụng `-c:v copy` để đảm bảo 100% bit-for-bit nguyên bản.

---

## 5. Kế hoạch Kiểm thử & Xác minh (Verification Plan)

| Trường hợp kiểm thử (Test Case) | Dữ liệu đầu vào | Kết quả kỳ vọng |
| :--- | :--- | :--- |
| **TC1: Chế độ Cắt Chung (Backward Compatibility)** | Cắt đồng bộ 10s -> 30s | Lệnh FFmpeg dùng 100% `-c copy` như cũ, video và tất cả track audio khớp chính xác. |
| **TC2: Cắt Track Audio ngắn hơn Video** | Video: 10s - 40s. Audio #1: 15s - 30s | Video 100% copy. Audio #1 có 5s đầu im lặng, phát từ giây 5 đến 20, sau đó im lặng. |
| **TC3: Auto-pull Clamping** | Video: 15s - 40s. Kéo Audio về 10s | Hệ thống tự động chặn hoặc kéo In của Audio về bằng 15s (không cho vượt ngoài video). |
| **TC4: Thu hẹp Video kéo theo Audio** | Ban đầu Video 10s, Audio 12s. Người dùng kéo Video lên 20s | Audio tự động nhảy lên 20s để không vượt ra ngoài. |
| **TC5: Độ tương thích file xuất** | Mở file xuất ra trên VLC, Windows Media Player, CapCut | Hình và tiếng khớp 100%, không bị lệch tiếng hoặc giật hình. |

---

