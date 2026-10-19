"""Các tiến trình ngầm (Worker Threads) thực thi tác vụ FFmpeg bất đồng bộ.

Giữ giao diện người dùng luôn phản hồi mượt mà và báo cáo tiến độ thời gian thực.
"""

import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Optional

try:
    from PySide6.QtCore import QThread, Signal
except ImportError:
    # Lớp dự phòng tối thiểu khi chưa cài đặt PySide6
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
    """Chuyển đổi định dạng thời gian của FFmpeg (HH:MM:SS.ms) thành tổng số giây."""
    match = re.search(r"(\d+):(\d+):(\d+\.?\d*)", time_str)
    if not match:
        return 0.0
    hrs = float(match.group(1))
    mins = float(match.group(2))
    secs = float(match.group(3))
    return hrs * 3600 + mins * 60 + secs


def parse_ffmpeg_progress(stderr_line: str, total_duration: float) -> Optional[float]:
    """Bóc tách phần trăm tiến độ hoàn thành từ luồng stderr của FFmpeg.
    
    Tìm kiếm mẫu chuỗi: time=HH:MM:SS.ms
    Trả về tỷ lệ phần trăm (0.0 đến 100.0) hoặc None nếu không khớp.
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
    """Luồng QThread ngầm thực thi lệnh cắt video FFmpeg mà không làm treo giao diện UI."""

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
        """Hủy tác vụ cắt đang chạy và dọn dẹp file xuất dở dang."""
        self._is_cancelled = True
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except Exception:
                pass

    def run(self):
        """Thực thi tiến trình FFmpeg ngầm và cập nhật tiến độ qua stderr."""
        self._is_cancelled = False
        self.status_message.emit("Bắt đầu xử lý Stream Copy...")
        self.progress_changed.emit(0.0)

        try:
            # Ẩn cửa sổ dòng lệnh cmd trên hệ điều hành Windows
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            self._process = subprocess.Popen(
                self.cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )

            # Đọc từng dòng thông báo tiến độ từ stderr
            stderr_tail: list[str] = []
            if self._process.stderr:
                for line in self._process.stderr:
                    if self._is_cancelled:
                        break
                    if len(stderr_tail) >= 10:
                        stderr_tail.pop(0)
                    stderr_tail.append(line)
                    pct = parse_ffmpeg_progress(line, self.cut_duration)
                    if pct is not None:
                        self.progress_changed.emit(pct)

            self._process.wait()

            if self._is_cancelled:
                # Xóa file dở dang nếu người dùng bấm Hủy
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
                tail_msg = "".join(stderr_tail).strip()
                err_msg = f"FFmpeg kết thúc với lỗi (code {self._process.returncode})"
                if tail_msg:
                    err_msg += f":\n{tail_msg}"
                self.failed.emit(err_msg)

        except Exception as e:
            self.failed.emit(f"Lỗi khi thực thi: {str(e)}")


class KeyframeWorker(QThread):
    """Luồng QThread quét danh sách Keyframe video ngầm mà không gây đơ giao diện."""

    keyframes_ready = Signal(list)
    scan_failed = Signal(str)

    def __init__(self, video_path: str | Path, parent=None):
        super().__init__(parent)
        self.video_path = Path(video_path).resolve()
        self._is_cancelled = False
        self._process: Optional[subprocess.Popen] = None

    def cancel(self):
        self._is_cancelled = True
        if self._process and self._process.poll() is None:
            try:
                self._process.kill()
            except Exception:
                pass

    def run(self):
        from src.core.probe import get_keyframe_timestamps

        try:
            keyframes = get_keyframe_timestamps(self.video_path, timeout=15.0, worker_ref=self)
            if not self._is_cancelled:
                self.keyframes_ready.emit(keyframes)
        except Exception as e:
            if not self._is_cancelled:
                self.scan_failed.emit(str(e))


class AudioWaveformWorker(QThread):
    """Luồng QThread trích xuất và chuẩn hóa sóng âm thanh thực tế cho toàn bộ các audio stream."""

    waveforms_ready = Signal(object)  # {stream_index: list[float]} - dùng object để tránh cảnh báo sao chép Shiboken C++ dict
    stream_waveform_ready = Signal(int, list)  # stream_index, list[float]

    def __init__(self, video_path: str | Path, audio_streams: list[dict], parent=None):
        super().__init__(parent)
        self.video_path = Path(video_path).resolve()
        self.audio_streams = audio_streams
        self._is_cancelled = False
        self._process: Optional[subprocess.Popen] = None

    def cancel(self):
        self._is_cancelled = True
        if self._process and self._process.poll() is None:
            try:
                self._process.kill()
            except Exception:
                pass

    def run(self):
        import array
        import math
        from src.core.config import get_ffmpeg_path, get_project_root

        ffmpeg_bin = get_ffmpeg_path()
        waveforms: dict[int, list[float]] = {}
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        debug_log_path = get_project_root() / "cache" / "waveform_debug.log"
        debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        if debug_log_path.exists() and debug_log_path.stat().st_size > 1024 * 1024:
            try:
                debug_log_path.write_text("", encoding="utf-8")
            except Exception:
                pass

        with open(debug_log_path, "a", encoding="utf-8") as log_f:
            log_f.write(f"\n--- Bắt đầu trích xuất sóng âm cho {self.video_path.name} ({len(self.audio_streams)} audio streams) ---\n")

        for idx, stream in enumerate(self.audio_streams):
            if self._is_cancelled:
                return

            s_idx = stream.get("stream_index", idx)

            # Thử ánh xạ 0:{s_idx}, dự phòng sang 0:a:{idx} nếu cần
            raw_bytes = b""
            for map_arg in [f"0:{s_idx}", f"0:a:{idx}"]:
                if self._is_cancelled:
                    return

                # Cờ -vn -sn -dn đảm bảo FFmpeg chỉ giải mã audio cực nhanh (<200ms)
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
                    self._process = subprocess.Popen(
                        cmd,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=creationflags,
                    )
                    out, err = self._process.communicate(timeout=45)
                    if out and len(out) >= 80:
                        raw_bytes = out
                        break
                except subprocess.TimeoutExpired:
                    if self._process:
                        try:
                            self._process.kill()
                            self._process.communicate()
                        except Exception:
                            pass
                    with open(debug_log_path, "a", encoding="utf-8") as log_f:
                        log_f.write(f"Stream {s_idx} map {map_arg}: Timeout sau 45s.\n")
                    continue
                except Exception as ex:
                    if self._process:
                        try:
                            self._process.kill()
                            self._process.communicate()
                        except Exception:
                            pass
                    with open(debug_log_path, "a", encoding="utf-8") as log_f:
                        log_f.write(f"Lỗi Stream {s_idx} map {map_arg}: {ex}\n")
                    continue
                finally:
                    self._process = None

            if not raw_bytes or len(raw_bytes) < 80:
                with open(debug_log_path, "a", encoding="utf-8") as log_f:
                    log_f.write(f"Stream {s_idx}: Không trích xuất được dữ liệu audio.\n")
                continue

            # Chuyển đổi byte PCM 16-bit qua array cấp độ C (tốc độ siêu nhanh, không tốn RAM)
            pcm = array.array("h")
            # Đảm bảo số lượng byte chẵn
            pcm.frombytes(raw_bytes[: len(raw_bytes) - (len(raw_bytes) % 2)])
            del raw_bytes  # Giải phóng ngay lập tức mảng byte thô hàng chục MB
            num_samples = len(pcm)

            # 40 mẫu tại 8000 Hz = 5ms mỗi đỉnh peak (200 peaks/giây)
            # Giúp bắt trọn chính xác các âm thanh gõ phím ngắn (10-25ms)
            window = 40
            raw_peaks: list[float] = []
            for i in range(0, num_samples, window):
                chunk = pcm[i : i + window]
                m = max(abs(x) for x in chunk) / 32768.0
                raw_peaks.append(m)
            del pcm  # Giải phóng mảng PCM sau khi đã lấy các đỉnh thô

            # --- Chuẩn hóa độ tương phản thích ứng (Adaptive Contrast Normalization) ---
            # Tách biệt tiếng ồn phòng xung quanh khỏi các âm thanh gõ phím sắc nét
            non_silent = [p for p in raw_peaks if p > 0.002]
            if non_silent and len(non_silent) > 20:
                sorted_peaks = sorted(non_silent)
                # Ngưỡng sàn tiếng ồn (phân vị thứ 15 của tín hiệu không im lặng)
                noise_floor = sorted_peaks[int(len(sorted_peaks) * 0.15)]
                noise_floor = min(0.04, noise_floor)

                # Đỉnh tham chiếu: phân vị 98 giúp ngăn chặn 1 tiếng nổ to lấn át toàn bộ đỉnh nhỏ
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
                        # Lũy thừa 0.55 giúp các âm gõ nhẹ nổi bật rõ ràng (chiều cao 30%-95%)
                        val = math.pow(ratio, 0.55) * 0.95
                        scaled_peaks.append(round(min(1.0, val), 4))
                del non_silent, sorted_peaks
            else:
                max_val = max(raw_peaks) if raw_peaks else 0.0
                if max_val > 0.003:
                    scale = 0.95 / max_val
                    scaled_peaks = [min(1.0, round(p * scale, 4)) for p in raw_peaks]
                else:
                    scaled_peaks = [0.0] * len(raw_peaks)
            del raw_peaks  # Giải phóng mảng raw_peaks

            waveforms[s_idx] = scaled_peaks
            with open(debug_log_path, "a", encoding="utf-8") as log_f:
                log_f.write(f"Stream {s_idx} thành công: {len(scaled_peaks)} peaks. Phát tín hiệu stream waveform.\n")

            if not self._is_cancelled:
                self.stream_waveform_ready.emit(s_idx, scaled_peaks)

        if not self._is_cancelled:
            self.waveforms_ready.emit(waveforms)


class VideoThumbnailWorker(QThread):
    """Lớp giữ tương thích: Timeline hiện đã sử dụng dải cuộn phim vector siêu nhẹ (0% CPU)."""
    thumbnails_ready = Signal(list)

    def cancel(self):
        pass


class SnapshotWorker(QThread):
    """Luồng QThread trích xuất ảnh chụp khung hình video ở độ phân giải gốc mà không làm đơ giao diện."""

    finished_success = Signal(str, float)  # (đường_dẫn_ảnh, mốc_thời_gian_giây)
    failed = Signal(str)                   # thông_báo_lỗi

    def __init__(self, cmd: list[str], output_path: str | Path, time_sec: float, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.output_path = Path(output_path).resolve()
        self.time_sec = float(time_sec)
        self._process: Optional[subprocess.Popen] = None
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        if self._process:
            try:
                self._process.kill()
            except Exception:
                pass

    def run(self):
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self._process = subprocess.Popen(
                self.cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
            _, stderr = self._process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            if self._process:
                try:
                    self._process.kill()
                    self._process.communicate()
                except Exception:
                    pass
            if not self._is_cancelled:
                self.failed.emit("Quá thời gian trích xuất ảnh chụp (Timeout 15s).")
            return
        except Exception as e:
            if self._process:
                try:
                    self._process.kill()
                    self._process.communicate()
                except Exception:
                    pass
            if not self._is_cancelled:
                self.failed.emit(f"Lỗi khi chụp ảnh: {str(e)}")
            return
        finally:
            self._process = None

        if self._is_cancelled:
            return

        if self.output_path.is_file() and self.output_path.stat().st_size > 0:
            self.finished_success.emit(str(self.output_path), self.time_sec)
        else:
            err = stderr.decode("utf-8", errors="ignore").strip() if stderr else "Không tạo được file ảnh"
            self.failed.emit(err)


class SmartCutWorker(QThread):
    """Luồng ngầm thực thi chuỗi tác vụ Smart Cut đa phân đoạn (Head -> Body -> Tail -> Concat)."""

    progress_changed = Signal(float)
    status_message = Signal(str)
    finished_success = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        plan: Any,
        parent=None,
    ):
        super().__init__(parent)
        self.plan = plan
        self._current_process: Optional[subprocess.Popen] = None
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        if self._current_process and self._current_process.poll() is None:
            try:
                self._current_process.terminate()
            except Exception:
                pass
        from src.core.smart_cutter import cleanup_smartcut_job
        cleanup_smartcut_job(self.plan.job_dir)
        if self.plan.final_output and Path(self.plan.final_output).exists():
            try:
                Path(self.plan.final_output).unlink()
            except Exception:
                pass

    def run(self):
        import shutil
        from src.core.smart_cutter import cleanup_smartcut_job
        self._is_cancelled = False
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        total_segs = len(self.plan.segments)

        try:
            # 1. Trường hợp chỉ có 1 phân đoạn (Sub-GOP)
            if total_segs == 1 and self.plan.segments[0].name == "single":
                seg = self.plan.segments[0]
                self.status_message.emit("Đang mã hóa đoạn ngắn chính xác từng frame...")
                self.progress_changed.emit(10.0)
                self._run_cmd(seg.cmd, max(0.001, seg.end_sec - seg.start_sec), creationflags)
                if self._is_cancelled:
                    return

                # Nếu có lượt xoay container metadata
                if self.plan.rotation_cmd:
                    self.status_message.emit("Đang áp dụng góc xoay metadata...")
                    self.progress_changed.emit(90.0)
                    self._run_cmd(self.plan.rotation_cmd, 1.0, creationflags, base_pct=90.0, weight=10.0)
                    if self._is_cancelled:
                        return
                else:
                    if self.plan.temp_target and Path(self.plan.temp_target).is_file():
                        final_p = Path(self.plan.final_output)
                        if final_p.exists():
                            final_p.unlink()
                        shutil.move(str(self.plan.temp_target), str(final_p))

                final_p = Path(self.plan.final_output)
                if final_p.is_file() and final_p.stat().st_size > 0:
                    self.progress_changed.emit(100.0)
                    self.status_message.emit("Smart Cut hoàn tất thành công!")
                    cleanup_smartcut_job(self.plan.job_dir)
                    self.finished_success.emit(str(final_p))
                else:
                    cleanup_smartcut_job(self.plan.job_dir)
                    self.failed.emit("Không tạo được file đích sau khi xử lý.")
                return

            # 2. Trường hợp đa phân đoạn
            total_duration = max(0.001, self.plan.effective_end - self.plan.effective_start)
            processed_duration = 0.0

            for i, seg in enumerate(self.plan.segments):
                if self._is_cancelled:
                    return

                seg_dur = max(0.001, seg.end_sec - seg.start_sec)
                label_map = {
                    "head": f"[{i+1}/{total_segs+1}] Đang mã hóa đoạn đầu để bắt chuẩn khung hình...",
                    "body": f"[{i+1}/{total_segs+1}] Đang sao chép phần thân (100% Lossless Stream Copy)...",
                    "tail": f"[{i+1}/{total_segs+1}] Đang mã hóa đoạn kết...",
                }
                msg = label_map.get(seg.name, f"[{i+1}/{total_segs+1}] Đang xử lý phân đoạn {seg.name}...")
                self.status_message.emit(msg)

                base_pct = (processed_duration / total_duration) * 85.0
                seg_weight = (seg_dur / total_duration) * 85.0

                self._run_cmd(seg.cmd, seg_dur, creationflags, base_pct=base_pct, weight=seg_weight)
                if self._is_cancelled:
                    return

                processed_duration += seg_dur

            # 3. Ghép file bằng FFmpeg Concat Demuxer
            if self._is_cancelled:
                return

            self.status_message.emit(f"[{total_segs+1}/{total_segs+1}] Đang ghép các phân đoạn thành file hoàn chỉnh...")
            self.progress_changed.emit(87.0)

            self._run_cmd(self.plan.concat_cmd, 1.0, creationflags, base_pct=87.0, weight=8.0)
            if self._is_cancelled:
                return

            # 4. Áp dụng góc xoay metadata vào container nếu có
            if self.plan.rotation_cmd:
                self.status_message.emit("Đang áp dụng góc xoay metadata vào container...")
                self.progress_changed.emit(95.0)
                self._run_cmd(self.plan.rotation_cmd, 1.0, creationflags, base_pct=95.0, weight=5.0)
                if self._is_cancelled:
                    return

            final_p = Path(self.plan.final_output)
            if final_p.is_file() and final_p.stat().st_size > 0:
                self.progress_changed.emit(100.0)
                self.status_message.emit("Smart Cut hoàn tất thành công 100%!")
                cleanup_smartcut_job(self.plan.job_dir)
                self.finished_success.emit(str(final_p))
            else:
                cleanup_smartcut_job(self.plan.job_dir)
                self.failed.emit("Không tạo được file đích sau khi ghép Smart Cut.")

        except Exception as e:
            cleanup_smartcut_job(self.plan.job_dir)
            if not self._is_cancelled:
                self.failed.emit(f"Lỗi Smart Cut: {str(e)}")

    def _run_cmd(
        self,
        cmd: list[str],
        duration: float,
        creationflags: int,
        base_pct: float = 0.0,
        weight: float = 100.0,
    ):
        self._current_process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )

        stderr_tail: list[str] = []
        if self._current_process.stderr:
            for line in self._current_process.stderr:
                if self._is_cancelled:
                    break
                if len(stderr_tail) >= 10:
                    stderr_tail.pop(0)
                stderr_tail.append(line)
                pct = parse_ffmpeg_progress(line, duration)
                if pct is not None:
                    overall_pct = min(99.0, base_pct + (pct / 100.0) * weight)
                    self.progress_changed.emit(overall_pct)

        self._current_process.wait()
        rc = self._current_process.returncode
        self._current_process = None

        if not self._is_cancelled and rc != 0:
            tail_msg = "".join(stderr_tail).strip()
            raise RuntimeError(f"Lệnh FFmpeg thất bại (code {rc}):\n{tail_msg}")




