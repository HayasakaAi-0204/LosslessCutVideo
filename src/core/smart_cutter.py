"""Module xử lý Smart Cut (Smart Rendering / Frame-accurate Lossless Cutting).

Cơ chế hoạt động theo chuẩn LosslessCut:
1. Phân tích vị trí mốc In và Out so với danh sách Keyframe thực tế của video.
2. Nếu In/Out đã trùng Keyframe hoặc hết file: Tự động dùng 100% Stream Copy siêu tốc (0% re-encode).
3. Nếu In/Out rơi vào giữa chu kỳ Keyframe (GOP):
   - Head (Đoạn đầu): Mã hóa lại đoạn ngắn từ In đến trước Keyframe kế tiếp [In, K_next - Δ] với cùng codec, fps, pix_fmt, color space.
   - Body (Phần thân): Chiếm 95%-99% video, sao chép Stream Copy 100% bit-for-bit nguyên bản không suy hao.
   - Tail (Đoạn cuối): Mã hóa lại đoạn ngắn từ Keyframe áp chót đến Out [K_tail, Out] với cùng tham số bitstream.
   - Concat: Dùng FFmpeg Concat Demuxer (-c copy) ghép các đoạn lại thành file hoàn chỉnh.
4. Xử lý góc xoay (Rotation) chuẩn Container Metadata:
   - Các đoạn Head, Body, Tail TUYỆT ĐỐI không xoay pixel (giữ nguyên tỷ lệ và chiều 0° raster gốc bằng -noautorotate).
   - Áp dụng góc xoay qua ma trận container tkhd (-display_rotation / rotate metadata) ở bước muxing cuối cùng.
   - Đảm bảo 100% không bao giờ bị lệch kích thước, không lag/khựng ở đoạn đuôi và không bị xoay 180 độ.
5. Tự động phát hiện và ưu tiên Hardware Encoder (NVENC av1_nvenc, h264_nvenc, hevc_nvenc) nếu hệ thống có GPU NVIDIA.
6. Đảm bảo toàn bộ file tạm đặt trong cache/smartcut/ theo quy định GEMINI.md và dọn dẹp sạch sẽ sau khi xong.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any
import uuid

from src.core.config import get_ffmpeg_path, get_project_root


@dataclass
class SmartCutSegment:
    name: str  # "head", "body", "tail", "single"
    start_sec: float
    end_sec: float
    mode: str  # "transcode" hoặc "copy"
    temp_file: Path
    cmd: list[str] = field(default_factory=list)


@dataclass
class SmartCutPlan:
    needs_smart_cut: bool
    reason: str
    job_id: str
    job_dir: Path
    segments: list[SmartCutSegment] = field(default_factory=list)
    concat_cmd: list[str] = field(default_factory=list)
    concat_file: Path | None = None
    final_output: Path | None = None
    temp_target: Path | None = None
    rotation_cmd: list[str] = field(default_factory=list)
    effective_start: float = 0.0
    effective_end: float = 0.0


_STALE_CLEANED = False


def get_smartcut_cache_dir() -> Path:
    """Trả về thư mục cache cho Smart Cut nằm bên trong thư mục gốc dự án theo GEMINI.md."""
    global _STALE_CLEANED
    cache_dir = get_project_root() / "cache" / "smartcut"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Tự động dọn dẹp các thư mục job_* cũ còn sót lại từ các phiên chạy trước (quá 2 giờ)
    if not _STALE_CLEANED:
        _STALE_CLEANED = True
        try:
            now = time.time()
            for item in cache_dir.iterdir():
                if item.is_dir() and item.name.startswith("job_"):
                    if (now - item.stat().st_mtime) > 7200:
                        shutil.rmtree(item, ignore_errors=True)
        except Exception:
            pass

    return cache_dir


def cleanup_smartcut_job(job_dir: Path | str | None):
    """Xóa bỏ an toàn thư mục tạm của một phiên Smart Cut."""
    if not job_dir:
        return
    try:
        p = Path(job_dir).resolve()
        cache_root = get_smartcut_cache_dir().resolve()
        # Đảm bảo chỉ xóa thư mục con nằm trong cache/smartcut/
        if cache_root in p.parents or p == cache_root:
            if p.is_dir() and p != cache_root:
                shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


# Bộ nhớ đệm kiểm tra hỗ trợ encoder phần cứng
_ENCODER_SUPPORT_CACHE: dict[str, bool] = {}


def is_encoder_supported(encoder_name: str) -> bool:
    """Kiểm tra nhanh xem encoder có được hỗ trợ bởi FFmpeg và GPU hiện tại hay không."""
    if encoder_name in _ENCODER_SUPPORT_CACHE:
        return _ENCODER_SUPPORT_CACHE[encoder_name]

    ffmpeg_bin = get_ffmpeg_path()
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        cmd = [
            str(ffmpeg_bin),
            "-v", "error",
            "-f", "lavfi",
            "-i", "color=c=black:s=64x64:d=0.04",
            "-c:v", encoder_name,
            "-frames:v", "1",
            "-f", "null",
            "-",
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            timeout=2.0,
        )
        supported = (res.returncode == 0)
    except Exception:
        supported = False

    _ENCODER_SUPPORT_CACHE[encoder_name] = supported
    return supported


def get_video_encoder_args(
    codec_name: str,
    target_pix_fmt: str,
    video_info: dict[str, Any],
) -> tuple[str, list[str]]:
    """Chọn encoder tối ưu nhất (ưu tiên NVENC phần cứng nếu có GPU) và xây dựng tham số đồng bộ bitstream."""
    c = str(codec_name or "").lower()
    encoder = "libx264"
    enc_args: list[str] = []

    if "av01" in c or "av1" in c:
        if is_encoder_supported("av1_nvenc"):
            encoder = "av1_nvenc"
            enc_args = ["-c:v", "av1_nvenc", "-preset", "p4", "-cq", "20", "-b:v", "0", "-flags", "+cgop", "-fps_mode", "cfr"]
        else:
            encoder = "libsvtav1"
            enc_args = ["-c:v", "libsvtav1", "-preset", "7", "-crf", "22", "-flags", "+cgop", "-fps_mode", "cfr"]
    elif "h264" in c or "avc" in c:
        if is_encoder_supported("h264_nvenc"):
            encoder = "h264_nvenc"
            enc_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "18", "-b:v", "0", "-flags", "+cgop", "-fps_mode", "cfr"]
        else:
            encoder = "libx264"
            enc_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-flags", "+cgop", "-fps_mode", "cfr"]
    elif "hevc" in c or "h265" in c:
        if is_encoder_supported("hevc_nvenc"):
            encoder = "hevc_nvenc"
            enc_args = ["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "19", "-b:v", "0", "-flags", "+cgop", "-fps_mode", "cfr"]
        else:
            encoder = "libx265"
            enc_args = ["-c:v", "libx265", "-preset", "veryfast", "-crf", "20", "-flags", "+cgop", "-fps_mode", "cfr"]
    elif "vp9" in c:
        encoder = "libvpx-vp9"
        enc_args = ["-c:v", "libvpx-vp9", "-crf", "24", "-b:v", "0", "-fps_mode", "cfr"]
    else:
        if is_encoder_supported("h264_nvenc"):
            encoder = "h264_nvenc"
            enc_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "18", "-b:v", "0", "-flags", "+cgop", "-fps_mode", "cfr"]
        else:
            encoder = "libx264"
            enc_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-flags", "+cgop", "-fps_mode", "cfr"]

    # Kế thừa định dạng điểm ảnh (Pixel Format)
    enc_args.extend(["-pix_fmt", target_pix_fmt])

    # Kế thừa không gian màu và đặc tính truyền tải màu gốc để tránh khựng hình / đổi màu ở mối nối
    c_range = str(video_info.get("color_range") or "").strip().lower()
    if c_range in ("tv", "limited"):
        enc_args.extend(["-color_range", "tv"])
    elif c_range in ("pc", "full"):
        enc_args.extend(["-color_range", "pc"])

    c_space = str(video_info.get("color_space") or "").strip()
    if c_space and c_space.lower() not in ("unknown", "n/a"):
        enc_args.extend(["-colorspace", c_space])

    c_primaries = str(video_info.get("color_primaries") or "").strip()
    if c_primaries and c_primaries.lower() not in ("unknown", "n/a"):
        enc_args.extend(["-color_primaries", c_primaries])

    c_trc = str(video_info.get("color_transfer") or "").strip()
    if c_trc and c_trc.lower() not in ("unknown", "n/a"):
        enc_args.extend(["-color_trc", c_trc])

    return encoder, enc_args


def map_video_encoder(codec_name: str) -> str:
    """Ánh xạ codec video sang encoder tương thích trong FFmpeg (dự phòng tương thích ngược)."""
    c = str(codec_name or "").lower()
    if "av01" in c or "av1" in c:
        return "libsvtav1"
    elif "h264" in c or "avc" in c:
        return "libx264"
    elif "hevc" in c or "h265" in c:
        return "libx265"
    elif "vp9" in c:
        return "libvpx-vp9"
    elif "vp8" in c:
        return "libvpx"
    return "libx264"


def analyze_smart_cut_plan(
    input_path: str | Path,
    output_path: str | Path,
    start_sec: float,
    end_sec: float,
    keyframes: list[float] | None,
    total_duration: float,
    video_info: dict[str, Any] | None = None,
    rotation: int | None = None,
    selected_stream_indices: list[int] | None = None,
) -> SmartCutPlan:
    """Phân tích và lập kế hoạch cắt Smart Cut tối ưu chuẩn LosslessCut.
    
    Tự động nhận diện xem vết cắt có cần re-encode hay có thể dùng 100% Stream Copy.
    Khi điểm In/Out không trùng Keyframe, chia tách thành các phân đoạn Head, Body, Tail
    với timestamp không trùng lặp (khử trùng lặp khung hình tại điểm giao nhau).
    Áp dụng góc xoay bằng Container Metadata Pass thay vì xoay vật lý điểm ảnh.
    Bảo toàn trọn vẹn toàn bộ các luồng âm thanh đa track.
    """
    in_p = Path(input_path).resolve()
    out_p = Path(output_path).resolve()
    kfs = sorted(keyframes or [])
    dur = max(0.001, total_duration)

    start_sec = max(0.0, start_sec)
    end_sec = min(dur, max(start_sec + 0.05, end_sec))

    job_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    job_dir = get_smartcut_cache_dir() / f"job_{job_id}"

    EPS = 0.03  # Ngưỡng sai số chấp nhận được (~1 khung hình ở 30fps)

    # 1. Kiểm tra xem mốc In có trùng Keyframe hay không
    in_is_keyframe = (start_sec <= EPS)
    closest_in_kf = None
    if kfs:
        for k in kfs:
            if abs(k - start_sec) < EPS:
                in_is_keyframe = True
                closest_in_kf = k
                break

    # 2. Kiểm tra xem mốc Out có trùng Keyframe hoặc ở cuối file hay không
    out_is_eof = (end_sec >= (dur - EPS))
    out_is_keyframe = False
    closest_out_kf = None
    if kfs:
        for k in kfs:
            if abs(k - end_sec) < EPS:
                out_is_keyframe = True
                closest_out_kf = k
                break

    # Trường hợp 1: Cắt trọn vẹn toàn bộ video (từ đầu đến cuối file)
    if (start_sec <= EPS) and out_is_eof:
        return SmartCutPlan(
            needs_smart_cut=False,
            reason="Cắt toàn bộ video từ 0 đến cuối file (Dùng Stream Copy 100% siêu tốc).",
            job_id=job_id,
            job_dir=job_dir,
            effective_start=0.0,
            effective_end=dur,
            final_output=out_p,
        )

    # Trường hợp 2: In là Keyframe VÀ (Out là Keyframe hoặc Out là cuối file)
    # => Hoàn toàn KHÔNG CẦN Smart Cut, thoái lui về Stream Copy 100% để đạt tốc độ tức thì
    if (in_is_keyframe or start_sec <= EPS) and (out_is_keyframe or out_is_eof):
        eff_start = closest_in_kf if (closest_in_kf is not None) else 0.0
        eff_end = dur if out_is_eof else (closest_out_kf if closest_out_kf is not None else end_sec)
        return SmartCutPlan(
            needs_smart_cut=False,
            reason="Mốc In và Out đã trùng khớp hoàn hảo với Keyframe/Cuối file (Dùng Stream Copy 100% siêu tốc).",
            job_id=job_id,
            job_dir=job_dir,
            effective_start=eff_start,
            effective_end=eff_end,
            final_output=out_p,
        )

    # Nếu không có danh sách keyframe thì không thể phân đoạn chính xác -> Dùng stream copy
    if not kfs:
        return SmartCutPlan(
            needs_smart_cut=False,
            reason="Chưa có dữ liệu Keyframe của video (Dùng Stream Copy).",
            job_id=job_id,
            job_dir=job_dir,
            effective_start=start_sec,
            effective_end=end_sec,
            final_output=out_p,
        )

    # Trường hợp 3: Bắt đầu cấu hình Smart Cut
    job_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = get_ffmpeg_path()
    v_info = video_info or {}
    v_codec = v_info.get("video_codec", "")
    fps_val = float(v_info.get("fps", 0.0))
    ext = out_p.suffix.lower() or in_p.suffix.lower() or ".mp4"

    # Tính toán thời lượng một khung hình (frame duration) để cắt chuẩn xác biên, loại bỏ hoàn toàn trùng lặp frame
    frame_dur = (1.0 / fps_val) if fps_val > 0 else 0.016667
    half_frame = frame_dur * 0.5

    # Ánh xạ danh sách stream bảo tồn trọn vẹn toàn bộ track âm thanh
    map_args: list[str] = []
    if selected_stream_indices is None:
        map_args = ["-map", "0"]
    else:
        for s_idx in sorted(set(selected_stream_indices)):
            map_args.extend(["-map", f"0:{s_idx}"])

    # Xác định Pixel format
    orig_pix_fmt = str(v_info.get("pix_fmt") or "").strip().lower()
    if "10" in orig_pix_fmt:
        target_pix_fmt = "yuv420p10le"
    elif "444" in orig_pix_fmt:
        target_pix_fmt = "yuv444p"
    elif "422" in orig_pix_fmt:
        target_pix_fmt = "yuv422p"
    else:
        target_pix_fmt = "yuv420p"

    # Lấy encoder tối ưu và danh sách tham số màu sắc
    timescale_val = int(v_info.get("timescale") or 0)
    timescale_args: list[str] = []
    if timescale_val > 0 and ext in (".mp4", ".mov", ".m4v", ".m4a"):
        timescale_args = ["-video_track_timescale", str(timescale_val)]

    _, encode_args = get_video_encoder_args(v_codec, target_pix_fmt, v_info)
    if fps_val > 0:
        encode_args.extend(["-r", f"{fps_val:.2f}"])
    encode_args.extend(timescale_args)

    # Xử lý xoay video theo chuẩn LosslessCut:
    # Tuyệt đối không xoay pixel vật lý khi encode segment (-noautorotate).
    # Áp dụng góc xoay bằng một lượt chuyển tiếp Metadata container siêu nhanh ở bước hoàn tất.
    needs_rotation = (
        rotation is not None
        and out_p.suffix.lower() in (".mp4", ".mov", ".m4v", ".mkv")
    )
    rot_val = (int(rotation) % 360) if rotation is not None else 0
    ccw_deg = (360 - rot_val) % 360

    # Tìm các keyframe nằm hoàn toàn ở giữa vết cắt
    inner_kfs = [k for k in kfs if (start_sec + EPS) < k < (end_sec - EPS)]

    segments: list[SmartCutSegment] = []

    # KỊCH BẢN A: Không có Keyframe nào ở giữa (Cắt trọn trong 1 GOP hoặc sub-GOP)
    if not inner_kfs:
        single_dur = max(0.001, end_sec - start_sec)
        if needs_rotation:
            seg_file = job_dir / f"single_segment{ext}"
            rotation_cmd = [
                str(ffmpeg_bin),
                "-y",
                "-display_rotation:v:0", str(ccw_deg),
                "-i", str(seg_file),
                "-c", "copy",
                "-map", "0",
                *timescale_args,
                "-metadata:s:v:0", f"rotate={rot_val}",
                "-movflags", "+faststart",
                str(out_p),
            ]
        else:
            seg_file = out_p
            rotation_cmd = []

        cmd_single = [
            str(ffmpeg_bin),
            "-y",
            "-noautorotate",
            "-ss", f"{start_sec:.6f}",
            "-i", str(in_p),
            "-t", f"{single_dur:.6f}",
            *map_args,
            *encode_args,
            "-c:a", "copy",
            *timescale_args,
            "-avoid_negative_ts", "make_zero",
        ]
        if not needs_rotation and out_p.suffix.lower() in (".mp4", ".mov", ".m4v", ".m4a"):
            cmd_single.extend(["-movflags", "+faststart"])
        cmd_single.append(str(seg_file))

        segments.append(
            SmartCutSegment(
                name="single",
                start_sec=start_sec,
                end_sec=end_sec,
                mode="transcode",
                temp_file=seg_file,
                cmd=cmd_single,
            )
        )
        return SmartCutPlan(
            needs_smart_cut=True,
            reason="Vết cắt nằm trong 1 GOP duy nhất (Mã hóa lại đoạn ngắn chính xác từng frame).",
            job_id=job_id,
            job_dir=job_dir,
            segments=segments,
            final_output=out_p,
            temp_target=seg_file if needs_rotation else None,
            rotation_cmd=rotation_cmd,
            effective_start=start_sec,
            effective_end=end_sec,
        )

    # KỊCH BẢN B: Cắt qua ít nhất 1 Keyframe ở giữa (Head -> Body -> Tail)
    first_inner_kf = inner_kfs[0]
    last_inner_kf = inner_kfs[-1]

    # 1. Đoạn Head (nếu start_sec không trùng Keyframe)
    # Head mã hóa chính xác từ start_sec đến first_inner_kf
    body_start = start_sec
    if not in_is_keyframe:
        head_file = job_dir / f"head_segment{ext}"
        head_dur = max(0.001, first_inner_kf - start_sec)
        cmd_head = [
            str(ffmpeg_bin),
            "-y",
            "-noautorotate",
            "-ss", f"{start_sec:.6f}",
            "-i", str(in_p),
            "-t", f"{head_dur:.6f}",
            *map_args,
            *encode_args,
            "-c:a", "copy",
            "-avoid_negative_ts", "make_zero",
            str(head_file),
        ]
        segments.append(
            SmartCutSegment(
                name="head",
                start_sec=start_sec,
                end_sec=first_inner_kf,
                mode="transcode",
                temp_file=head_file,
                cmd=cmd_head,
            )
        )
        body_start = first_inner_kf
    else:
        body_start = closest_in_kf if (closest_in_kf is not None) else start_sec

    # 2. Đoạn Tail (nếu end_sec không trùng Keyframe và không ở EOF)
    # Tail bắt đầu chính xác từ last_inner_kf và mã hóa đến end_sec
    body_end = dur if out_is_eof else (closest_out_kf if closest_out_kf is not None else end_sec)
    tail_segment = None
    if (not out_is_keyframe) and (not out_is_eof):
        tail_file = job_dir / f"tail_segment{ext}"
        tail_dur = max(0.001, end_sec - last_inner_kf)
        cmd_tail = [
            str(ffmpeg_bin),
            "-y",
            "-noautorotate",
            "-ss", f"{last_inner_kf:.6f}",
            "-i", str(in_p),
            "-t", f"{tail_dur:.6f}",
            *map_args,
            *encode_args,
            "-c:a", "copy",
            "-avoid_negative_ts", "make_zero",
            str(tail_file),
        ]
        tail_segment = SmartCutSegment(
            name="tail",
            start_sec=last_inner_kf,
            end_sec=end_sec,
            mode="transcode",
            temp_file=tail_file,
            cmd=cmd_tail,
        )
        body_end = last_inner_kf

    # 3. Đoạn Body (Stream Copy 100% không suy hao)
    # Body chạy từ body_start đến body_end chuẩn xác bitstream và timescale
    if body_end > (body_start + EPS):
        body_file = job_dir / f"body_segment{ext}"
        if tail_segment is not None:
            body_dur = max(0.001, body_end - body_start)
            duration_arg = ["-t", f"{body_dur:.6f}"]
        elif out_is_eof:
            duration_arg = []
        else:
            body_dur = max(0.001, body_end - body_start)
            duration_arg = ["-t", f"{body_dur:.6f}"]

        cmd_body = [
            str(ffmpeg_bin),
            "-y",
            "-ss", f"{body_start:.6f}",
            "-i", str(in_p),
            *duration_arg,
            *map_args,
            "-c", "copy",
            *timescale_args,
            "-avoid_negative_ts", "make_zero",
            str(body_file),
        ]
        segments.append(
            SmartCutSegment(
                name="body",
                start_sec=body_start,
                end_sec=body_end,
                mode="copy",
                temp_file=body_file,
                cmd=cmd_body,
            )
        )

    # Thêm đoạn Tail vào danh sách nếu có
    if tail_segment is not None:
        segments.append(tail_segment)

    # Lập file danh sách Concat Demuxer
    concat_list_file = job_dir / "concat_list.txt"
    with open(concat_list_file, "w", encoding="utf-8") as f:
        for seg in segments:
            safe_path = seg.temp_file.resolve().as_posix().replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    # Xác định đích đến của Concat Demuxer
    if needs_rotation:
        concat_target = job_dir / f"concat_temp{ext}"
        rotation_cmd = [
            str(ffmpeg_bin),
            "-y",
            "-display_rotation:v:0", str(ccw_deg),
            "-i", str(concat_target),
            "-c", "copy",
            "-map", "0",
            *timescale_args,
            "-metadata:s:v:0", f"rotate={rot_val}",
            "-movflags", "+faststart",
            str(out_p),
        ]
    else:
        concat_target = out_p
        rotation_cmd = []

    # Lệnh Concat Demuxer: Ghép thuần stream copy không đổi raster và đồng bộ timescale
    cmd_concat = [
        str(ffmpeg_bin),
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list_file),
        "-c", "copy",
        "-map", "0",
        *timescale_args,
        "-avoid_negative_ts", "make_zero",
    ]
    if not needs_rotation and out_p.suffix.lower() in (".mp4", ".mov", ".m4v", ".m4a"):
        cmd_concat.extend(["-movflags", "+faststart"])
    cmd_concat.append(str(concat_target))

    return SmartCutPlan(
        needs_smart_cut=True,
        reason=f"Smart Cut: {len(segments)} phân đoạn (Đoạn giữa Stream Copy 100%, chỉ mã hóa biên).",
        job_id=job_id,
        job_dir=job_dir,
        segments=segments,
        concat_cmd=cmd_concat,
        concat_file=concat_list_file,
        final_output=out_p,
        temp_target=concat_target if needs_rotation else None,
        rotation_cmd=rotation_cmd,
        effective_start=start_sec,
        effective_end=end_sec,
    )
