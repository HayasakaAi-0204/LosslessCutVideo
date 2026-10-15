"""Lossless video cutting engine using FFmpeg Stream Copy.

Ensures bit-for-bit quality preservation with zero re-encoding.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.config import get_ffmpeg_path


def format_timestamp(seconds: float) -> str:
    """Format seconds into HH:MM:SS.mmm string."""
    seconds = max(0.0, seconds)
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:06.3f}"


def find_nearest_keyframe(
    target_sec: float,
    keyframes: list[float],
    mode: str = "closest",
    max_delta: float | None = None,
) -> float:
    """Find the nearest keyframe according to mode and optional distance constraint.
    
    Args:
        target_sec: Target timestamp in seconds.
        keyframes: Sorted list of keyframe timestamps.
        mode: 'closest' for minimum delta, 'prev' for largest keyframe <= target_sec,
              'next' for smallest keyframe >= target_sec.
        max_delta: Maximum acceptable distance in seconds. If closest candidate is further
                   than max_delta, returns target_sec unchanged. None means no limit.
        
    Returns:
        Snapped timestamp in seconds.
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
    """Generate a safe, unique output file path using timestamp:
    '<Stem>_<HH>h<MM>m<SS>s_<DD>-<MM>-<YYYY>.<suffix>'
    """
    p = Path(input_path).resolve()
    stem = p.stem
    suffix = p.suffix
    now_str = datetime.now().strftime("%Hh%Mm%Ss_%d-%m-%Y")
    output_filename = f"{stem}_{now_str}{suffix}"
    output_path = p.parent / output_filename

    # If already exists, append counter
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
    """Construct FFmpeg stream copy / smart hybrid cut command.
    
    Args:
        input_path: Path to source video.
        output_path: Path to destination file.
        start_sec: Desired start time in seconds.
        end_sec: Desired end time in seconds.
        snap_keyframe: If True, snap start_sec to the nearest keyframe.
        keyframes: List of keyframe timestamps.
        selected_stream_indices: List of all stream indices to include (video, audio, etc.).
        selected_audio_indices: Legacy alias for backward compatibility.
        track_ranges: Optional per-stream (in_sec, out_sec) mapping for independent track trimming.
        stream_types: Optional mapping from stream_index to 'video' | 'audio'.
        cut_mode: 'global' (all tracks synchronous) or 'per_track' (independent track trimming).
        snap_mode: 'closest' (default) or 'prev'.
        mix_audio: If True, merge all selected audio tracks into a single stream via amix.
        
    Returns:
        tuple of (cmd_list, effective_start_sec, effective_end_sec)
        
    Raises:
        ValueError: If arguments are invalid.
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
        # If snapped start equals or exceeds end_sec, fall back to nearest keyframe strictly before end_sec
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

    # Determine stream mapping
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

    # Pure 100% Lossless Stream Copy: All selected tracks share identical cut window bit-for-bit
    map_args: list[str] = []
    if sorted_streams is None:
        map_args = ["-map", "0"]
    else:
        for s_idx in sorted_streams:
            map_args.extend(["-map", f"0:{s_idx}"])

    cmd = [
        str(ffmpeg_bin),
        "-y",
        "-ss", f"{effective_start:.4f}",
        "-i", str(in_p),
        "-t", f"{cut_dur:.4f}",
        "-c", "copy",
        *map_args,
        "-avoid_negative_ts", "make_zero",
    ]
    # Add rotation metadata if applicable and video stream is present
    has_video_out = True
    if sorted_streams is not None:
        has_video_out = any(_get_stype(s) == "video" for s in sorted_streams)

    if has_video_out and rotation is not None and out_p.suffix.lower() in (".mp4", ".mov", ".m4v", ".mkv"):
        rot_val = int(rotation) % 360
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
    """Generate a collision-free filename for video frame snapshot.
    
    Example: 'MyVideo_snapshot_01m25s340ms.png'
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
    # Verify write access to source directory, fallback to Pictures if read-only
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
    """Construct FFmpeg command to extract a single frame at time_sec with exact frame accuracy and rotation.
    
    If time_sec > 5s, fast seeks close to the target frame and fine seeks precisely to avoid full decode.
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


