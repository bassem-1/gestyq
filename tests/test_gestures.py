import math

from gestures import GestureEngine, caption_for, tile_rect
from synth import cfg, make_hand, obs, true_label


class Sim:
    def __init__(self, **over):
        self.c = cfg(**over)
        self.e = GestureEngine(self.c, screen=(1920, 1080))
        self.t = 0.0
        self.log = []          # (t, Event)

    def step(self, right=None, left=None, n=1):
        evs = []
        for _ in range(n):
            o = []
            if right is not None:
                o.append(obs(right, true_label("right")))
            if left is not None:
                o.append(obs(left, true_label("left")))
            ev = self.e.update(o, self.t)
            self.log += [(self.t, x) for x in ev]
            evs += ev
            self.t += 1 / 30
        return evs

    def kinds(self, kind):
        return [(t, e) for t, e in self.log if e.kind == kind]


def R(x=0.4, y=0.5, **kw):
    return make_hand("right", x=x, y=y, **kw)


def Lh(x=0.7, y=0.5, **kw):
    return make_hand("left", x=x, y=y, **kw)


def test_cursor_moves_mirrored_and_palm_anchored():
    s = Sim()
    s.step(R(0.5), n=10)
    first = s.kinds("move")[-1][1].value
    for i in range(30):
        s.step(R(0.5 - 0.005 * i))        # hand moves toward image-left = user's right
    last = s.kinds("move")[-1][1].value
    assert last[0] > first[0] + 0.1       # cursor moved right
    assert abs(last[1] - first[1]) < 0.02


def test_pointer_ignores_pose_changes_of_fingers():
    s = Sim()
    s.step(R(0.5), n=15)
    n0 = len(s.kinds("move"))
    s.step(R(0.5, thumb="curl", curl=(0, 0.3, 0.3, 0.3)), n=5)   # finger motion must not move the cursor
    assert len(s.kinds("move")) == n0


def test_pinch_clicks_at_position_before_onset_and_freezes():
    s = Sim()
    s.step(R(0.4), n=40)
    pre = s.kinds("move")[-1][1].value
    n_moves = len(s.kinds("move"))
    for k in range(1, 12):                          # pinch closes at once while the hand drifts away
        s.step(R(0.4 + 0.01 * k, pinch=1.0))
    clicks = s.kinds("click")
    assert len(clicks) == 1
    cx, cy, count = clicks[0][1].value
    assert count == 1 and clicks[0][1].pulse
    assert math.dist((cx, cy), pre) < 2e-3
    # nothing moved the cursor during the pinch except the one move back to the click position
    assert len(s.kinds("move")) <= n_moves + 1
    assert s.kinds("move")[-1][1].value == (cx, cy)
    # release: cursor follows again, from where the hand is now
    s.step(R(0.52), n=6)
    assert math.dist(s.kinds("move")[-1][1].value, pre) > 0.05
    assert len(s.kinds("click")) == 1


def test_double_click_within_gap():
    s = Sim()
    s.step(R(0.4), n=30)
    for _ in range(2):
        s.step(R(0.4, pinch=1.0), n=4)
        s.step(R(0.4), n=4)
    cl = s.kinds("click")
    assert [e.value[2] for _, e in cl] == [1, 2]
    s.step(R(0.4), n=30)
    s.step(R(0.4, pinch=1.0), n=4)
    assert s.kinds("click")[-1][1].value[2] == 1      # too late for a double


def test_single_frame_pinch_blip_is_not_a_click():
    s = Sim()
    s.step(R(0.4), n=30)
    s.step(R(0.4, pinch=1.0))
    s.step(R(0.4), n=10)
    assert not s.kinds("click")


FIST = dict(curl=(1, 1, 1, 1), thumb="curl")


def test_fist_drag_lifecycle_and_no_click():
    s = Sim()
    s.step(R(0.4), n=30)
    pre = s.kinds("move")[-1][1].value
    s.step(R(0.4, **FIST), n=4)
    s.step(R(0.4, **FIST), n=6)
    ds = s.kinds("drag_start")
    assert len(ds) == 1 and math.dist(ds[0][1].value, pre) < 2e-3
    for i in range(20):
        s.step(R(0.4 - 0.004 * i, **FIST))
    dm = s.kinds("drag_move")
    assert len(dm) >= 10 and dm[-1][1].value[0] > ds[0][1].value[0] + 0.05
    s.step(R(0.3), n=6)                                # open hand: drop
    assert len(s.kinds("drag_end")) == 1
    assert not s.kinds("click")


