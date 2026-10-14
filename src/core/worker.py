"""Background worker for executing FFmpeg cut jobs asynchronously.

Keeps the UI responsive and reports real-time progress.
"""

from pathlib import Path
import re
import subprocess
import sys
from typing import Optional

try:
    from PySide6.QtCore import QThread, Signal
except ImportError:
    # Minimal fallback for environments before PySide6 installation
    class QThread:  # type: ignore
        def __init__(self, parent=None):
            pass
        def start(self):
            self.run()

    class Signal:  # type: ignore
        def __init__(self, *args):
            pass
        def emit(self, *args):
            pass
        def connect(self, slot):
            pass


def parse_time_to_seconds(time_str: str) -> float:
    """Convert FFmpeg time format (HH:MM:SS.ms) into total seconds."""
    match = re.search(r"(\d+):(\d+):(\d+\.?\d*)", time_str)
    if not match:
        return 0.0
    hrs = float(match.group(1))
    mins = float(match.group(2))
    secs = float(match.group(3))
    return hrs * 3600 + mins * 60 + secs


def parse_ffmpeg_progress(stderr_line: str, total_duration: float) -> Optional[float]:
    """Parse percentage completed from FFmpeg stderr line.
    
    Looks for pattern: time=HH:MM:SS.ms
    Returns percentage (0.0 to 100.0) or None if no time match.
    """
    if total_duration <= 0.0:
        return None

    match = re.search(r"time=(\d+:\d+:\d+\.?\d*)", stderr_line)
    if not match:
        return None

    current_sec = parse_time_to_seconds(match.group(1))
    percent = min(100.0, max(0.0, (current_sec / total_duration) * 100.0))
    return round(percent, 1)


class CutWorker(QThread):
    """QThread worker to execute FFmpeg cut command without blocking UI."""

    progress_changed = Signal(float)
    status_message = Signal(str)
    finished_success = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        cmd: list[str],
        output_path: str | Path,
        cut_duration: float,
        parent=None,
    ):
        super().__init__(parent)
        self.cmd = cmd
        self.output_path = Path(output_path).resolve()
        self.cut_duration = cut_duration
        self._process: Optional[subprocess.Popen] = None
        self._is_cancelled = False

    def cancel(self):
        """Cancel ongoing cut job and clean up incomplete file."""
        self._is_cancelled = True
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except Exception:
                pass

    def run(self):
        """Execute FFmpeg in background and parse stderr progress."""
        self._is_cancelled = False
        self.status_message.emit("Bắt đầu xử lý Stream Copy...")
        self.progress_changed.emit(0.0)

        try:
            # Creationflags to prevent command prompt window popping up on Windows
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            self._process = subprocess.Popen(
                self.cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )

            # Read stderr line-by-line
            if self._process.stderr:
                for line in self._process.stderr:
                    if self._is_cancelled:
                        break
                    pct = parse_ffmpeg_progress(line, self.cut_duration)
                    if pct is not None:
                        self.progress_changed.emit(pct)

            self._process.wait()

            if self._is_cancelled:
                # Clean up incomplete file
                if self.output_path.exists():
                    try:
                        self.output_path.unlink()
                    except Exception:
                        pass
                self.failed.emit("Tiến trình đã bị người dùng hủy.")
                return

            if self._process.returncode == 0:
                self.progress_changed.emit(100.0)
                self.status_message.emit("Hoàn thành xuất video thành công!")
                self.finished_success.emit(str(self.output_path))
            else:
                self.failed.emit(f"FFmpeg kết thúc với lỗi (code {self._process.returncode}).")

        except Exception as e:
            self.failed.emit(f"Lỗi khi thực thi: {str(e)}")


class KeyframeWorker(QThread):
    """Background worker to scan video keyframes without blocking the UI thread."""

    keyframes_ready = Signal(list)
    scan_failed = Signal(str)

    def __init__(self, video_path: str | Path, parent=None):
        super().__init__(parent)
        self.video_path = Path(video_path).resolve()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        from src.core.probe import get_keyframe_timestamps

        try:
            keyframes = get_keyframe_timestamps(self.video_path, timeout=30.0)
            if not self._is_cancelled:
                self.keyframes_ready.emit(keyframes)
        except Exception as e:
            if not self._is_cancelled:
                self.scan_failed.emit(str(e))


