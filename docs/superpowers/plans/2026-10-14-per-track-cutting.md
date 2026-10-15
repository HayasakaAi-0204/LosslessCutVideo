# Per-Track Cutting (Smart Hybrid Sync) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable independent per-track cutting with a master-child constraint model (Video as master, Audio as constrained child) and smart hybrid synchronization for 100% lossless video + perfectly aligned audio.

**Architecture:** 
- The Video track acts as the Master anchor defining the output bounding box $[In_{video}, Out_{video}]$ and is cut via 100% lossless stream copy (`-c:v copy`).
- Child audio tracks are constrained to $In_{video} \le In_{audio} < Out_{audio} \le Out_{video}$ with automatic cascade clamping when the video range narrows.
- A toggle button on the Timeline controls bar switches between Global Sync Cut and Per-Track Cut modes.
- TimelineCanvas draws per-track clip blocks with active waveform/filmstrip regions and dimmed excluded regions.
- FFmpeg cutter engine uses pure stream copy for matching tracks and `adelay` audio filters with 320kbps AAC encoding for delayed/trimmed tracks to guarantee universal playback compatibility.

**Tech Stack:** Python 3.10+, PySide6 (Qt for Python), FFmpeg 6.x/7.x portable, unittest.

**Spec:** [docs/superpowers/specs/2026-10-14-per-track-cut-design.md](file:///c:/Users/HayasakaAi/Downloads/Code/CutVideo/docs/superpowers/specs/2026-10-14-per-track-cut-design.md)

## Global Constraints

- Never freeze or block the UI thread during media operations or cutting.
- Protect source video from in-place overwriting (`in_p != out_p`).
- Preserve 100% bit-for-bit lossless video quality (`-c:v copy`) and Keyframe snapping.
- Maintain full backward compatibility for standard single-range cuts.
- Audio tracks aligned with video must use pure stream copy (`-c:a copy`).
- Audio tracks with offset delay must use `adelay` filter + AAC 320kbps encoding for universal playback.

## Review Focus

- Audio track with zero duration ($Out \le In$): Must be prevented or clamped to minimum valid span (0.05s).
- Video range narrowed past audio in-point: Audio in-point must cascade-clamp forward to new video in-point.
- Video range narrowed before audio out-point: Audio out-point must cascade-clamp backward to new video out-point.
- All tracks deselected or invalid track index: Gracefully handle with clear warnings and fallbacks.
- Single-track video (no audio) or audio-only files: Gracefully degrade without crashing.

---

### Task 1: Core Engine - Enhanced `build_cut_command` with Smart Hybrid Sync

**Files:**
- Modify: `src/core/cutter.py:71-158`
- Test: `tests/test_cutter.py`

**Interfaces:**
- Consumes: `input_path`, `output_path`, `start_sec`, `end_sec`, `snap_keyframe`, `keyframes`, `selected_stream_indices`, `track_ranges: dict[int, tuple[float, float]] | None`
- Produces: `build_cut_command(...) -> tuple[list[str], float, float]`

- [ ] **Step 1: Write unit tests in `tests/test_cutter.py` for per-track ranges and Smart Hybrid Sync**

```python
    def test_build_cut_command_per_track_matching(self):
        dummy_in = Path(__file__)
        dummy_out = Path(__file__).parent / "dummy_out.mp4"
        # Video: 10.0 to 40.0; Audio #1 (stream 1): 10.0 to 40.0 (matching)
        ranges = {0: (10.0, 40.0), 1: (10.0, 40.0)}
        cmd, start, end = build_cut_command(
            input_path=dummy_in,
            output_path=dummy_out,
            start_sec=10.0,
            end_sec=40.0,
            selected_stream_indices=[0, 1],
            track_ranges=ranges,
        )
        self.assertEqual(start, 10.0)
        self.assertEqual(end, 40.0)
        self.assertIn("-c", cmd)
        self.assertIn("copy", cmd)

    def test_build_cut_command_per_track_hybrid_delay(self):
        dummy_in = Path(__file__)
        dummy_out = Path(__file__).parent / "dummy_out.mp4"
        # Video: 10.0 to 40.0; Audio #1 (stream 1): 15.0 to 30.0 (offset by 5s)
        ranges = {0: (10.0, 40.0), 1: (15.0, 30.0)}
        cmd, start, end = build_cut_command(
            input_path=dummy_in,
            output_path=dummy_out,
            start_sec=10.0,
            end_sec=40.0,
            selected_stream_indices=[0, 1],
            track_ranges=ranges,
        )
        self.assertEqual(start, 10.0)
        self.assertEqual(end, 40.0)
        # Check that video is stream-copied
        self.assertIn("-c:v", cmd)
        self.assertIn("copy", cmd)
        # Check that audio filter with adelay is constructed
        cmd_str = " ".join(cmd)
        self.assertIn("adelay", cmd_str)
        self.assertIn("5000", cmd_str)
        self.assertIn("320k", cmd_str)
```

- [ ] **Step 2: Run unit test to verify it fails**

Run: `python -m unittest tests/test_cutter.py`
Expected: FAIL due to `unexpected keyword argument 'track_ranges'`

- [ ] **Step 3: Implement `track_ranges` handling in `src/core/cutter.py`**

Update `build_cut_command`:
1. Add `track_ranges: dict[int, tuple[float, float]] | None = None` parameter.
2. Determine `eff_start` and `eff_end` based on Master range (`start_sec`, `end_sec`) snapped to Keyframe.
3. If `track_ranges` is None or all selected audio tracks match `[eff_start, eff_end]`:
   Use fast `-ss eff_start -to eff_end -c copy` with `-map 0:s_idx`.
4. If one or more audio tracks differ from `[eff_start, eff_end]`:
   - Keep `-c:v copy` for video stream.
   - For each audio stream:
     If matches `[eff_start, eff_end]`: `-c:a:<N> copy`.
     If offset/trimmed:
       $\Delta t = \max(0.0, in_a - eff\_start)$
       `delay_ms = int(round(\Delta t * 1000))`
       `filter_complex` entry:
       `[0:{s_idx}]atrim=start={in_a:.4f}:end={out_a:.4f},asetpts=PTS-STARTPTS,adelay={delay_ms}|{delay_ms}:all=1,apad[a{out_idx}]`
       Set codec to `-c:a:<out_idx> aac -b:a:<out_idx> 320k`.

- [ ] **Step 4: Run unit tests to verify they pass**

Run: `python -m unittest tests/test_cutter.py`
Expected: ALL PASS

---

### Task 2: Timeline Widget Model - Per-Track Ranges & Master-Child Auto-Pull Constraints

**Files:**
- Modify: `src/ui/timeline_widget.py:713-870`

**Interfaces:**
- Consumes: `tracks: list[dict]`, duration
- Produces:
  - `set_cut_mode(mode: str)`: Switch between `"global"` and `"per_track"`.
  - `get_cut_mode() -> str`: Returns current cut mode.
  - `set_selected_stream(stream_index: int)`: Set active track for editing.
  - `get_selected_stream() -> int | None`: Returns currently selected stream index.
  - `set_track_range(stream_index: int, in_sec: float, out_sec: float)`: Sets range for track with auto-pull clamping.
  - `get_track_ranges() -> dict[int, tuple[float, float]]`: Returns dict of ranges.
  - `get_effective_track_range(stream_index: int) -> tuple[float, float]`: Returns `(in_sec, out_sec)` for specific stream.

- [ ] **Step 1: Add per-track range state and methods to `TimelineWidget`**

In `TimelineWidget.__init__`:
- Add `self._cut_mode: str = "global"`
- Add `self._selected_stream_index: int | None = None`
- Add `self._track_cut_ranges: dict[int, tuple[float, float]] = {}`

- [ ] **Step 2: Implement Master-Child constraint enforcement logic**

Implement `_enforce_master_child_constraints(changed_stream_index: int)`:
- Identify master video stream index (default 0 or stream with `codec_type == 'video'`).
- If `changed_stream_index == video_idx`:
  - For all other tracks `s_idx`:
    `cur_in, cur_out = self._track_cut_ranges[s_idx]`
    If `cur_in < video_in`: set `cur_in = video_in` (auto-pull forward).
    If `cur_out > video_out`: set `cur_out = video_out` (auto-pull backward).
    `self._track_cut_ranges[s_idx] = (cur_in, cur_out)`
- If `changed_stream_index != video_idx`:
  - `video_in, video_out = self._track_cut_ranges.get(video_idx, (0.0, self._duration_sec))`
  - Clamp audio `in` to $\max(video\_in, \min(in, out - 0.05))$.
  - Clamp audio `out` to $\min(video\_out, \max(out, in + 0.05))$.

- [ ] **Step 3: Update `clear_timeline()` and `set_tracks()`**

In `set_tracks()`:
- Initialize `self._track_cut_ranges = {t['stream_index']: (0.0, self._duration_sec) for t in tracks}`.
- Default `self._selected_stream_index = video_idx`.

---

### Task 3: Timeline Widget UI - Mode Toggle & Interactive Track Selection

**Files:**
- Modify: `src/ui/timeline_widget.py:596-816`

**Interfaces:**
- Consumes: User clicks on mode toggle button, track cards, in/out buttons.
- Produces: Visual state updates on timeline toolbar and track list.

- [ ] **Step 1: Add Mode Toggle and Active Track Indicator to Timeline Controls Bar**

In `TimelineWidget._setup_ui()`:
- Add `btn_cut_mode = QPushButton("🔗 Cắt đồng bộ")` with tooltip and styling.
- Add `lbl_active_track = QLabel("Đang chỉnh: [🎬 Video]")` with styling.
- Connect `btn_cut_mode.clicked.connect(self._toggle_cut_mode)`.

- [ ] **Step 2: Add track selection signal and styling to `TrackHeadersWidget`**

In `TrackHeadersWidget`:
- Add signal `track_selected = Signal(int)` (stream_index).
- In `card.mousePressEvent`: emit `track_selected.emit(s_idx)`.
- Highlight active selected card with Cyan border (`border: 2px solid #00d2d3; background-color: #2a313d;`).
- Non-active cards retain default border (`border: 1px solid #2e3440; background-color: #22262f;`).

- [ ] **Step 3: Wire track selection and In/Out button actions to active track**

In `TimelineWidget`:
- Connect `self.headers_widget.track_selected.connect(self.select_track)`.
- When user clicks `📍 Đặt In [I]`:
  If `_cut_mode == "global"`: update all tracks.
  If `_cut_mode == "per_track"`: update `_selected_stream_index` track with constraints.
- When user clicks `🏁 Đặt Out [O]`:
  Update correspondingly.
- Update `lbl_in_val`, `lbl_out_val`, `lbl_cut_dur` to reflect the active track's cut points.

---

### Task 4: TimelineCanvas Visualization - Independent Per-Track Clip Blocks & Dim Overlays

**Files:**
- Modify: `src/ui/timeline_widget.py:57-595`

**Interfaces:**
- Consumes: `_track_cut_ranges`, `_tracks`, `_active_stream_indices`, `_selected_stream_index`.
- Produces: Custom painted timeline lanes with individual active/dimmed regions.

- [ ] **Step 1: Pass `track_ranges` and `selected_stream` to `TimelineCanvas`**

In `TimelineCanvas`:
- Add `set_track_ranges(ranges: dict[int, tuple[float, float]])`.
- Add `set_selected_stream(stream_index: int | None)`.

- [ ] **Step 2: Update `_draw_tracks` and `_draw_cut_overlay` for per-lane rendering**

In `TimelineCanvas._draw_tracks()`:
- For each track lane:
  - Obtain `(trk_in, trk_out) = self._track_cut_ranges.get(s_idx, (0.0, self._duration_sec))`.
  - Draw active clip block between $trk\_in$ and $trk\_out$ with full waveforms/filmstrips.
  - Draw dim overlay (`rgba(10, 12, 16, 185)`) on the excluded portions:
    - Left excluded: from $0$ to $trk\_in$.
    - Right excluded: from $trk\_out$ to total width.
  - If track is `_selected_stream_index`, draw subtle accent border around its lane header/bounds.

- [ ] **Step 3: Update Ruler overlay**

In `_draw_cut_overlay()`:
- Ruler flags `[I]` and `[O]` always represent the Master Video bounds or active track bounds.

---

### Task 5: Main Window Integration & End-to-End Verification

**Files:**
- Modify: `src/ui/main_window.py:366-450`

**Interfaces:**
- Consumes: `timeline_widget.get_track_ranges()`, `timeline_widget.get_cut_mode()`
- Produces: Multi-track cut command dispatched to `CutWorker`.

- [ ] **Step 1: Update `_start_cut()` in `src/ui/main_window.py`**

In `MainWindow._start_cut()`:
- Retrieve `track_ranges = self.timeline_widget.get_track_ranges()`.
- Pass `track_ranges=track_ranges` into `build_cut_command`.
- Include per-track details in cut summary status message.

- [ ] **Step 2: Run all unit tests**

Run: `python -m unittest discover tests`
Expected: ALL PASS

- [ ] **Step 3: Verify with real application data**

Launch app or run verification probe on sample video info to confirm command generation and UI integrity.

---

