import json
import os

import pytest

import bindings
import preview
from events import Event
from tracking import HandObs


def test_camera_runs_only_while_gestyq_is_on():
    assert preview.camera_wanted(False) is False             # off = camera off, a window open or not
    assert preview.camera_wanted(True) is True
    assert preview.mode_label(False) == "off · camera off" and preview.mode_label(True) == "on"
    assert not hasattr(preview, "actions_live")               # no preview mode any more


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


def test_shared_state_has_live_slots_and_no_preview():
    from state import SharedState
    d = SharedState().get()
    assert d["window_open"] is False and d["live"] is None and d["recording"] is None and "preview" not in d


class _Cam:
    """A camera that records being opened / closed."""
    def __init__(self):
        import types
        self.cap, self.opened, self.closed, self.reads = None, 0, 0, 0
        self.device, self.note = types.SimpleNamespace(uid="u1", name="test camera"), ""

    def open(self):
        self.opened += 1
        self.cap = object()
        return True

    def read(self):
        import time
        import numpy as np
        time.sleep(0.004)
        self.reads += 1
        return True, np.zeros((72, 128, 3), np.uint8)

    def close(self):
        if self.cap is not None:
            self.closed += 1
        self.cap = None


def _wait(cond, timeout=3.0):
    import time
    t = time.time()
    while time.time() - t < timeout:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_off_means_the_camera_is_closed_even_with_the_window_open(monkeypatch):
    import types
    import actions
    import vision
    from roi import FULL, Plan
    from state import SharedState
    from synth import cfg
    monkeypatch.setattr(vision, "ensure_models", lambda: None)
    st, c = SharedState(), cfg()
    v = vision.VisionThread(st, c, actions.Actions(c, st))
    v.cam = cam = _Cam()
    v.pipe = types.SimpleNamespace(run=lambda f, now, ts, ts_f: ([], None, None, Plan(FULL, False, 0.0)),
                                   reset=lambda: None)
    v.start()
    try:
        v.set_window_open(True)                                # the window is open and gestyq is OFF
        import time
        time.sleep(0.3)
        assert cam.opened == 0 and cam.cap is None and cam.reads == 0
        d = st.get()
        assert d["camera"] == "off" and d["live"] is None and d["window_open"] is True and d["enabled"] is False
        v.set_enabled(True)                                    # turning on from the window starts camera + actions
        assert _wait(lambda: cam.opened == 1 and st.get()["live"] is not None)
        assert st.get()["camera"] == "ok"
        v.set_enabled(False)                                   # off: the camera closes, the window stays open
        assert _wait(lambda: cam.cap is None and st.get()["camera"] == "off")
        assert cam.closed == 1 and st.get()["live"] is None and st.get()["window_open"] is True
        reads = cam.reads
        time.sleep(0.2)
        assert cam.reads == reads and cam.opened == 1          # nothing reads or reopens while off
        v.set_window_open(False)
        v.set_enabled(True)                                    # on with the window closed: camera, no live view
        assert _wait(lambda: cam.opened == 2)
        time.sleep(0.15)
        assert st.get()["live"] is None
    finally:
        v.stop()
        v.join(timeout=3)
    assert cam.cap is None


def test_asleep_display_blocks_blind_actions_but_hands_wake_it():
    import types
    import vision
    from desktop import Desktop
    from events import Event
    from state import SharedState
    from synth import cfg, make_hand
    from tracking import HandObs

    class Act:
        def __init__(self):
            self.ran, self.woke, self.asleep, self.desktop = [], 0, True, Desktop()
        def execute(self, e): self.ran.append(e.kind)
        def display_asleep(self): return self.asleep
        def wake_display(self): self.woke += 1
        def release_all(self): pass
    a = Act()
    v = vision.VisionThread(SharedState(), cfg(), a)
    v.set_enabled(True)
    hand = lambda x: [HandObs(make_hand("right", x=x), "Left", 0.9)]
    ev = [Event("gesture", {"id": "pinch", "pos": None}, pulse=True), Event("drag_end", None), Event("move", (0.5, 0.5))]
    v._wake(10.0, hand(0.40), [])                              # first sight of a hand while asleep: wakes
    assert v.asleep and a.woke == 1
    v._emit(ev)
    assert a.ran == ["drag_end"]                               # no blind click or move; a held drag is still released
    v._wake(10.5, hand(0.45), [])                              # rate limited to once per 2 s
    assert a.woke == 1
    v._wake(12.1, hand(0.50), [])
    assert a.woke == 2
    v._wake(14.5, hand(0.50), [])                              # a still hand does not wake it
    assert a.woke == 2
    v._wake(16.7, hand(0.50), ev)                              # a gesture does
    assert a.woke == 3
    v.set_enabled(False)
    v._wake(20.0, hand(0.9), [])
    assert a.woke == 3                                         # off: never
    v.set_enabled(True)
    a.asleep, v.asleep_t = False, -1e9
    v._wake(30.0, hand(0.3), [])
    assert not v.asleep and a.woke == 3
    v._emit(ev)
    assert a.ran[-3:] == ["gesture", "drag_end", "move"]       # awake: everything runs
    v.no_wake_until = 100.0                                    # the user just told it to sleep the display
    a.asleep, v.asleep_t = True, -1e9
    v._wake(40.0, hand(0.8), [])
    assert a.woke == 3


# ---------------------------------------------------------------- air-writing canvas (AppKit; skips elsewhere)
def test_canvas_view_draws_every_state_and_the_panel_never_takes_focus():
    pytest.importorskip("AppKit")
    import time
    from AppKit import NSApplication
    NSApplication.sharedApplication()
    from ui.canvas import CanvasPanel, CanvasView
    now = time.monotonic()
    line = ((0.0, 0.0), (0.5, -0.5), (1.0, 0.0), (1.0, 1.0))
    base = {"n": 1, "strokes": (), "tip": (0.0, 0.0), "pen": False, "hand": True, "armed": True, "result": None,
            "typed": "hel lo"}
    res = lambda **k: {"t": now, "char": "g", "alt": None, "why": "", "strokes": (line,), **k}
    states = [None, base, dict(base, armed=False), dict(base, hand=False, tip=None),
              dict(base, strokes=(line, line[:2]), pen=True), dict(base, strokes=(((0, 0), (9, 9)),)),
              dict(base, result=res(alt="q")), dict(base, result=res(char=None, why="reject")),
              dict(base, result=res(char=None, why="small", strokes=())), dict(base, strokes=((( 0.0, 0.0),),))]
    for st in states:
        v = CanvasView.alloc().initWithScale_(48.0)
        v.set_snap(st, now)
        rep = v.render()
        assert rep.pixelsWide() == 640 and rep.pixelsHigh() == 400
    p = CanvasPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        ((0, 0), (320, 200)), 0, 2, False)
    assert p.canBecomeKeyWindow() is False and p.canBecomeMainWindow() is False
    from ui.canvas import CanvasController

    class M:
        cfg = {"write": {"ink_scale": 48}}
    c = CanvasController(M())
    panel = c._make()
    assert panel.ignoresMouseEvents() is True and panel.canBecomeKeyWindow() is False
    assert panel.styleMask() & 128                                   # NSWindowStyleMaskNonactivatingPanel
    assert panel.hidesOnDeactivate() is False and panel.hasShadow() is False
