"""Executor routing: every binding resolves to the right primitive (primitives are recorded, not posted)."""
import bindings
from actions import Actions, MODS
from events import Event
from synth import cfg


class Rec(Actions):
    def __init__(self, c):
        super().__init__(c, None)
        self.calls = []
        self._b, self._bt = (0, 0, 1001, 501), 1e18      # fixed 1001 x 501 screen

    def move_to(self, pt, dragging=False): self.calls.append(("move", pt, dragging))
    def _button(self, pt, down, right=False, count=1, middle=False):
        self.calls.append(("btn", down, "middle" if middle else "right" if right else "left", count))
    def key(self, code, flags=0): self.calls.append(("key", code, flags))
    def scroll(self, dy): self.calls.append(("scroll", dy))
    def media_key(self, k): self.calls.append(("media", k))
    def tile(self, mode): self.calls.append(("tile", mode))
    def _run(self, args): self.calls.append(("run", tuple(args)))
    def location(self): return (5.0, 6.0)


def gest(gid, pos=None):
    return Event("gesture", {"id": gid, "pos": pos}, pulse=True)


def run(ev, **b):
    c = cfg(bindings={**bindings.DEFAULT_BINDINGS, **b})
    a = Rec(c)
    a.execute(ev)
    return a.calls


def test_default_pinch_is_left_click_at_pos():
    c = run(gest("pinch", (0.5, 0.5)))
    assert c[0] == ("move", (500.0, 250.0), False)
    assert [x for x in c if x[0] == "btn"] == [("btn", True, "left", 1), ("btn", False, "left", 1)]


def test_rebinding_changes_the_button_and_cursor_fallback():
    c = run(gest("pinch"), pinch="right_click")
    assert c[0] == ("move", (5.0, 6.0), False)
    assert ("btn", True, "right", 1) in c
    assert ("btn", True, "middle", 1) in run(gest("pinch"), pinch="middle_click")


def test_double_pinch_after_click_adds_only_the_second_click():
    c = cfg()
    a = Rec(c)
    a.execute(gest("pinch", (0.5, 0.5)))
    a.calls.clear()
    a.execute(gest("double_pinch", (0.5, 0.5)))
    assert [x for x in a.calls if x[0] == "btn"] == [("btn", True, "left", 2), ("btn", False, "left", 2)]
    a.calls.clear()
    a.execute(gest("double_pinch", (0.5, 0.5)))          # alone: a full double click
    assert [x[3] for x in a.calls if x[0] == "btn" and x[1]] == [1, 2]


def test_discrete_keys_and_none():
    ctrl = MODS["control"]
    assert run(gest("swipe_left")) == [("key", 124, ctrl)]            # next space
    assert run(gest("swipe_right")) == [("key", 123, ctrl)]
    assert run(gest("pinch"), pinch="mission_control") == [("key", 126, ctrl)]
    assert run(gest("pinch"), pinch="app_windows") == [("key", 125, ctrl)]
    assert run(gest("pinch"), pinch="show_desktop") == [("key", 103, 0)]
    assert run(gest("pinch"), pinch="next_app") == [("key", 48, MODS["command"])]
    assert run(gest("pinch"), pinch="prev_app") == [("key", 48, MODS["command"] | MODS["shift"])]
    assert run(gest("pinch"), pinch="screenshot") == [("key", 20, MODS["command"] | MODS["shift"])]
    assert run(gest("pinch"), pinch="play_pause") == [("media", 16)]
    assert run(gest("pinch"), pinch="volume_up") == [("media", 0)]
    assert run(gest("pinch"), pinch="volume_down") == [("media", 1)]
    assert run(gest("pinch"), pinch="display_sleep") == [("run", ("pmset", "displaysleepnow"))]
    assert run(gest("palms_apart")) == [("tile", "fill")]
    assert run(gest("pinch"), pinch="none") == []


