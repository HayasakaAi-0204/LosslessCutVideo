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
) -> float:
    """Find the nearest keyframe according to mode.
    
    Args:
        target_sec: Target timestamp in seconds.
        keyframes: Sorted list of keyframe timestamps.
        mode: 'closest' for minimum delta, 'prev' for largest keyframe <= target_sec,
              'next' for smallest keyframe >= target_sec.
        
    Returns:
        Snapped timestamp in seconds.
    """
    if not keyframes:
        return target_sec

    if mode == "prev":
        candidates = [k for k in keyframes if k <= target_sec]
        if candidates:
            return max(candidates)
        return keyframes[0]

    if mode == "next":
        candidates = [k for k in keyframes if k >= target_sec]
        if candidates:
            return min(candidates)
        return keyframes[-1]

    # mode == "closest"
    return min(keyframes, key=lambda k: abs(k - target_sec))


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

    # Detect if any audio stream has a range differing from master [effective_start, effective_end].
    # Crucial: Only trigger hybrid mode if user is EXPLICITLY in 'per_track' mode!
    # In 'global' mode, all tracks are 100% synchronous stream copy with zero re-encoding or delay filters.
    is_hybrid = False
    if cut_mode == "per_track" and track_ranges and sorted_streams:
        for s_idx in sorted_streams:
            stype = (
                stream_types.get(s_idx, "video" if s_idx == 0 else "audio")
                if stream_types
                else ("video" if s_idx == 0 else "audio")
            )
            if stype == "audio":
                trk_in, trk_out = track_ranges.get(s_idx, (effective_start, effective_end))
                if abs(trk_in - effective_start) > 0.05 or abs(trk_out - effective_end) > 0.05:
                    is_hybrid = True
                    break

    cut_dur = max(0.001, effective_end - effective_start)

    # Branch 1: Pure Stream Copy (All tracks share the same cut window)
    if not is_hybrid:
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
        if out_p.suffix.lower() in (".mp4", ".mov", ".m4v"):
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(str(out_p))
        return cmd, effective_start, effective_end

    # Branch 2: Smart Hybrid Sync (Video 100% lossless copy, offset audio filtered with adelay + 320k AAC)
    filter_complex_parts: list[str] = []
    map_args: list[str] = []
    codec_args: list[str] = []

    audio_out_idx = 0
    has_video = False

    for s_idx in sorted_streams:
        stype = (
            stream_types.get(s_idx, "video" if s_idx == 0 else "audio")
            if stream_types
            else ("video" if s_idx == 0 else "audio")
        )
        if stype == "video":
            has_video = True
            map_args.extend(["-map", f"0:{s_idx}"])
        elif stype == "subtitle":
            # Subtitle track: Stream copy lossless directly without audio filtering
            map_args.extend(["-map", f"0:{s_idx}"])
            codec_args.extend(["-c:s", "copy"])
        else:
            # Audio stream handling
            trk_in, trk_out = track_ranges.get(s_idx, (effective_start, effective_end))
            rel_in = max(0.0, trk_in - effective_start)
            rel_out = min(cut_dur, max(rel_in + 0.05, trk_out - effective_start))

            # If matches master range precisely, keep stream copy
            if abs(rel_in) <= 0.05 and abs(rel_out - cut_dur) <= 0.05:
                map_args.extend(["-map", f"0:{s_idx}"])
                codec_args.extend([f"-c:a:{audio_out_idx}", "copy"])
            else:
                # Insert exact silence delay and pad to prevent desync
                delay_ms = int(round(rel_in * 1000))
                out_label = f"a{s_idx}"
                filter_complex_parts.append(
                    f"[0:{s_idx}]atrim=start={rel_in:.4f}:end={rel_out:.4f},"
                    f"asetpts=PTS-STARTPTS,adelay={delay_ms}:all=1,apad[{out_label}]"
                )
                map_args.extend(["-map", f"[{out_label}]"])
                codec_args.extend([f"-c:a:{audio_out_idx}", "aac", f"-b:a:{audio_out_idx}", "320k"])
            audio_out_idx += 1

    cmd = [
        str(ffmpeg_bin),
        "-y",
        "-ss", f"{effective_start:.4f}",
        "-i", str(in_p),
        "-t", f"{cut_dur:.4f}",
    ]

    if filter_complex_parts:
        cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])

    if has_video:
        cmd.extend(["-c:v", "copy"])

    cmd.extend(map_args)
    cmd.extend(codec_args)
    cmd.extend([
        "-avoid_negative_ts", "make_zero",
    ])
    if out_p.suffix.lower() in (".mp4", ".mov", ".m4v"):
        cmd.extend(["-movflags", "+faststart"])
    cmd.append(str(out_p))

    return cmd, effective_start, effective_end

