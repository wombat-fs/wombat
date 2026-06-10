"""Headless tests for VideoPlayer state and logical-time bookkeeping.

We mock the mpv.MPV handle so these run without a display or libmpv installation.
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _make_mock_mpv():
    """Return a mock that satisfies VideoPlayer.__init__ without touching libmpv."""
    m = MagicMock()
    m.time_pos = None
    m.container_fps = None
    m.estimated_vf_fps = None
    m.dwidth = None
    m.dheight = None
    m.path = None
    m.pause = True
    m.speed = 1.0
    m.volume = 100.0
    m.mute = False
    # property_observer and event_callback are decorators — return identity
    m.property_observer.return_value = lambda fn: fn
    m.event_callback.return_value = lambda fn: fn
    return m


class TestVideoPlayerInitialState(unittest.TestCase):
    def _make_player(self):
        mock_mpv = _make_mock_mpv()
        with patch("wombat.playback.player.mpv") as mock_module:
            mock_module.MPV.return_value = mock_mpv
            from wombat.playback.player import VideoPlayer
            player = VideoPlayer.__new__(VideoPlayer)
            # Call QObject.__init__ via super() chain requires a QApplication.
            # Skip Qt init and set attributes directly for unit testing.
            player._mpv = mock_mpv
            player._logical_time = 0.0
            player._actual_time = 0.0
            player._duration = 0.0
            player._fps = 0.0
            player._is_paused = True
            player._is_loaded = False
            player._speed = 1.0
        return player

    def test_initial_state(self):
        p = self._make_player()
        self.assertFalse(p.is_loaded)
        self.assertTrue(p.is_paused)
        self.assertEqual(p.logical_time, 0.0)
        self.assertEqual(p.actual_time, 0.0)
        self.assertEqual(p.duration, 0.0)
        self.assertEqual(p.speed, 1.0)
        self.assertEqual(p.video_size, (0, 0))

    def test_fps_zero_before_load(self):
        p = self._make_player()
        self.assertEqual(p.fps, 0.0)
        self.assertEqual(p.frame_time, 0.0)

    def test_fps_nonzero(self):
        p = self._make_player()
        p._fps = 30.0
        self.assertAlmostEqual(p.fps, 30.0)
        self.assertAlmostEqual(p.frame_time, 1.0 / 30.0)


class TestLogicalTimeBookkeeping(unittest.TestCase):
    def _make_player(self):
        mock_mpv = _make_mock_mpv()
        from wombat.playback.player import VideoPlayer
        p = VideoPlayer.__new__(VideoPlayer)
        p._mpv = mock_mpv
        p._logical_time = 0.0
        p._actual_time = 0.0
        p._duration = 120.0
        p._fps = 24.0
        p._is_paused = True
        p._is_loaded = True
        p._speed = 1.0
        return p

    def test_seek_exact_sets_logical_immediately(self):
        p = self._make_player()
        p.seek_exact(42.5)
        self.assertEqual(p.logical_time, 42.5)
        p._mpv.command.assert_called_once_with("seek", 42.5, "absolute+exact")

    def test_seek_exact_multiple(self):
        p = self._make_player()
        p.seek_exact(10.0)
        p.seek_exact(20.0)
        self.assertEqual(p.logical_time, 20.0)

    def test_seek_percent(self):
        p = self._make_player()
        p.seek_percent(0.5)  # 50% of 120s = 60s
        self.assertAlmostEqual(p.logical_time, 60.0)

    def test_seek_relative(self):
        p = self._make_player()
        p._logical_time = 10.0
        p.seek_relative(5.0)
        self.assertAlmostEqual(p.logical_time, 15.0)

    def test_seek_relative_clamps_at_zero(self):
        p = self._make_player()
        p._logical_time = 2.0
        p.seek_relative(-10.0)
        self.assertEqual(p.logical_time, 0.0)

    def test_step_frame_forward(self):
        p = self._make_player()
        p.step_frame(forward=True)
        p._mpv.command.assert_called_once_with("frame-step")

    def test_step_frame_backward(self):
        p = self._make_player()
        p.step_frame(forward=False)
        p._mpv.command.assert_called_once_with("frame-back-step")

    def test_logical_time_unchanged_by_play(self):
        p = self._make_player()
        p._logical_time = 7.0
        p.play()
        self.assertEqual(p.logical_time, 7.0)

    def test_set_speed(self):
        p = self._make_player()
        p.set_speed(2.0)
        self.assertEqual(p._mpv.speed, 2.0)


if __name__ == "__main__":
    unittest.main()
