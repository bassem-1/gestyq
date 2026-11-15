"""Executor routing: every binding resolves to the right primitive (primitives are recorded, not posted)."""
import pytest

import bindings
from actions import Actions, MODS
from events import Event
from state import SharedState
from synth import cfg


class Rec(Actions):
    def __init__(self, c):
        super().__init__(c, SharedState())
        self.calls = []
        self.desktop.set([(0, 0, 1001, 501)])             # fixed 1001 x 501 screen
        self._poll_t = 1e18                               # never re-query the real displays

    def move_to(self, pt, dragging=False): self.calls.append(("move", pt, dragging))
    def _button(self, pt, down, right=False, count=1, middle=False):
        self.calls.append(("btn", down, "middle" if middle else "right" if right else "left", count))
    def key(self, code, flags=0): self.calls.append(("key", code, flags))
    def type_text(self, s): self.calls.append(("text", s))
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
        assert a.calls or osa or a.state.commands or aid in ("none", "drag"), aid
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


# ---- the pointer covers every display
from desktop import Desktop

SIDE = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
L_SHAPE = [(0, 0, 1000, 1000), (1000, 500, 1000, 500)]
NEG = [(0, 0, 1440, 900), (-1920, -180, 1920, 1080)]          # an external display left of and above the origin


def on_a_display(pt, rects):
    return any(r[0] <= pt[0] <= r[0] + r[2] and r[1] <= pt[1] <= r[1] + r[3] for r in rects)


def test_union_mapping_reaches_every_display_and_snaps_dead_areas():
    a = Rec(cfg())
    a.desktop.set(SIDE)
    assert a.to_px(0.0, 0.0) == (0.0, 0.0) and a.to_px(1.0, 1.0) == (3839.0, 1079.0)
    assert a.to_px(0.75, 0.5)[0] > 1920 and a.to_px(0.25, 0.5)[0] < 1920
    a.desktop.set(L_SHAPE)
    assert a.to_px(0.9, 0.1) == pytest.approx((1799.1, 500.0))                # top-right corner is dead: snapped down to the display
    for nx in (0.0, 0.3, 0.55, 0.9, 1.0):
        for ny in (0.0, 0.2, 0.49, 0.8, 1.0):
            assert on_a_display(a.to_px(nx, ny), L_SHAPE), (nx, ny)
    a.desktop.set(NEG)                                          # negative global coordinates
    assert a.to_px(0.0, 0.0) == (-1920.0, -180.0)
    for nx in (0.0, 0.4, 0.5, 0.6, 1.0):
        assert on_a_display(a.to_px(nx, 0.0), NEG) and on_a_display(a.to_px(nx, 1.0), NEG)


def test_clicks_and_drags_land_on_the_second_display():
    a = Rec(cfg())
    a.desktop.set(SIDE)
    a.execute(gest("pinch", (0.75, 0.5)))
    x, y = a.calls[0][1]
    assert 1920 <= x < 3840 and abs(y - 539.5) < 1
    a.calls.clear()
    a.execute(Event("drag_start", (0.9, 0.5)))
    a.execute(Event("drag_move", (0.6, 0.5)))
    a.execute(Event("drag_end", (0.6, 0.5)))
    moves = [c for c in a.calls if c[0] == "move"]
    assert moves[-1][1][0] > 1920 and all(m[2] for m in moves[1:])
    assert [c[1] for c in a.calls if c[0] == "btn"] == [True, False] and not a.dragging


def test_display_hot_swap_mid_drag_never_sticks_and_the_cursor_stays_on_a_display():
    a = Rec(cfg())
    a.desktop.set(SIDE)
    a.execute(Event("drag_start", (0.9, 0.5)))
    assert a.dragging
    a.desktop.set(SIDE[:1])                                      # external display unplugged
    a.calls.clear()
    # what refresh_displays() does on a change, without touching the real displays
    a.release_all()
    a.last = None
    assert not a.dragging and [c[1] for c in a.calls if c[0] == "btn"] == [False]     # button released
    a.calls.clear()
    a.execute(Event("drag_move", (0.9, 0.5)))                    # the engine still thinks it drags
    a.execute(Event("drag_end", (0.9, 0.5)))
    assert not [c for c in a.calls if c[0] == "btn"]             # no second release, no stray press
    assert all(m[2] is False and on_a_display(m[1], SIDE[:1]) for m in a.calls if m[0] == "move")
    a.desktop.set(SIDE)                                          # plugged back in: the whole union again
    assert a.to_px(1.0, 0.5)[0] == 3839.0


