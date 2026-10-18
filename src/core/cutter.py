"""Engine cắt video Lossless sử dụng cơ chế FFmpeg Stream Copy.

Bảo toàn 100% chất lượng bit-for-bit nguyên bản, không tái mã hóa (0% re-encoding).
"""

from datetime import datetime
import os
from pathlib import Path
from typing import Any

from src.core.config import get_ffmpeg_path


def format_timestamp(seconds: float) -> str:
    """Định dạng số giây thành chuỗi thời gian dạng HH:MM:SS.mmm."""
    seconds = max(0.0, seconds)
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:06.3f}"


def format_file_size(size_bytes: float) -> str:
    """Định dạng số byte thành chuỗi kích thước dễ đọc (B, KB, MB, GB)."""
    if size_bytes <= 0:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes:.0f} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def estimate_output_file_size(
    cut_duration: float,
    video_info: dict[str, Any] | None,
    active_stream_indices: list[int] | set[int] | None = None,
) -> tuple[float, str]:
    """Ước tính dung lượng file xuất ra (bytes và chuỗi hiển thị có tiền tố ~).

    Bảo đảm xử lý các trường hợp:
    1. Thiếu thông tin bitrate trong metadata (tự động tính từ kích thước file gốc / thời lượng).
    2. Người dùng tắt/bật các track (nếu bỏ track video, chỉ tính bitrate các track audio).
    3. Trừ hao chi phí đóng gói container (Muxing Overhead ~1.5% + 32KB).
    4. Tự động định dạng đơn vị hiển thị KB / MB / GB.

    Trả về:
        tuple (estimated_bytes: float, formatted_text: str)
    """
    if not video_info or cut_duration <= 0.05:
        return 0.0, "~ 0 MB"

    orig_dur = max(0.001, float(video_info.get("duration", 0.0)))
    orig_size = max(0, int(video_info.get("size", 0)))
    tracks = video_info.get("tracks", [])

    # Xác định các stream được chọn
    if active_stream_indices is None:
        active_set = {t.get("stream_index") for t in tracks if "stream_index" in t}
    else:
        active_set = set(active_stream_indices)

    # Phân loại các track được chọn
    selected_tracks = [t for t in tracks if t.get("stream_index") in active_set]
    has_video = any(t.get("codec_type") == "video" for t in selected_tracks)
    selected_audios = [t for t in selected_tracks if t.get("codec_type") == "audio"]

    effective_bitrate_bps = 0.0

    if not has_video and selected_audios:
        # Trường hợp 1: Chỉ xuất âm thanh (track video bị tắt)
        # Tính tổng bitrate từ các track audio được chọn
        for a in selected_audios:
            bps = float(a.get("bitrate_bps", 0.0))
            if bps > 1000:
                effective_bitrate_bps += bps
            else:
                # Ước tính bitrate chuẩn theo codec âm thanh nếu không có thẻ bitrate
                codec = str(a.get("codec_name", "")).lower()
                if "flac" in codec or "alac" in codec:
                    effective_bitrate_bps += 700_000.0  # Lossless audio ~700kbps
                elif "pcm" in codec or "wav" in codec:
                    effective_bitrate_bps += 1_411_200.0  # CD quality 16-bit 44.1kHz stereo
                else:
                    effective_bitrate_bps += 192_000.0  # AAC / MP3 / Opus chuẩn 192kbps
    else:
        # Trường hợp 2: Có video (hoặc video + audio)
        # 1. Thử lấy từ format_bitrate
        fmt_bps = float(video_info.get("format_bitrate", 0.0))
        if fmt_bps > 10_000:
            effective_bitrate_bps = fmt_bps
        else:
            # 2. Thử cộng bitrate các stream được chọn
            stream_bps_sum = sum(float(t.get("bitrate_bps", 0.0)) for t in selected_tracks)
            if stream_bps_sum > 10_000:
                effective_bitrate_bps = stream_bps_sum
            elif orig_size > 0 and orig_dur > 0:
                # 3. Tính toán trực tiếp từ file_size / duration của video gốc
                effective_bitrate_bps = (orig_size * 8.0) / orig_dur

    if effective_bitrate_bps <= 0:
        return 0.0, "~ 0 MB"

    # Tính dung lượng bitstream lý thuyết
    raw_bytes = (effective_bitrate_bps * cut_duration) / 8.0

    # Bù trù hao phí đóng gói container (Muxing Overhead ~1.5% + 32KB moov/headers)
    est_bytes = (raw_bytes * 1.015) + 32_768.0

    # Nếu thời lượng cắt gần bằng hoặc bằng thời lượng gốc, không vượt quá dung lượng file gốc
    if orig_size > 0 and cut_duration >= (orig_dur - 0.5):
        est_bytes = min(est_bytes, float(orig_size))

    formatted_str = f"~ {format_file_size(est_bytes)}"
    return est_bytes, formatted_str