def test_fist_must_be_stable_before_drag():
    s = Sim()
    s.step(R(0.4), n=20)
    s.step(R(0.4, **FIST), n=3)           # 0.1 s only
    s.step(R(0.4), n=10)
    assert not s.kinds("drag_start")


def test_hand_loss_grace_keeps_drag_then_releases():
    s = Sim()
    s.step(R(0.4), n=20)
    s.step(R(0.4, **FIST), n=15)
    assert s.kinds("drag_start")
    s.step(None, n=3)                      # 0.1 s gone: still dragging
    assert not s.kinds("drag_end")
    s.step(R(0.4, **FIST), n=3)
    assert not s.kinds("drag_end")
    s.step(None, n=8)                      # > 150 ms: released
    assert len(s.kinds("drag_end")) == 1
    assert not s.e.dragging


def test_left_pinch_right_clicks_at_cursor():
    s = Sim()
    s.step(R(0.4), Lh(), n=30)
    cur = s.kinds("move")[-1][1].value
    s.step(R(0.4), Lh(pinch=1.0), n=5)
    rc = s.kinds("right_click")
    assert len(rc) == 1 and rc[0][1].value == cur
    s.step(R(0.4), Lh(), n=5)
    s.step(R(0.4), Lh(pinch=1.0), n=5)
    assert len(s.kinds("right_click")) == 2


def test_left_two_finger_scroll_direction():
    s = Sim()
    s.step(None, Lh(y=0.6, curl=(0, 0, 1, 1)), n=10)
    for i in range(15):
        s.step(None, Lh(y=0.6 - 0.01 * i, curl=(0, 0, 1, 1)))      # hand moves up
    sc = s.kinds("scroll")
    assert sc and sum(e.value for _, e in sc) > 100
    assert sum(1 for _, e in sc if e.pulse) == 1                    # one pulse per burst
    s2 = Sim()
    s2.step(None, Lh(y=0.4, curl=(0, 0, 1, 1)), n=10)
    for i in range(15):
        s2.step(None, Lh(y=0.4 + 0.01 * i, curl=(0, 0, 1, 1)))
    assert sum(e.value for _, e in s2.kinds("scroll")) < -100


def test_left_open_swipe_changes_space_and_cooldown():
    s = Sim()
    s.step(None, Lh(0.7), n=10)
    for i in range(8):
        s.step(None, Lh(0.7 - 0.045 * i))                          # fast move toward image-left = user's right
    sp = s.kinds("space")
    assert len(sp) == 1 and sp[0][1].value == "left"                # user's right => previous space
    for i in range(8):
        s.step(None, Lh(0.4 + 0.045 * i))
    assert len(s.kinds("space")) == 1                               # 1 s cooldown


def test_slow_left_hand_motion_is_not_a_swipe():
    s = Sim()
    for i in range(90):
        s.step(None, Lh(0.8 - 0.004 * i))
    assert not s.kinds("space")


def test_tiling_left_right_fill_center():
    def tile(rx0, lx0, rx1, lx1):
        s = Sim()
        s.step(R(rx0), Lh(lx0), n=10)
        for i in range(1, 11):
            a = i / 10
            s.step(R(rx0 + (rx1 - rx0) * a), Lh(lx0 + (lx1 - lx0) * a))
        return [e.value for _, e in s.kinds("tile")]
    assert tile(0.4, 0.7, 0.6, 0.9)[:1] == ["left"]      # image-right = user's left
    assert tile(0.5, 0.7, 0.3, 0.5)[:1] == ["right"]
    assert tile(0.4, 0.55, 0.3, 0.8)[:1] == ["fill"]       # hands spread
    assert tile(0.3, 0.8, 0.45, 0.6)[:1] == ["center"]     # hands together
    s = Sim(tiling=False)
    s.step(R(0.4), Lh(0.7), n=5)
    for i in range(10):
        s.step(R(0.4 + 0.015 * i), Lh(0.7 + 0.015 * i))
    assert not s.kinds("tile")