def test_desktop_changes_are_visible_across_threads():
    d = Desktop(SIDE[:1])
    seen = []
    import threading
    t = threading.Thread(target=lambda: seen.append((d.count(), d.bounds())))
    d.set(SIDE)
    t.start(); t.join()
    assert seen == [(2, (0, 0, 3840, 1080))]


# ---------------------------------------------------------------- hot corners, HID source, wake, key queue
def test_hot_corners_setting_keeps_the_gesture_cursor_off_the_corners():
    a = Rec(cfg())                                         # default: corners reachable
    assert a.to_px(0.0, 0.0) == (0.0, 0.0) and a.to_px(1.0, 1.0) == (1000.0, 500.0)
    a = Rec(cfg(hot_corners=False))
    assert a.to_px(0.0, 0.0) == (4.0, 4.0) and a.to_px(1.0, 1.0) == (996.0, 496.0)
    assert a.to_px(0.0, 0.5) == (0.0, 250.0)               # edges stay reachable
    a.cfg["hot_corners"] = True                             # live: the window flips the same dict
    assert a.to_px(0.0, 0.0) == (0.0, 0.0)


def test_posted_pointer_events_use_the_hid_system_state_source(monkeypatch):
    import Quartz
    created, posted = [], []
    monkeypatch.setattr(Quartz, "CGEventSourceCreate", lambda state: ("src", state))
    monkeypatch.setattr(Quartz, "CGEventCreateMouseEvent", lambda src, typ, pt, btn: created.append(("mouse", src)) or object())
    monkeypatch.setattr(Quartz, "CGEventCreateScrollWheelEvent", lambda src, unit, n, dy: created.append(("scroll", src)) or object())
    monkeypatch.setattr(Quartz, "CGEventSetIntegerValueField", lambda *a: None)
    monkeypatch.setattr(Quartz, "CGWarpMouseCursorPosition", lambda pt: None)
    monkeypatch.setattr(Quartz, "CGAssociateMouseAndMouseCursorPosition", lambda b: None)
    monkeypatch.setattr(Quartz, "CGEventPost", lambda tap, ev: posted.append(tap))
    a = Actions(cfg(), None)
    a.move_to((10.0, 10.0))
    a._button((10.0, 10.0), True)
    a.scroll(5)
    hid = ("src", Quartz.kCGEventSourceStateHIDSystemState)
    assert [k for k, _ in created] == ["mouse", "mouse", "scroll"] and all(s == hid for _, s in created)
    assert posted == [Quartz.kCGHIDEventTap] * 3


def test_wake_display_declares_user_activity_and_falls_back_to_caffeinate():
    calls = []

    class W(Rec):
        def _declare_user_activity(self): calls.append("iokit")
    a = W(cfg())
    a.wake_display()
    assert calls == ["iokit"] and not [c for c in a.calls if c[0] == "run"]

    class Broken(Rec):
        def _declare_user_activity(self): raise OSError("no iokit")
    b = Broken(cfg())
    b.wake_display()
    assert ("run", ("caffeinate", "-u", "-t", "2")) in b.calls


def test_quick_successive_chords_are_never_dropped_or_overlapped(monkeypatch):
    import threading
    import time
    import actions as A
    monkeypatch.setattr(A, "KEY_GAP", 0.005)
    played, active, worst = [], [0], [0]
    lock = threading.Lock()

    class K(Actions):
        def key_sequence(self, code, flags=0, sleep=time.sleep):
            with lock:
                active[0] += 1
                worst[0] = max(worst[0], active[0])
            time.sleep(0.02)                                # a chord takes a while to play
            played.append((code, flags))
            with lock:
                active[0] -= 1
    a = K(cfg(), None)
    for i in range(6):                                      # six flicks' worth of ctrl+arrow in a burst
        a.run("next_space" if i % 2 == 0 else "prev_space")
    t = time.time()
    while len(played) < 6 and time.time() - t < 3:
        time.sleep(0.01)
    ctrl = MODS["control"]
    assert played == [(124, ctrl), (123, ctrl)] * 3 and worst[0] == 1


