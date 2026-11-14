import json
import os

import pytest

import bindings
import preview
from events import Event
from tracking import HandObs


def test_camera_and_actions_logic():
    assert preview.camera_wanted(False, False) is False
    assert preview.camera_wanted(True, False) is True
    assert preview.camera_wanted(False, True) is True       # preview: window open while off
    assert preview.actions_live(False) is False              # the window alone never clicks
    assert preview.actions_live(True) is True
    assert preview.mode_label(False, True) == "preview · actions off"
    assert preview.mode_label(True, True) == "on · actions live"
    assert preview.mode_label(False, False) == "off"


def _hand():
    return HandObs([(i / 100, i / 200, -0.01 * i) for i in range(21)], "Right", 0.97)


def test_recording_line_schema_and_file(tmp_path):
    rec = preview.frame_record(12.5, 16 / 9, [_hand()])
    assert set(rec) == {"t", "aspect", "hands"}
    h = rec["hands"][0]
    assert set(h) == {"lms", "label", "conf"} and len(h["lms"]) == 21 and len(h["lms"][0]) == 3
    r = preview.Recorder(str(tmp_path / "rec"))
    assert not r.active
    path = r.start(100.0)
    assert r.active and path.endswith(".jsonl") and os.path.dirname(path) == str(tmp_path / "rec")
    r.write(100.0, 1.5, [_hand()])
    r.write(100.1, 1.5, [])
    assert r.elapsed(112.4) == 12
    r.stop()
    assert not r.active
    lines = open(path).read().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["aspect"] == 1.5 and first["hands"][0]["label"] == "Right" and first["hands"][0]["conf"] == 0.97
    assert json.loads(lines[1])["hands"] == []
    assert preview.recording_label(True, 12) == "recording · 12 s" and preview.recording_label(False, 0) == "record"


def test_gesture_log_names_events_and_keeps_last_eight():
    log = preview.GestureLog()
    log.add_events([Event("move", (0.1, 0.1)), Event("gesture", {"id": "pinch", "pos": None}),
                    Event("drag_end"), Event("scroll", 3), Event("head", "next_app")], 1.0)
    assert [g for _, _, g in log.snapshot()] == ["pinch", "two_finger", "head_right"]
    for i in range(20):
        log.add("swipe_left", 2.0 + i)
    snap = log.snapshot()
    assert len(snap) == preview.LOG_SIZE and snap[-1][0] == 23
    log.clear()
    assert log.snapshot() == []


def test_log_line_uses_bound_action():
    assert preview.log_line("pinch", {}) == "pinch → click"
    assert preview.log_line("pinch", {"bindings": {"pinch": "right_click"}}) == "pinch → right click"
    assert preview.log_line("pinch", {"bindings": {"pinch": "bogus"}}) == "pinch → click"


def test_readout_helpers():
    assert preview.finger_letters({"thumb": "ext", "index": "curl", "middle": "ext", "ring": "curl",
                                   "pinky": "curl"}) == "T i M r p"
    assert preview.meter_fraction(9.0) == 1.0 and preview.meter_fraction(-1) == 0.0
    assert preview.meter_fraction(0.35, 0.7) == pytest.approx(0.5)


def test_inspector_layout_and_live_geometry():
    pytest.importorskip("AppKit")
    from ui import inspector, live
    items, total = inspector.layout(bindings.groups())
    gids = [k for kind, k, y, h in items if kind == "gesture"]
    assert gids == list(bindings.GESTURES)
    assert [k for kind, k, y, h in items if kind == "header"] == [g for g, _ in bindings.groups()]
    ys = [y for _, _, y, _ in items]
    assert ys == sorted(ys) and total > ys[-1]
    x, y, w, h = live.fit_rect(16 / 9, 0, 0, 408, 230)
    assert (w, h) == pytest.approx((408, 229.5)) and x == 0
    x, y, w, h = live.fit_rect(4 / 3, 0, 0, 408, 230)
    assert h == 230 and w == pytest.approx(230 * 4 / 3) and x == pytest.approx((408 - w) / 2)
    # the image is mirrored: a landmark at x=0.1 appears near the right edge
    assert live.to_view((0.1, 0.5, 0), (10, 20, 100, 50)) == pytest.approx((100.0, 45.0))


def test_shared_state_has_preview_slots():
    from state import SharedState
    d = SharedState().get()
    assert d["window_open"] is False and d["preview"] is None and d["recording"] is None