def test_swipe_not_triggered_by_tiling_move():
    s = Sim()
    s.step(R(0.3), Lh(0.6), n=10)
    for i in range(1, 9):
        s.step(R(0.3 + 0.04 * i), Lh(0.6 + 0.04 * i))      # both open hands sweep together
    assert s.kinds("tile") and not s.kinds("space")


def test_dwell_click_default_off_and_rearm():
    s = Sim()
    s.step(R(0.4), n=60)
    assert not s.kinds("click")
    d = Sim(dwell_click=True)
    d.step(R(0.4), n=45)
    assert len(d.kinds("click")) == 1                       # 0.9 s still -> one click
    d.step(R(0.4), n=60)
    assert len(d.kinds("click")) == 1                       # no repeat without moving
    d.step(R(0.25), n=5)                                    # move > 40 px
    d.step(R(0.25), n=45)
    assert len(d.kinds("click")) == 2


def test_pointer_off_and_swap_hands():
    s = Sim(pointer_speed=0)
    s.step(R(0.4), n=20)
    assert not s.kinds("move")
    s = Sim(swap_hands=True)
    s.step(R(0.4), n=20)           # right-geometry hand now acts as the command hand
    assert not s.kinds("move")


def test_release_returns_drag_end_and_caption():
    s = Sim()
    s.step(R(0.4), n=20)
    s.step(R(0.4, **FIST), n=15)
    ev = s.e.release()
    assert [e.kind for e in ev] == ["drag_end"]
    assert caption_for({}) == "no hands"
    assert caption_for({"right": "open"}) == "right · move"
    assert caption_for({"right": "pinch", "left": "scroll"}) == "right · pinch"
    assert caption_for({"left": "scroll"}) == "left · scroll"
    assert caption_for({"right": "open"}, "head · next app") == "head · next app"


def test_tile_rect_matches_v2():
    assert tile_rect("left", (0, 25, 1440, 875), 900) == (0, 0, 720, 875)
    assert tile_rect("right", (0, 25, 1440, 875), 900) == (720, 0, 720, 875)
    assert tile_rect("fill", (0, 25, 1440, 875), 900) == (0, 0, 1440, 875)
    assert tile_rect("center", (0, 0, 1000, 1000), 1000) == (200, 200, 600, 600)



# ---------------------------------------------------------------- v0.4: palm-relative swipe / tiling, dictation
from gestures import PalmSwipe


def _swipe_sim(scale, step, n=8):
    s = Sim()
    s.step(None, make_hand("left", x=0.7, y=0.5, scale=scale), n=10)
    for i in range(n):
        s.step(None, make_hand("left", x=0.7 - step * i, y=0.5, scale=scale))
    return s.kinds("space")


def test_swipe_is_relative_to_palm_width():
    assert not _swipe_sim(1.0, 0.015)                    # 0.105 frame = 1.3 palm widths: too short
    assert len(_swipe_sim(1.0, 0.020)) == 1              # 0.14 = 1.7 palm widths
    assert len(_swipe_sim(0.4, 0.012)) == 1              # far hand: 0.084 frame but 2.6 palm widths
    assert not _swipe_sim(0.4, 0.006)                    # far hand moving 1.3 palm widths


def test_swipe_must_be_mostly_horizontal_and_survives_palm_flicker():
    h = cfg()["hand"]
    sw = PalmSwipe(h)
    t = 0.0
    out = []
    for i in range(8):                                   # diagonal: |dx| < 2|dy|
        out.append(sw.update(True, 0.5 - 0.02 * i, 0.5 + 0.015 * i, 0.08, t))
        t += 1 / 30
    assert not any(out)
    sw = PalmSwipe(h)
    t, out = 0.0, []
    for i in range(10):                                  # 2 dropped frames mid-swipe are tolerated
        out.append(sw.update(i not in (3, 4), 0.7 - 0.02 * i, 0.5, 0.08, t))
        t += 1 / 30
    assert sum(o is not None for o in out) == 1
    sw = PalmSwipe(h)
    t, out = 0.0, []
    for i in range(10):                                  # 3 dropped frames reset the history
        out.append(sw.update(i not in (2, 3, 4), 0.7 - 0.02 * i, 0.5, 0.08, t))
        t += 1 / 30
    assert not any(o is not None for o in out)