def test_minimize_and_full_screen_send_their_shortcuts(monkeypatch):
    import actions as A
    import config
    from state import SharedState
    act = A.Actions(config.load(), SharedState())
    sent = []
    monkeypatch.setattr(act, "key", lambda code, flags=0: sent.append((code, flags)))
    act.run("minimize")
    act.run("full_screen")
    assert sent == [(A.K_M, A.MODS["command"]), (A.K_F, A.MODS["command"] | A.MODS["control"])]


# ---------------------------------------------------------------- air-writing: typing
def test_type_text_posts_one_key_down_and_up_with_the_unicode_string_and_no_flags(monkeypatch):
    import Quartz
    made, posted = [], []
    real_create = Quartz.CGEventCreateKeyboardEvent
    real_set = Quartz.CGEventKeyboardSetUnicodeString

    def create(src, code, down):
        ev = real_create(src, code, down)
        made.append({"ev": ev, "code": code, "down": down, "text": None, "flags": None})
        return ev

    def set_text(ev, n, s):
        next(m for m in made if m["ev"] is ev)["text"] = (n, s)
        return real_set(ev, n, s)

    def set_flags(ev, fl):
        next(m for m in made if m["ev"] is ev)["flags"] = fl

    monkeypatch.setattr(Quartz, "CGEventCreateKeyboardEvent", create)
    monkeypatch.setattr(Quartz, "CGEventKeyboardSetUnicodeString", set_text)
    monkeypatch.setattr(Quartz, "CGEventSetFlags", set_flags)
    monkeypatch.setattr(Quartz, "CGEventPost", lambda tap, ev: posted.append(next(m for m in made if m["ev"] is ev)))
    Actions(cfg(), None).type_string("a")
    assert [(m["down"], m["text"], m["flags"]) for m in posted] == [(True, (1, "a"), 0), (False, (1, "a"), 0)]


def test_write_events_and_space_delete_enter_route_to_the_right_primitives():
    assert run(Event("write", {"op": "text", "text": "h"}, pulse=True)) == [("text", "h")]
    assert run(Event("write", {"op": "enter"}, pulse=True)) == [("key", 36, 0)]
    assert run(gest("write_flick_right")) == [("text", " ")]
    assert run(gest("write_flick_left")) == [("key", 51, 0)]
    assert run(gest("write_flick_left"), write_flick_left="none") == []
    assert run(gest("pinch"), pinch="enter") == [("key", 36, 0)]
    assert run(gest("pinch"), pinch="type_space") == [("text", " ")]


def test_toggle_write_queues_a_command_for_the_main_thread():
    from state import SharedState
    a = Rec(cfg(bindings={**bindings.DEFAULT_BINDINGS, "pinch": "toggle_write"}))
    a.state = SharedState()
    a.execute(gest("pinch"))
    assert a.state.pop_commands() == [("toggle_write", None)]


def test_text_and_chords_play_in_order_on_the_key_worker(monkeypatch):
    import time
    import actions as A
    monkeypatch.setattr(A, "KEY_GAP", 0.001)
    played = []

    class K(Actions):
        def key_sequence(self, code, flags=0, sleep=time.sleep): played.append(("key", code))
        def type_string(self, s): played.append(("text", s))
    a = K(cfg(), None)
    a.type_text("h"); a.key(51); a.type_text("i"); a.key(36)
    t = time.time()
    while len(played) < 4 and time.time() - t < 2:
        time.sleep(0.01)
    assert played == [("text", "h"), ("key", 51), ("text", "i"), ("key", 36)]


def test_bindings_for_writing_are_stable_and_listed():
    assert bindings.DEFAULT_BINDINGS["write_flick_right"] == "type_space" and bindings.DEFAULT_BINDINGS["write_flick_left"] == "backspace"
    assert ("writing", ["write_flick_right", "write_flick_left"]) in bindings.groups()
    assert {"type_space", "backspace", "enter", "toggle_write"} <= set(bindings.choices("write_flick_left"))
    assert bindings.gesture_of(Event("write", {"op": "text", "text": "a"})) is None