class AudioWaveformWorker(QThread):
    """Background worker to extract downsampled real audio waveforms for all audio streams."""

    waveforms_ready = Signal(object)  # {stream_index: list[float]} - use object to prevent Shiboken C++ dict copy warning
    stream_waveform_ready = Signal(int, list)  # stream_index, list[float]

    def __init__(self, video_path: str | Path, audio_streams: list[dict], parent=None):
        super().__init__(parent)
        self.video_path = Path(video_path).resolve()
        self.audio_streams = audio_streams
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        import array
        import math
        from src.core.config import get_ffmpeg_path, get_project_root

        ffmpeg_bin = get_ffmpeg_path()
        waveforms: dict[int, list[float]] = {}
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        debug_log_path = get_project_root() / "cache" / "waveform_debug.log"
        debug_log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(debug_log_path, "a", encoding="utf-8") as log_f:
            log_f.write(f"\n--- Waveform extraction started for {self.video_path.name} ({len(self.audio_streams)} audio streams) ---\n")

        for idx, stream in enumerate(self.audio_streams):
            if self._is_cancelled:
                return

            s_idx = stream.get("stream_index", idx)

            # Try primary map 0:{s_idx}, fallback to 0:a:{idx} if needed
            raw_bytes = b""
            for map_arg in [f"0:{s_idx}", f"0:a:{idx}"]:
                if self._is_cancelled:
                    return

                # -vn -sn -dn guarantees FFmpeg decodes only audio, finishing in <200ms
                cmd = [
                    str(ffmpeg_bin),
                    "-v", "error",
                    "-vn", "-sn", "-dn",
                    "-i", str(self.video_path),
                    "-map", map_arg,
                    "-ac", "1",
                    "-ar", "8000",
                    "-f", "s16le",
                    "-",
                ]

                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=creationflags,
                    )
                    out, err = proc.communicate(timeout=30)
                    if out and len(out) >= 80:
                        raw_bytes = out
                        break
                except Exception as ex:
                    with open(debug_log_path, "a", encoding="utf-8") as log_f:
                        log_f.write(f"Stream {s_idx} map {map_arg} error: {ex}\n")
                    continue

            if not raw_bytes or len(raw_bytes) < 80:
                with open(debug_log_path, "a", encoding="utf-8") as log_f:
                    log_f.write(f"Stream {s_idx}: No audio data extracted.\n")
                continue

            # Convert 16-bit PCM bytes via C-level array (blazing fast, no overhead)
            pcm = array.array("h")
            # Ensure even number of bytes
            pcm.frombytes(raw_bytes[: len(raw_bytes) - (len(raw_bytes) % 2)])
            num_samples = len(pcm)

            # 40 samples at 8000 Hz = 5ms per peak (200 peaks/second)
            # Keyboard click transients (10-25ms) are captured with pinpoint precision
            window = 40
            raw_peaks: list[float] = []
            for i in range(0, num_samples, window):
                chunk = pcm[i : i + window]
                m = max(abs(x) for x in chunk) / 32768.0
                raw_peaks.append(m)

            # --- Adaptive Click-Contrast Normalization ---
            # Separate ambient room noise floor from sharp keyboard click transients
            non_silent = [p for p in raw_peaks if p > 0.002]
            if non_silent and len(non_silent) > 20:
                sorted_peaks = sorted(non_silent)
                # Ambient noise floor (15th percentile of non-silent signal)
                noise_floor = sorted_peaks[int(len(sorted_peaks) * 0.15)]
                noise_floor = min(0.04, noise_floor)  # Cap noise floor

                # Reference peak: 98th percentile prevents 1 single loud thump from squashing clicks
                p98 = sorted_peaks[int(len(sorted_peaks) * 0.98)]
                p_max = sorted_peaks[-1]
                p_ref = max(0.015, max(p98, p_max * 0.70))

                denom = max(0.01, p_ref - noise_floor)
                scaled_peaks: list[float] = []
                for p in raw_peaks:
                    if p <= noise_floor:
                        scaled_peaks.append(0.0)
                    else:
                        ratio = min(1.0, max(0.0, (p - noise_floor) / denom))
                        # Power 0.55 makes light taps & clicks stand out tall and crisp (30%-95% height)
                        val = math.pow(ratio, 0.55) * 0.95
                        scaled_peaks.append(round(min(1.0, val), 4))
            else:
                max_val = max(raw_peaks) if raw_peaks else 0.0
                if max_val > 0.003:
                    scale = 0.95 / max_val
                    scaled_peaks = [min(1.0, round(p * scale, 4)) for p in raw_peaks]
                else:
                    scaled_peaks = [0.0] * len(raw_peaks)

            waveforms[s_idx] = scaled_peaks
            with open(debug_log_path, "a", encoding="utf-8") as log_f:
                log_f.write(f"Stream {s_idx} success: {len(scaled_peaks)} peaks generated. Emitting stream waveform.\n")

            if not self._is_cancelled:
                self.stream_waveform_ready.emit(s_idx, scaled_peaks)

        if not self._is_cancelled:
            self.waveforms_ready.emit(waveforms)