def test_swipe_cooldown_is_one_second():
    sw = PalmSwipe(cfg()["hand"])
    fired, t = [], 0.0
    for i in range(60):                                  # continuous fast sweep for 2 s
        r = sw.update(True, 0.9 - 0.02 * i if i < 30 else 0.3 + 0.02 * (i - 30), 0.5, 0.08, t)
        if r is not None:
            fired.append(t)
        t += 1 / 30
    assert len(fired) >= 2 and all(b - a >= 1.0 - 1e-9 for a, b in zip(fired, fired[1:]))


def test_tiling_works_at_distance():
    def tile(scale, k):
        s = Sim()
        r0, l0 = (0.4, 0.55)
        s.step(make_hand("right", x=r0, scale=scale), make_hand("left", x=l0, scale=scale), n=10)
        for i in range(1, 11):
            s.step(make_hand("right", x=r0 - k * i, scale=scale), make_hand("left", x=l0 + k * i, scale=scale))
        return [e.value for _, e in s.kinds("tile")]
    assert tile(1.0, 0.03)[:1] == ["fill"]               # spread 0.6 frame
    assert tile(0.4, 0.012)[:1] == ["fill"]              # far hands: 0.24 frame = 7 palm widths
    assert not tile(1.0, 0.004)                          # tiny spread at close range


def test_left_fist_dictation_once_per_hold_and_rearms():
    s = Sim()
    s.step(R(0.4), Lh(), n=10)
    s.step(R(0.4), Lh(**FIST), n=12)                     # ~0.4 s
    assert not s.kinds("dictation")
    s.step(R(0.4), Lh(**FIST), n=30)                     # well past 0.6 s
    d = s.kinds("dictation")
    assert len(d) == 1 and d[0][1].pulse
    s.step(R(0.4), Lh(**FIST), n=60)                     # continued hold: no repeat
    assert len(s.kinds("dictation")) == 1
    s.step(R(0.4), Lh(), n=10)                           # open hand re-arms
    s.step(R(0.4), Lh(**FIST), n=30)
    assert len(s.kinds("dictation")) == 2
    off = Sim(dictation=False)
    off.step(R(0.4), Lh(), n=10)
    off.step(R(0.4), Lh(**FIST), n=40)
    assert not off.kinds("dictation")
    r = Sim()                                            # the RIGHT fist is a drag, never dictation
    r.step(R(0.4), n=10)
    r.step(R(0.4, **FIST), n=40)
    assert not r.kinds("dictation") and r.kinds("drag_start")


def test_dictation_caption_flash():
    s = Sim()
    s.step(None, Lh(), n=10)
    for _ in range(30):
        s.step(None, Lh(**FIST))
        if s.kinds("dictation"):
            break
    assert s.e.caption(s.t) == "left · dictation"


def test_body_relative_box_same_arm_travel_covers_screen_at_any_distance():
    from roi import FaceGeom

    def span(frac):
        s = Sim()
        for _ in range(40):
            s.e.observe_face(FaceGeom(0.5, 0.35, frac), s.t)
            s.step(R(0.5, y=0.6), n=1)
        xs = []
        for x in (0.5 + 1.0 * 4.5 * frac * 0.5, 0.5 - 1.2 * 4.5 * frac * 0.0 - 4.5 * frac * 0.5):
            for _ in range(25):
                s.e.observe_face(FaceGeom(0.5, 0.35, frac), s.t)
                s.step(R(x, y=0.6), n=1)
            xs.append(s.kinds("move")[-1][1].value[0])
        return abs(xs[0] - xs[1])
    near, far = span(0.15), span(0.05)
    assert near > 0.5 and far > 0.5                 # arm travel scaled by face width gives a similar sweep
    assert abs(near - far) < 0.35


def test_pointer_box_frozen_during_pinch():
    from roi import FaceGeom
    s = Sim()
    s.e.observe_face(FaceGeom(0.5, 0.35, 0.1), 0.0)
    s.step(R(0.4), n=30)
    b0 = s.e.pointer.box
    s.e.observe_face(FaceGeom(0.6, 0.35, 0.05), s.t)          # the person moves while pinching
    s.step(R(0.4, pinch=1.0), n=3)
    s.step(R(0.4, pinch=1.0), n=5)
    assert s.e.pointer.mode == "pinch" and s.e.pointer.box == b0
