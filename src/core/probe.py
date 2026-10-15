"""Module for inspecting video files using ffprobe.

Extracts metadata (duration, resolution, fps, streams) and keyframe (I-frame) timestamps.
"""

import json
import math
from pathlib import Path
import subprocess
from typing import Any

from src.core.config import get_ffprobe_path


def safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert a value to float, handling 'N/A', None, and invalid formats."""
    if val is None or val == "N/A" or val == "":
        return default
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (ValueError, TypeError):
        return default


def format_bitrate(bitrate_raw: Any) -> str:
    """Format raw bitrate value to human-readable string (e.g. 58.2 Mbps or 320 kbps)."""
    if not bitrate_raw:
        return ""
    try:
        val = float(bitrate_raw)
        if val >= 1_000_000:
            return f"{val / 1_000_000:.1f} Mbps"
        elif val >= 1_000:
            return f"{val / 1_000:.0f} kbps"
        return f"{val:.0f} bps"
    except Exception:
        return ""


def parse_ffprobe_json(raw_json: str) -> dict[str, Any]:
    """Parse raw ffprobe JSON output into a structured dictionary."""
    data = json.loads(raw_json)
    format_info = data.get("format", {})
    streams = data.get("streams", [])

    video_stream = None
    audio_streams = []
    all_tracks = []
    audio_idx = 0
    video_idx = 0
    sub_idx = 0

    for i, s in enumerate(streams):
        codec_type = s.get("codec_type", "unknown")
        codec_name = s.get("codec_name", "unknown")
        stream_index = int(s.get("index", i))
        tags = s.get("tags") or {}

        bitrate_raw = s.get("bit_rate") or tags.get("BPS") or tags.get("BPS-eng")
        bitrate_str = format_bitrate(bitrate_raw)
        title = tags.get("title") or tags.get("handler_name") or ""
        lang = tags.get("language") or "und"

        if codec_type == "video":
            if video_stream is None:
                video_stream = s
            video_idx += 1
            w = int(s.get("width", 0))
            h = int(s.get("height", 0))
            r_fr = s.get("r_frame_rate", "0/1")
            fps_val = 0.0
            try:
                num, den = r_fr.split("/")
                fps_val = round(float(num) / float(den), 2) if float(den) > 0 else 0.0
            except Exception:
                fps_val = 0.0
            details = f"{w}x{h} {fps_val:.2f}fps" if fps_val > 0 else f"{w}x{h}"
            all_tracks.append({
                "track_num": i + 1,
                "stream_index": stream_index,
                "codec_type": "video",
                "type_label": "Video",
                "icon": "🎥",
                "codec_name": codec_name,
                "details": details,
                "bitrate": bitrate_str,
                "title": title,
                "language": lang,
            })
        elif codec_type == "audio":
            audio_streams.append(s)
            audio_idx += 1
            channels = int(s.get("channels", 2))
            channel_layout = s.get("channel_layout", "stereo")
            details = f"{channels}c {channel_layout}"
            all_tracks.append({
                "track_num": i + 1,
                "stream_index": stream_index,
                "codec_type": "audio",
                "type_label": f"Audio #{audio_idx}",
                "icon": "🔊",
                "codec_name": codec_name,
                "codec": codec_name,
                "details": details,
                "bitrate": bitrate_str,
                "title": title,
                "language": lang,
            })
        elif codec_type == "subtitle":
            sub_idx += 1
            all_tracks.append({
                "track_num": i + 1,
                "stream_index": stream_index,
                "codec_type": "subtitle",
                "type_label": f"Subtitle #{sub_idx}",
                "icon": "💬",
                "codec_name": codec_name,
                "codec": codec_name,
                "details": "Subtitles",
                "bitrate": bitrate_str,
                "title": title,
                "language": lang,
            })
        else:
            all_tracks.append({
                "track_num": i + 1,
                "stream_index": stream_index,
                "codec_type": codec_type,
                "type_label": codec_type.capitalize(),
                "icon": "📄",
                "codec_name": codec_name,
                "codec": codec_name,
                "details": "",
                "bitrate": bitrate_str,
                "title": title,
                "language": lang,
            })

    duration = safe_float(format_info.get("duration"))
    if duration <= 0.0 and video_stream:
        duration = safe_float(video_stream.get("duration"))
    if duration <= 0.0 and audio_streams:
        duration = safe_float(audio_streams[0].get("duration"))

    fps = 0.0
    width = 0
    height = 0
    video_codec = ""

    initial_rotation = 0
    if video_stream:
        video_codec = video_stream.get("codec_name", "")
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        r_frame_rate = video_stream.get("r_frame_rate", "0/1")
        try:
            num, den = r_frame_rate.split("/")
            fps = round(float(num) / float(den), 3) if float(den) > 0 else 0.0
        except Exception:
            fps = 0.0

        # Detect orientation rotation from tags or display matrix
        v_tags = video_stream.get("tags") or {}
        rot_val = v_tags.get("rotate")
        if rot_val is not None:
            try:
                initial_rotation = int(float(rot_val)) % 360
            except Exception:
                pass
        if initial_rotation == 0 and "side_data_list" in video_stream:
            for sd in video_stream.get("side_data_list", []):
                if "rotation" in sd:
                    try:
                        initial_rotation = int(float(sd["rotation"])) % 360
                        break
                    except Exception:
                        pass

    return {
        "duration": duration,
        "size": int(safe_float(format_info.get("size", 0))),
        "format_name": format_info.get("format_name", ""),
        "video_codec": video_codec,
        "width": width,
        "height": height,
        "fps": fps,
        "rotation": initial_rotation,
        "tracks": all_tracks,
        "audio_tracks_count": len(audio_streams),
        "audio_codecs": [a.get("codec_name", "") for a in audio_streams],
        "audio_tracks": [t for t in all_tracks if t["codec_type"] == "audio"],
    }


def parse_keyframe_csv(csv_text: str) -> list[float]:
    """Parse ffprobe CSV output for keyframe timestamps.
    
    Supports both two-column format (ts,is_key), single-column (-skip_frame nokey),
    and multi-entry format (pts_time,pkt_pts_time).
    """
    keyframes: list[float] = []
    for line in csv_text.strip().splitlines():
        parts = [p.strip() for p in line.split(",") if p.strip()]
        if not parts:
            continue
        # Scan parts to find the first valid non-negative float
        for part in parts:
            if part in ("N/A", "0/0", "none", "null"):
                continue
            try:
                val = float(part)
                if val >= 0.0:
                    keyframes.append(round(val, 4))
                    break
            except ValueError:
                continue
    return sorted(list(set(keyframes)))


def probe_video_info(video_path: str | Path) -> dict[str, Any]:
    """Run ffprobe to get comprehensive video metadata.
    
    Args:
        video_path: Path to the input video file.
        
    Returns:
        Dictionary with parsed video information.
        
    Raises:
        FileNotFoundError: If video_path does not exist.
        RuntimeError: If ffprobe fails.
    """
    path = Path(video_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Video file not found: {path}")

    ffprobe_bin = get_ffprobe_path()
    cmd = [
        str(ffprobe_bin),
        "-v", "error",
        "-show_entries", "format=duration,size,format_name",
        "-show_streams",
        "-of", "json",
        str(path),
    ]

    import sys
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=10,
            creationflags=creationflags,
            check=True,
        )
        return parse_ffprobe_json(result.stdout)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe error: {e.stderr}") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"ffprobe binary not found at {ffprobe_bin}") from e


def get_keyframe_timestamps(video_path: str | Path, timeout: float = 30.0) -> list[float]:
    """Extract list of Keyframe (I-frame) timestamps in seconds.
    
    Uses -skip_frame nokey for high performance demuxing without decoding P/B frames.
    
    Args:
        video_path: Path to the video file.
        timeout: Maximum seconds to wait before falling back.
        
    Returns:
        List of keyframe timestamps in ascending order.
    """
    path = Path(video_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Video file not found: {path}")

    ffprobe_bin = get_ffprobe_path()
    import sys
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    # 1. Primary method: frame pts_time with skip_frame nokey
    cmd_frames = [
        str(ffprobe_bin),
        "-v", "error",
        "-select_streams", "v:0",
        "-skip_frame", "nokey",
        "-show_frames",
        "-show_entries", "frame=pts_time,pkt_pts_time",
        "-of", "csv=p=0",
        str(path),
    ]

    try:
        result = subprocess.run(
            cmd_frames,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            creationflags=creationflags,
            check=True,
        )
        keyframes = parse_keyframe_csv(result.stdout)
        if keyframes:
            return keyframes
    except Exception:
        pass

    # 2. Fast Fallback: packet level flags (works for AV1/HEVC without frame decoding)
    cmd_packets = [
        str(ffprobe_bin),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_packets",
        "-show_entries", "packet=pts_time,flags",
        "-of", "csv=p=0",
        str(path),
    ]

    try:
        result = subprocess.run(
            cmd_packets,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=15,
            creationflags=creationflags,
            check=True,
        )
        packet_kf: list[float] = []
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) >= 2 and "K" in parts[1]:
                try:
                    packet_kf.append(round(float(parts[0]), 4))
                except ValueError:
                    continue
        if packet_kf:
            return sorted(list(set(packet_kf)))
    except Exception:
        pass

    return [0.0]