def find_nearest_keyframe(
    target_sec: float,
    keyframes: list[float],
    mode: str = "closest",
    max_delta: float | None = None,
) -> float:
    """Tìm mốc Keyframe (I-frame) gần nhất theo chế độ và giới hạn khoảng cách tùy chọn.
    
    Tham số:
        target_sec: Mốc thời gian mục tiêu tính bằng giây.
        keyframes: Danh sách các mốc thời gian Keyframe đã được sắp xếp tăng dần.
        mode: 'closest' (khoảng cách nhỏ nhất), 'prev' (Keyframe lớn nhất <= target_sec),
              'next' (Keyframe nhỏ nhất >= target_sec).
        max_delta: Khoảng cách tối đa chấp nhận được (giây). Nếu Keyframe gần nhất vượt quá
                   max_delta, trả về target_sec ban đầu. None nghĩa là không giới hạn.
        
    Trả về:
        Mốc thời gian bám dính (giây).
    """
    if not keyframes:
        return target_sec

    if mode == "prev":
        candidates = [k for k in keyframes if k <= target_sec]
        cand = max(candidates) if candidates else keyframes[0]
    elif mode == "next":
        candidates = [k for k in keyframes if k >= target_sec]
        cand = min(candidates) if candidates else keyframes[-1]
    else:
        # mode == "closest"
        cand = min(keyframes, key=lambda k: abs(k - target_sec))

    if max_delta is not None and abs(cand - target_sec) > max_delta:
        return target_sec

    return cand


def generate_default_output_name(input_path: str | Path, start_sec: float = 0.0, end_sec: float = 0.0) -> Path:
    """Sinh đường dẫn file đầu ra duy nhất, an toàn có gắn mốc thời gian:
    '<TênGốc>_<HH>h<MM>m<SS>s_<DD>-<MM>-<YYYY>.<đuôi>'
    """
    p = Path(input_path).resolve()
    stem = p.stem
    suffix = p.suffix
    now_str = datetime.now().strftime("%Hh%Mm%Ss_%d-%m-%Y")
    output_filename = f"{stem}_{now_str}{suffix}"
    output_path = p.parent / output_filename

    # Nếu file đã tồn tại, tự động thêm số đếm chống ghi đè
    counter = 1
    while output_path.exists():
        output_filename = f"{stem}_{now_str}_{counter}{suffix}"
        output_path = p.parent / output_filename
        counter += 1

    return output_path


