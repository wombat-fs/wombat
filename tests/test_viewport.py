"""Tests for Viewport (pure coordinate mapping) and speed_color heatmap."""
import pytest

from wombat.ui.timeline.viewport import Viewport


def _vp(**kwargs) -> Viewport:
    defaults = dict(offset=0.0, visible_time=30.0, width=600, lane_top=24, lane_height=120)
    defaults.update(kwargs)
    return Viewport(**defaults)


# ------------------------------------------------------------------ time_to_x

def test_time_to_x_at_left_edge():
    vp = _vp(offset=10.0)
    assert vp.time_to_x(10.0) == pytest.approx(0.0)


def test_time_to_x_at_right_edge():
    vp = _vp(offset=0.0, visible_time=30.0, width=600)
    assert vp.time_to_x(30.0) == pytest.approx(600.0)


def test_time_to_x_midpoint():
    vp = _vp(offset=0.0, visible_time=20.0, width=400)
    assert vp.time_to_x(10.0) == pytest.approx(200.0)


def test_time_to_x_before_offset_is_negative():
    vp = _vp(offset=5.0, visible_time=10.0, width=100)
    assert vp.time_to_x(4.0) < 0.0


def test_time_to_x_zero_width_returns_zero():
    vp = _vp(width=0)
    assert vp.time_to_x(999.0) == 0.0


# ------------------------------------------------------------------ x_to_time

def test_x_to_time_at_left():
    vp = _vp(offset=5.0)
    assert vp.x_to_time(0.0) == pytest.approx(5.0)


def test_x_to_time_at_right():
    vp = _vp(offset=0.0, visible_time=30.0, width=600)
    assert vp.x_to_time(600.0) == pytest.approx(30.0)


def test_x_to_time_zero_width_returns_offset():
    vp = _vp(width=0, offset=7.0)
    assert vp.x_to_time(100.0) == pytest.approx(7.0)


# ------------------------------------------------------------------ round-trips

def test_round_trip_time_x():
    vp = _vp(offset=10.0, visible_time=20.0, width=800)
    for t in [10.0, 15.0, 17.5, 25.0, 30.0]:
        assert vp.x_to_time(vp.time_to_x(t)) == pytest.approx(t)


def test_round_trip_x_time():
    vp = _vp(offset=0.0, visible_time=60.0, width=1200)
    for x in [0.0, 100.0, 600.0, 1200.0]:
        assert vp.time_to_x(vp.x_to_time(x)) == pytest.approx(x)


# ------------------------------------------------------------------ pos_to_y

def test_pos_to_y_bottom_is_max_y():
    vp = _vp(lane_top=24, lane_height=100)
    assert vp.pos_to_y(0.0) == pytest.approx(124.0)   # lane_top + lane_height


def test_pos_to_y_top_is_lane_top():
    vp = _vp(lane_top=24, lane_height=100)
    assert vp.pos_to_y(100.0) == pytest.approx(24.0)   # exactly lane_top


def test_pos_to_y_midpoint():
    vp = _vp(lane_top=0, lane_height=100)
    assert vp.pos_to_y(50.0) == pytest.approx(50.0)


# ------------------------------------------------------------------ y_to_pos

def test_y_to_pos_at_lane_top():
    vp = _vp(lane_top=24, lane_height=100)
    assert vp.y_to_pos(24.0) == pytest.approx(100.0)


def test_y_to_pos_at_lane_bottom():
    vp = _vp(lane_top=24, lane_height=100)
    assert vp.y_to_pos(124.0) == pytest.approx(0.0)


def test_y_to_pos_zero_height_returns_zero():
    vp = _vp(lane_height=0)
    assert vp.y_to_pos(50.0) == 0.0


# ------------------------------------------------------------------ pos round-trips

def test_round_trip_pos_y():
    vp = _vp(lane_top=24, lane_height=200)
    for pos in [0.0, 25.0, 50.0, 75.0, 100.0]:
        assert vp.y_to_pos(vp.pos_to_y(pos)) == pytest.approx(pos)


def test_round_trip_y_pos():
    vp = _vp(lane_top=24, lane_height=200)
    for y in [24.0, 74.0, 124.0, 174.0, 224.0]:
        assert vp.pos_to_y(vp.y_to_pos(y)) == pytest.approx(y)


# ------------------------------------------------------------------ zoom

def test_zoom_in_reduces_visible_time():
    vp = _vp(visible_time=30.0)
    assert vp.zoom(0.5, 300.0).visible_time == pytest.approx(15.0)


def test_zoom_out_increases_visible_time():
    vp = _vp(visible_time=30.0)
    assert vp.zoom(2.0, 300.0).visible_time == pytest.approx(60.0)


def test_zoom_anchor_time_preserved():
    vp = _vp(offset=0.0, visible_time=30.0, width=600)
    anchor_x = 300.0
    anchor_t = vp.x_to_time(anchor_x)
    zoomed = vp.zoom(0.5, anchor_x)
    assert zoomed.x_to_time(anchor_x) == pytest.approx(anchor_t)


