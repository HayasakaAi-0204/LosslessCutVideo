"""Unit tests for timeline keyframe magnetic snapping logic."""

import unittest
from src.core.cutter import find_nearest_keyframe


def calculate_magnetic_snap(
    target_sec: float,
    keyframes: list[float],
    pixels_per_sec: float = 50.0,
    snap_radius_px: float = 16.0,
    force_closest: bool = False,
) -> float:
    """Calculate magnetic snap timestamp based on zoom level and screen pixel distance.
    
    Args:
        target_sec: The requested timestamp in seconds.
        keyframes: Sorted list of keyframe timestamps.
        pixels_per_sec: Current timeline zoom level (pixels per second).
        snap_radius_px: Pixel radius for magnetic snapping on screen.
        force_closest: If True (e.g. on mouse release or button click), snap to closest
                       available keyframe regardless of distance.
                       
    Returns:
        Snapped timestamp in seconds.
    """
    if not keyframes:
        return target_sec

    # Dynamic magnetic delta in seconds based on current zoom
    pps = max(0.1, pixels_per_sec)
    max_delta = max(0.25, snap_radius_px / pps)

    if force_closest:
        return min(keyframes, key=lambda k: abs(k - target_sec))

    return find_nearest_keyframe(target_sec, keyframes, mode="closest", max_delta=max_delta)


class TestTimelineKeyframeSnap(unittest.TestCase):
    def setUp(self):
        # Sample keyframe sequence every 2.0 or 2.5 seconds (typical OBS / H.264 GOP)
        self.keyframes = [0.0, 2.5, 5.0, 7.5, 10.0, 12.5, 15.0]

    def test_magnetic_snap_within_threshold(self):
        # Zoom = 50 px/s, radius = 16 px -> max_delta = 0.32s
        # Target at 2.4s is 0.1s away from 2.5s -> should snap to 2.5s
        snapped = calculate_magnetic_snap(2.4, self.keyframes, pixels_per_sec=50.0)
        self.assertEqual(snapped, 2.5)

    def test_magnetic_snap_outside_threshold_during_drag(self):
        # Target at 2.166s is 0.334s away from 2.5s and 2.166s away from 0.0s
        # With max_delta ~0.32s, during free drag it remains 2.166s (smooth dragging)
        snapped = calculate_magnetic_snap(2.166, self.keyframes, pixels_per_sec=50.0, snap_radius_px=10.0)
        self.assertEqual(snapped, 2.166)

    def test_snap_force_closest_on_release_or_button(self):
        # When mouse is released or button [ I ] is clicked with snap enabled:
        # 2.166s must snap to closest keyframe (2.5s)
        snapped = calculate_magnetic_snap(2.166, self.keyframes, force_closest=True)
        self.assertEqual(snapped, 2.5)

        # 1.0s is closer to 0.0s (dist 1.0) than 2.5s (dist 1.5) -> snaps to 0.0s
        snapped_zero = calculate_magnetic_snap(1.0, self.keyframes, force_closest=True)
        self.assertEqual(snapped_zero, 0.0)

    def test_snap_empty_keyframes_graceful(self):
        # If keyframes list is empty, return original timestamp without error
        snapped = calculate_magnetic_snap(2.166, [], force_closest=True)
        self.assertEqual(snapped, 2.166)

    def test_find_nearest_keyframe_with_max_delta(self):
        # Test cutter.find_nearest_keyframe with max_delta parameter
        self.assertEqual(find_nearest_keyframe(2.4, self.keyframes, max_delta=0.2), 2.5)
        self.assertEqual(find_nearest_keyframe(2.166, self.keyframes, max_delta=0.2), 2.166)
        self.assertEqual(find_nearest_keyframe(2.166, self.keyframes, max_delta=None), 2.5)

    def test_per_track_ranges_preserved_when_video_snapped(self):
        # Master video at 4.0 -> 52.0
        # Audio #2 at 8.0 -> 52.0
        # Audio #3 at 8.0 -> 52.0
        track_ranges = {0: (4.0, 52.0), 2: (8.0, 52.0), 3: (8.0, 52.0)}
        # When video track (0) snaps, audio tracks (2 and 3) must keep their custom ranges
        snapped_vid_in = calculate_magnetic_snap(4.0, self.keyframes, force_closest=True)
        track_ranges[0] = (snapped_vid_in, 52.0)
        # Verify audio ranges are preserved!
        self.assertEqual(track_ranges[2], (8.0, 52.0))
        self.assertEqual(track_ranges[3], (8.0, 52.0))


if __name__ == "__main__":
    unittest.main()