class VideoThumbnailWorker(QThread):
    """Background worker to extract video thumbnails for the filmstrip timeline."""

    thumbnails_ready = Signal(list)  # list of {"time_sec": float, "image_path": str}

    def __init__(self, video_path: str | Path, duration_sec: float, parent=None):
        super().__init__(parent)
        self.video_path = Path(video_path).resolve()
        self.duration_sec = max(1.0, duration_sec)
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        from src.core.config import get_ffmpeg_path, get_project_root

        ffmpeg_bin = get_ffmpeg_path()
        import hashlib
        path_hash = hashlib.md5(str(self.video_path.resolve()).encode("utf-8")).hexdigest()[:8]
        cache_dir = get_project_root() / "cache" / "thumbnails" / f"{self.video_path.stem}_{path_hash}"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # 1. Fast path: If high-resolution thumbnails were already generated, load immediately!
        existing = sorted(list(cache_dir.glob("thumb_*.jpg")))
        is_valid_cache = False
        if len(existing) >= 20:
            try:
                # High-res 90px thumbnails with q:v 3 are typically >= 3.5KB (old 80x44 were ~1.5KB)
                if existing[0].stat().st_size >= 3500:
                    is_valid_cache = True
            except Exception:
                pass

        if is_valid_cache:
            interval = self.duration_sec / len(existing)
            results = []
            for i, f in enumerate(existing):
                results.append({
                    "time_sec": i * interval,
                    "image_path": str(f.resolve()),
                })
            if not self._is_cancelled:
                self.thumbnails_ready.emit(results)
            return

        # Purge old low-res thumbnails if present
        for f in existing:
            try:
                f.unlink()
            except Exception:
                pass

        # 2. Extract high-density, sharp thumbnails (height 90px, scale=-2:90, high quality q:v 3)
        if self.duration_sec <= 60:
            thumb_count = min(100, max(30, int(self.duration_sec * 1.5)))
        elif self.duration_sec <= 300:
            thumb_count = min(120, max(50, int(self.duration_sec * 0.6)))
        else:
            thumb_count = min(150, max(60, int(self.duration_sec / 5.0)))

        fps = thumb_count / self.duration_sec
        pattern = str(cache_dir / "thumb_%04d.jpg")

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        cmd = [
            str(ffmpeg_bin),
            "-v", "error",
            "-y",
            "-threads", "0",
            "-i", str(self.video_path),
            "-an", "-sn", "-dn",
            "-vf", f"fps={fps:.4f},scale=-2:90",
            "-q:v", "3",
            pattern,
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
            proc.communicate(timeout=60)
        except Exception:
            pass

        if self._is_cancelled:
            return

        thumb_files = sorted(list(cache_dir.glob("thumb_*.jpg")))
        if not thumb_files:
            return

        interval = self.duration_sec / len(thumb_files)
        results = []
        for i, f in enumerate(thumb_files):
            results.append({
                "time_sec": i * interval,
                "image_path": str(f.resolve()),
            })

        if not self._is_cancelled:
            self.thumbnails_ready.emit(results)