def build_cut_command(
    input_path: str | Path,
    output_path: str | Path,
    start_sec: float,
    end_sec: float,
    snap_keyframe: bool = True,
    keyframes: list[float] | None = None,
    selected_stream_indices: list[int] | None = None,
    selected_audio_indices: list[int] | None = None,
    track_ranges: dict[int, tuple[float, float]] | None = None,
    stream_types: dict[int, str] | None = None,
    cut_mode: str = "global",
    snap_mode: str = "closest",
    mix_audio: bool = False,
    rotation: int | None = None,
) -> tuple[list[str], float, float]:
    """Xây dựng câu lệnh FFmpeg Stream Copy bảo toàn 100% nguyên bản.
    
    Tham số:
        input_path: Đường dẫn tới video nguồn.
        output_path: Đường dẫn tới file xuất đích.
        start_sec: Thời gian bắt đầu mong muốn (giây).
        end_sec: Thời gian kết thúc mong muốn (giây).
        snap_keyframe: Nếu True, tự động bám start_sec vào Keyframe gần nhất.
        keyframes: Danh sách các mốc Keyframe.
        selected_stream_indices: Danh sách stream index được chọn xuất (video, audio...).
        selected_audio_indices: Alias tương thích ngược.
        track_ranges: Tùy chọn phạm vi (in_sec, out_sec) cho từng track riêng lẻ.
        stream_types: Tùy chọn ánh xạ từ stream_index sang 'video' | 'audio'.
        cut_mode: 'global' (đồng bộ tất cả track) hoặc 'per_track'.
        snap_mode: 'closest' (mặc định) hoặc 'prev'.
        mix_audio: Nếu True, trộn các audio stream thành 1 stream duy nhất.
        rotation: Góc xoay video (0, 90, 180, 270).
        
    Trả về:
        tuple (danh_sách_lệnh_cmd, thời_gian_bắt_đầu_thực_tế, thời_gian_kết_thúc_thực_tế)
        
    Ngoại lệ:
        ValueError: Nếu tham số đầu vào không hợp lệ.
    """
    in_p = Path(input_path).resolve()
    out_p = Path(output_path).resolve()

    if not in_p.is_file():
        raise ValueError(f"Input file does not exist: {in_p}")

    if in_p == out_p:
        raise ValueError("Output file path cannot be the same as input file path! (GEMINI.md protection)")

    if start_sec < 0:
        raise ValueError(f"Start time cannot be negative: {start_sec}")

    if end_sec <= start_sec:
        raise ValueError(f"End time ({end_sec}s) must be greater than start time ({start_sec}s)")

    effective_start = start_sec
    if snap_keyframe and keyframes:
        effective_start = find_nearest_keyframe(start_sec, keyframes, mode=snap_mode)
        # Nếu mốc bám dính vượt quá end_sec, lùi về Keyframe lớn nhất đứng trước end_sec
        if effective_start >= end_sec:
            prev_candidates = [k for k in keyframes if k < end_sec]
            if prev_candidates:
                effective_start = max(prev_candidates)
            else:
                effective_start = start_sec

    effective_end = end_sec
    duration = effective_end - effective_start
    if duration <= 0:
        effective_start = start_sec

    ffmpeg_bin = get_ffmpeg_path()

    # Xác định danh sách ánh xạ stream cần xuất
    target_streams = selected_stream_indices
    if target_streams is None and selected_audio_indices is not None:
        target_streams = [0] + selected_audio_indices

    sorted_streams: list[int] | None = None
    if target_streams is not None:
        if len(target_streams) == 0:
            raise ValueError("Vui lòng chọn ít nhất 1 track để xuất!")
        sorted_streams = sorted(set(target_streams))

    def _get_stype(s_idx: int) -> str:
        if stream_types and s_idx in stream_types:
            return stream_types[s_idx]
        return "video" if s_idx == 0 else "audio"

    cut_dur = max(0.001, effective_end - effective_start)

    # Stream Copy 100% Lossless: Mọi track được chọn chia sẻ chung một cửa sổ cắt bit-for-bit
    map_args: list[str] = []
    if sorted_streams is None:
        map_args = ["-map", "0"]
    else:
        for s_idx in sorted_streams:
            map_args.extend(["-map", f"0:{s_idx}"])

    # Kiểm tra xem có track video trong danh sách xuất hay không
    has_video_out = True
    if sorted_streams is not None:
        has_video_out = any(_get_stype(s) == "video" for s in sorted_streams)

    # Xoay video: Hỗ trợ display_rotation hiện đại (ma trận side data) và -metadata rotate
    display_rot_args: list[str] = []
    rot_val: int | None = None
    if has_video_out and rotation is not None and out_p.suffix.lower() in (".mp4", ".mov", ".m4v", ".mkv"):
        rot_val = int(rotation) % 360
        if rot_val != 0:
            # Trong FFmpeg, -display_rotation nhận góc quay ngược chiều kim đồng hồ (độ)
            ccw_deg = (360 - rot_val) % 360
            display_rot_args = ["-display_rotation:v:0", str(ccw_deg)]

    cmd = [
        str(ffmpeg_bin),
        "-y",
        *display_rot_args,
        "-ss", f"{effective_start:.4f}",
        "-i", str(in_p),
        "-t", f"{cut_dur:.4f}",
        "-c", "copy",
        *map_args,
        "-avoid_negative_ts", "make_zero",
    ]

    if has_video_out and rot_val is not None and out_p.suffix.lower() in (".mp4", ".mov", ".m4v", ".mkv"):
        cmd.extend(["-metadata:s:v:0", f"rotate={rot_val}"])

    if out_p.suffix.lower() in (".mp4", ".mov", ".m4v", ".m4a"):
        cmd.extend(["-movflags", "+faststart"])
    cmd.append(str(out_p))

    return cmd, effective_start, effective_end