def test_zoom_anchor_preserved_at_edges():
    vp = _vp(offset=5.0, visible_time=20.0, width=1000)
    for anchor_x in [0.0, 500.0, 999.0]:
        anchor_t = vp.x_to_time(anchor_x)
        for factor in [0.5, 2.0, 0.1, 10.0]:
            zoomed = vp.zoom(factor, anchor_x)
            assert zoomed.x_to_time(anchor_x) == pytest.approx(anchor_t, abs=1e-9)


def test_zoom_clamps_to_min():
    vp = _vp(visible_time=Viewport.MIN_VISIBLE)
    zoomed = vp.zoom(0.01, 300.0)
    assert zoomed.visible_time == pytest.approx(Viewport.MIN_VISIBLE)


def test_zoom_clamps_to_max():
    vp = _vp(visible_time=Viewport.MAX_VISIBLE)
    zoomed = vp.zoom(100.0, 300.0)
    assert zoomed.visible_time == pytest.approx(Viewport.MAX_VISIBLE)


def test_zoom_at_min_still_preserves_anchor():
    vp = _vp(visible_time=Viewport.MIN_VISIBLE, offset=5.0, width=600)
    anchor_x = 200.0
    anchor_t = vp.x_to_time(anchor_x)
    zoomed = vp.zoom(0.001, anchor_x)
    assert zoomed.visible_time == pytest.approx(Viewport.MIN_VISIBLE)
    assert zoomed.x_to_time(anchor_x) == pytest.approx(anchor_t)


def test_zoom_preserves_width_and_lane():
    vp = _vp(width=800, lane_top=24, lane_height=200)
    zoomed = vp.zoom(0.5, 400.0)
    assert zoomed.width == 800
    assert zoomed.lane_top == 24
    assert zoomed.lane_height == 200


# ------------------------------------------------------------------ pan

def test_pan_forward_increases_offset():
    vp = _vp(offset=10.0)
    assert vp.pan(5.0).offset == pytest.approx(15.0)


def test_pan_backward_decreases_offset():
    vp = _vp(offset=10.0)
    assert vp.pan(-3.0).offset == pytest.approx(7.0)


def test_pan_preserves_visible_time():
    vp = _vp(visible_time=20.0)
    assert vp.pan(5.0).visible_time == pytest.approx(20.0)


def test_pan_preserves_dimensions():
    vp = _vp(width=800, lane_top=24, lane_height=200)
    panned = vp.pan(10.0)
    assert panned.width == 800
    assert panned.lane_top == 24
    assert panned.lane_height == 200


def test_pan_zero_is_identity():
    vp = _vp(offset=7.0, visible_time=15.0)
    panned = vp.pan(0.0)
    assert panned.offset == pytest.approx(7.0)
    assert panned.visible_time == pytest.approx(15.0)


# ------------------------------------------------------------------ time_window

def test_time_window_bounds():
    vp = _vp(offset=5.0, visible_time=20.0)
    t0, t1 = vp.time_window()
    assert t0 == pytest.approx(5.0)
    assert t1 == pytest.approx(25.0)


def test_time_window_width_matches_visible_time():
    vp = _vp(offset=0.0, visible_time=30.0)
    t0, t1 = vp.time_window()
    assert (t1 - t0) == pytest.approx(vp.visible_time)


# ------------------------------------------------------------------ heatmap

def test_speed_color_slow_is_blue() -> None:
    from wombat.ui.timeline.heatmap import speed_color
    c = speed_color(0.0)
    assert c.blueF() > c.redF()


def test_speed_color_fast_is_red() -> None:
    from wombat.ui.timeline.heatmap import MAX_SPEED, speed_color
    c = speed_color(MAX_SPEED)
    assert c.redF() > c.blueF()


def test_speed_color_clamps_above_max() -> None:
    from wombat.ui.timeline.heatmap import MAX_SPEED, speed_color
    c1 = speed_color(MAX_SPEED)
    c2 = speed_color(MAX_SPEED * 10)
    assert c1.rgb() == c2.rgb()


def test_speed_color_red_increases_with_speed() -> None:
    from wombat.ui.timeline.heatmap import MAX_SPEED, speed_color
    speeds = [0.0, MAX_SPEED * 0.25, MAX_SPEED * 0.5, MAX_SPEED * 0.75, MAX_SPEED]
    reds = [speed_color(s).redF() for s in speeds]
    for i in range(len(reds) - 1):
        assert reds[i] <= reds[i + 1]


def test_speed_color_blue_decreases_with_speed() -> None:
    from wombat.ui.timeline.heatmap import MAX_SPEED, speed_color
    speeds = [0.0, MAX_SPEED * 0.25, MAX_SPEED * 0.5, MAX_SPEED * 0.75, MAX_SPEED]
    blues = [speed_color(s).blueF() for s in speeds]
    for i in range(len(blues) - 1):
        assert blues[i] >= blues[i + 1]