def test_every_action_id_is_implemented(monkeypatch):
    import actions
    osa = []
    monkeypatch.setattr(actions, "_osa", osa.append)
    for aid in bindings.ACTIONS:
        a = Rec(cfg())
        a.run(aid, (1.0, 2.0), 7)
        assert a.calls or osa or aid in ("none", "drag"), aid
    assert len(osa) == 1


def test_scroll_and_inverted_and_none():
    assert run(Event("scroll", 12)) == [("scroll", 12)]
    assert run(Event("scroll", 12), two_finger="scroll_inverted") == [("scroll", -12)]
    assert run(Event("scroll", 12), two_finger="none") == []


def test_drag_follows_the_fist_binding():
    c = run(Event("drag_start", (0.5, 0.5)))
    assert ("btn", True, "left", 1) in c
    assert run(Event("drag_start", (0.5, 0.5)), fist="mission_control") == []     # engine never sends it; guard anyway


def test_head_and_gaze_resolve_through_bindings():
    assert run(Event("head", "next_app")) == [("key", 48, MODS["command"])]
    assert run(Event("head", "next_app"), head_right="play_pause") == [("media", 16)]
    assert run(Event("gaze", "top-left")) == [("key", 126, MODS["control"])]
    assert run(Event("gaze", "bottom-right"), gaze_bottom_right="none") == []


def test_errors_never_escape(capsys):
    class Boom(Rec):
        def key(self, *a, **k): raise RuntimeError("x")
    Boom(cfg()).execute(gest("swipe_left"))
    assert "action error" in capsys.readouterr().out


# ---- real key sequences (CGEventPost recorded)
def _seq(code, flags):
    import Quartz
    import actions
    posted, downs = [], {}
    orig_post, orig_create = Quartz.CGEventPost, Quartz.CGEventCreateKeyboardEvent

    def create(src, kc, down):
        ev = orig_create(src, kc, down)
        downs[id(ev)] = (kc, down)
        return ev
    Quartz.CGEventCreateKeyboardEvent = create
    Quartz.CGEventPost = lambda tap, ev: posted.append((*downs[id(ev)], Quartz.CGEventGetFlags(ev)))
    try:
        Actions(cfg(), None).key_sequence(code, flags, sleep=lambda s: None)
    finally:
        Quartz.CGEventPost, Quartz.CGEventCreateKeyboardEvent = orig_post, orig_create
    return posted


def test_cmd_tab_presses_command_around_tab():
    import Quartz
    C = Quartz.kCGEventFlagMaskCommand
    got = _seq(48, MODS["command"])
    assert [(k, d) for k, d, _ in got] == [(55, True), (48, True), (48, False), (55, False)]
    assert [f & C for _, _, f in got] == [C, C, C, 0]


def test_cmd_shift_tab_orders_and_flags():
    import Quartz
    C, S = Quartz.kCGEventFlagMaskCommand, Quartz.kCGEventFlagMaskShift
    got = _seq(48, MODS["command"] | MODS["shift"])
    assert [(k, d) for k, d, _ in got] == [(56, True), (55, True), (48, True), (48, False), (55, False), (56, False)]
    m = C | S
    assert [f & m for _, _, f in got] == [S, m, m, m, S, 0]


def test_ctrl_arrow_carries_fn_and_numpad():
    import Quartz
    got = _seq(124, MODS["control"])
    assert [(k, d) for k, d, _ in got] == [(59, True), (124, True), (124, False), (59, False)]
    need = Quartz.kCGEventFlagMaskControl | Quartz.kCGEventFlagMaskSecondaryFn | Quartz.kCGEventFlagMaskNumericPad
    assert got[1][2] & need == need and got[2][2] & need == need
    assert got[3][2] & Quartz.kCGEventFlagMaskControl == 0


def test_f11_has_fn_and_plain_keys_have_none():
    import Quartz
    got = _seq(103, 0)
    assert [(k, d) for k, d, _ in got] == [(103, True), (103, False)]
    assert got[0][2] & Quartz.kCGEventFlagMaskSecondaryFn