def generate_snapshot_output_name(
    input_path: str | Path,
    time_sec: float,
    extension: str = ".png",
) -> Path:
    """Sinh tên file chống trùng lặp cho ảnh chụp khung hình video.
    
    Ví dụ: 'MyVideo_snapshot_01m25s340ms.png'
    """
    p = Path(input_path).resolve()
    stem = p.stem
    total_ms = int(round(max(0.0, float(time_sec)) * 1000))
    mins = (total_ms // 1000) // 60
    secs = (total_ms // 1000) % 60
    ms = total_ms % 1000

    time_tag = f"{mins:02d}m{secs:02d}s{ms:03d}ms"
    base_name = f"{stem}_snapshot_{time_tag}"

    target_dir = p.parent
    # Kiểm tra quyền ghi vào thư mục nguồn, tự động chuyển về Pictures nếu thư mục chỉ đọc
    try:
        test_file = target_dir / f".test_write_{time_tag}.tmp"
        test_file.touch(exist_ok=True)
        test_file.unlink(missing_ok=True)
    except Exception:
        import os
        pictures_dir = Path(os.environ.get("USERPROFILE", "")) / "Pictures"
        if pictures_dir.is_dir():
            target_dir = pictures_dir
        else:
            target_dir = Path.home()

    out_file = target_dir / f"{base_name}{extension}"
    counter = 1
    while out_file.exists():
        out_file = target_dir / f"{base_name}_{counter}{extension}"
        counter += 1

    return out_file


def build_snapshot_command(
    input_path: str | Path,
    output_path: str | Path,
    time_sec: float,
    rotation: int = 0,
) -> list[str]:
    """Xây dựng câu lệnh FFmpeg trích xuất 1 khung hình tại time_sec với độ nét gốc và xoay tương ứng.
    
    Nếu time_sec > 5s, thực hiện tua nhanh (Fast Seek) đến gần mốc rồi tua tinh (Fine Seek) để tối ưu tốc độ.
    """
    in_p = Path(input_path).resolve()
    out_p = Path(output_path).resolve()
    t = max(0.0, float(time_sec))
    ffmpeg_bin = get_ffmpeg_path()

    cmd = [
        str(ffmpeg_bin),
        "-v", "error",
        "-y",
    ]
    if t > 5.0:
        pre_seek = t - 3.0
        cmd.extend(["-ss", f"{pre_seek:.3f}", "-i", str(in_p), "-ss", "3.000"])
    else:
        cmd.extend(["-ss", f"{t:.3f}", "-i", str(in_p)])

    vf_filters = []
    rot_norm = int(rotation) % 360
    if rot_norm == 90:
        vf_filters.append("transpose=1")
    elif rot_norm == 180:
        vf_filters.append("hflip,vflip")
    elif rot_norm == 270:
        vf_filters.append("transpose=2")

    if vf_filters:
        cmd.extend(["-vf", ",".join(vf_filters)])

    cmd.extend([
        "-frames:v", "1",
        "-q:v", "2",
        str(out_p),
    ])
    return cmd


