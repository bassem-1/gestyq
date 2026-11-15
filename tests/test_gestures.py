import math

from gestures import GestureEngine, caption_for, tile_rect
from synth import cfg, make_hand, obs, true_label
from tracking import iso, palm_scale


class Sim:
    """Absolute pointer by default (most older tests move the hand to a place and read the cursor there);
    the relative mode has its own tests below (pass pointer_mode="relative")."""

    def __init__(self, **over):
        over.setdefault("pointer_mode", "absolute")
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

    def gest(self, gid):
        return [(t, e) for t, e in self.log if e.kind == "gesture" and e.value["id"] == gid]


def R(x=0.4, y=0.5, **kw):
    return make_hand("right", x=x, y=y, **kw)


def Lh(x=0.7, y=0.5, **kw):
    return make_hand("left", x=x, y=y, **kw)


def palm_of(scale=1.0):
    """The engine's palm size (frame widths, y isotropic at 16:9) of a synth hand."""
    return palm_scale(iso(make_hand("right", scale=scale), 16 / 9))


def flick(s, role, x0, direction, palms=1.8, frames=4, scale=1.0, y0=0.5, pose=None, other=None):
    """A flick of `palms` palm sizes in `frames` frames toward image-right (direction=+1; the user's LEFT) or
    image-left, starting from rest at x0. `other`: (role, hand-factory args) kept still alongside."""
    pose = pose or {}
    mk = (lambda x: make_hand("right", x=x, y=y0, scale=scale, **pose)) if role == "right" else \
         (lambda x: make_hand("left", x=x, y=y0, scale=scale, **pose))
    dx = direction * palms * palm_of(scale) / frames
    for i in range(1, frames + 1):
        h = mk(x0 + dx * i)
        s.step(h if role == "right" else other, h if role == "left" else other)
    return x0 + dx * frames


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
    clicks = s.gest("pinch")
    assert len(clicks) == 1
    cx, cy = clicks[0][1].value["pos"]
    assert clicks[0][1].pulse
    assert math.dist((cx, cy), pre) < 2e-3
    # nothing moved the cursor during the pinch except the one move back to the click position
    assert len(s.kinds("move")) <= n_moves + 1
    assert s.kinds("move")[-1][1].value == (cx, cy)
    # release: cursor follows again, from where the hand is now
    s.step(R(0.52), n=6)
    assert math.dist(s.kinds("move")[-1][1].value, pre) > 0.05
    assert len(s.gest("pinch")) == 1


def test_double_click_within_gap():
    s = Sim()
    s.step(R(0.4), n=30)
    for _ in range(2):
        s.step(R(0.4, pinch=1.0), n=4)
        s.step(R(0.4), n=4)
    assert [len(s.gest("pinch")), len(s.gest("double_pinch"))] == [1, 1]
    s.step(R(0.4), n=30)
    s.step(R(0.4, pinch=1.0), n=4)
    assert len(s.gest("pinch")) == 2 and len(s.gest("double_pinch")) == 1     # too late for a double


def test_single_frame_pinch_blip_is_not_a_click():
    s = Sim()
    s.step(R(0.4), n=30)
    s.step(R(0.4, pinch=1.0))
    s.step(R(0.4), n=10)
    assert not s.gest("pinch")


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
    assert not s.gest("pinch")


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
    rc = s.gest("left_pinch")
    assert len(rc) == 1 and rc[0][1].value["pos"] == cur
    s.step(R(0.4), Lh(), n=5)
    s.step(R(0.4), Lh(pinch=1.0), n=5)
    assert len(s.gest("left_pinch")) == 2


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




def test_slow_left_hand_motion_is_not_a_flick():
    s = Sim()
    for i in range(90):
        s.step(None, Lh(0.8 - 0.004 * i))
    assert not s.gest("swipe_left") and not s.gest("swipe_right")


def test_tiling_left_right_fill_center():
    def tile(rx0, lx0, rx1, lx1):
        s = Sim()
        s.step(R(rx0), Lh(lx0), n=10)
        for i in range(1, 11):
            a = i / 10
            s.step(R(rx0 + (rx1 - rx0) * a), Lh(lx0 + (lx1 - lx0) * a))
        return [e.value["id"] for _, e in s.log if e.kind == "gesture" and e.value["id"].startswith("palms")]
    assert tile(0.4, 0.7, 0.6, 0.9)[:1] == ["palms_left"]      # image-right = user's left
    assert tile(0.5, 0.7, 0.3, 0.5)[:1] == ["palms_right"]
    assert tile(0.4, 0.55, 0.3, 0.8)[:1] == ["palms_apart"]       # hands spread
    assert tile(0.3, 0.8, 0.45, 0.6)[:1] == ["palms_together"]     # hands together
    s = Sim(tiling=False)
    s.step(R(0.4), Lh(0.7), n=5)
    for i in range(10):
        s.step(R(0.4 + 0.015 * i), Lh(0.7 + 0.015 * i))
    assert not [1 for _, e in s.log if e.kind == "gesture"]


def test_swipe_not_triggered_by_tiling_move():
    s = Sim()
    s.step(R(0.3), Lh(0.6), n=10)
    for i in range(1, 9):
        s.step(R(0.3 + 0.04 * i), Lh(0.6 + 0.04 * i))      # both open hands sweep together
    assert s.gest("palms_left") and not s.gest("swipe_left") and not s.gest("swipe_right")


def test_dwell_click_default_off_and_rearm():
    s = Sim()
    s.step(R(0.4), n=60)
    assert not s.gest("dwell")
    d = Sim(dwell_click=True)
    d.step(R(0.4), n=45)
    assert len(d.gest("dwell")) == 1                       # 0.9 s still -> one click
    d.step(R(0.4), n=60)
    assert len(d.gest("dwell")) == 1                       # no repeat without moving
    d.step(R(0.25), n=5)                                    # move > 40 px
    d.step(R(0.25), n=45)
    assert len(d.gest("dwell")) == 2


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


# ---------------------------------------------------------------- regressions: click / scroll robustness
import random

from synth import PEACE, noisy


def bound(**b):
    return {"bindings": {**__import__("bindings").DEFAULT_BINDINGS, **b}}


def test_pinch_with_strongly_curled_index_clicks_and_never_drags():
    for ci in (0.3, 0.45, 0.55):
        s = Sim()
        s.step(R(0.4), n=30)
        s.step(R(0.4, curl=(ci, 0.8, 0.8, 0.8), pinch=1.0), n=40)       # hold a long time
        assert len(s.gest("pinch")) == 1, ci
        assert not s.kinds("drag_start") and not s.kinds("drag_move"), ci


def test_pinch_survives_one_noisy_frame_and_z_noise():
    rng = random.Random(1)
    s = Sim()
    s.step(R(0.4), n=30)
    for k in range(6):                      # six separate pinches, heavy z noise, one bad frame in each
        for i in range(8):
            hand = R(0.4, pinch=1.0) if i != 3 else R(0.4)
            s.step(noisy(hand, rng, xy=0.001, z=0.03))
        s.step(noisy(R(0.4), rng, xy=0.001, z=0.03), n=6)
    assert len(s.gest("pinch")) + len(s.gest("double_pinch")) == 6


def test_fist_with_thumb_over_index_still_drags():
    s = Sim()
    s.step(R(0.4), n=20)
    s.step(R(0.4, **FIST), n=15)
    assert len(s.kinds("drag_start")) == 1 and not s.gest("pinch")


def test_peace_sign_with_loose_fingers_scrolls_and_never_reads_open():
    s = Sim()
    labels = set()
    for i in range(25):
        s.step(None, Lh(y=0.6 - 0.01 * i, curl=PEACE))
        labels.add(s.e.states["left"].label)
    assert "open" not in labels and labels <= {"scroll", "none", "other", "point"}
    assert s.e.states["left"].label == "scroll"
    assert sum(e.value for _, e in s.kinds("scroll")) > 300
    first = s.kinds("scroll")[0][0]
    assert first < 0.2                                  # scroll starts within a few frames




# ---------------------------------------------------------------- bindings
def test_fist_bound_to_discrete_action_fires_once_per_hold():
    s = Sim(**bound(fist="mission_control"))
    s.step(R(0.4), n=20)
    s.step(R(0.4, **FIST), n=30)
    assert len(s.gest("fist")) == 1 and not s.kinds("drag_start")
    assert s.gest("fist")[0][1].pulse
    s.step(R(0.4), n=10)
    s.step(R(0.4, **FIST), n=15)
    assert len(s.gest("fist")) == 2
    assert s.e.caption(s.t) == "right · mission control"


def test_fist_bound_to_none_does_nothing():
    s = Sim(**bound(fist="none"))
    s.step(R(0.4), n=20)
    s.step(R(0.4, **FIST), n=30)
    assert not s.kinds("drag_start") and not s.gest("fist")


def test_two_finger_none_and_inverted():
    s = Sim(**bound(two_finger="none"))
    s.step(None, Lh(y=0.6, curl=PEACE), n=10)
    for i in range(15):
        s.step(None, Lh(y=0.6 - 0.01 * i, curl=PEACE))
    assert not s.kinds("scroll")
    s = Sim(**bound(two_finger="scroll_inverted"))     # the engine still reports hand-up = positive
    s.step(None, Lh(y=0.6, curl=PEACE), n=10)
    for i in range(15):
        s.step(None, Lh(y=0.6 - 0.01 * i, curl=PEACE))
    assert sum(e.value for _, e in s.kinds("scroll")) > 100


def test_pinch_none_and_double_pinch_none():
    s = Sim(**bound(pinch="none"))
    s.step(R(0.4), n=30)
    s.step(R(0.4, pinch=1.0), n=4)
    assert not s.gest("pinch")
    s = Sim(**bound(double_pinch="none"))               # falls back to two single pinches
    s.step(R(0.4), n=30)
    for _ in range(2):
        s.step(R(0.4, pinch=1.0), n=4)
        s.step(R(0.4), n=4)
    assert len(s.gest("pinch")) == 2 and not s.gest("double_pinch")


def test_swipe_and_palms_bound_to_none_emit_nothing_and_flash_uses_label():
    s = Sim(**bound(swipe_left="none", swipe_right="none"))
    s.step(None, Lh(0.7), n=10)
    flick(s, "left", 0.7, -1)
    assert not s.gest("swipe_right") and not s.gest("swipe_left")
    s = Sim(**bound(pinch="right_click"))
    s.step(R(0.4), n=30)
    s.step(R(0.4, pinch=1.0), n=4)
    assert s.e.caption(s.t) == "right · right click"
    s.step(None, Lh(0.7), n=10)


# ---- phantom hands: spawn gate and face veto
def test_three_frame_blip_never_acts():
    s = Sim()
    s.step(right=R(), left=Lh(), n=3)
    s.step(n=10)
    assert s.log == [] and s.e.labels == {}


def test_hand_gets_a_role_after_spawn_frames():
    s = Sim()
    s.step(right=R(), n=4)
    assert s.e.labels == {}
    s.step(right=R(), n=1)
    assert s.e.labels == {"right": "open"}


def test_blip_with_gap_restarts_the_spawn_count():
    s = Sim()
    s.step(right=R(), n=4)
    s.step(n=1)
    s.step(right=R(), n=4)
    assert s.e.labels == {}


FACE = (0.35, 0.15, 0.65, 0.55)      # centre (0.5, 0.35)


def _labels_with_face(scale, face=FACE, conf=0.9):
    e = GestureEngine(cfg(), screen=(1920, 1080))
    for i in range(8):
        e.update([obs(make_hand("right", x=0.5, y=0.5, scale=scale), "Left", conf)], i / 30, face_box=face)
    return e.labels, e.rejected


def test_small_hand_inside_face_box_is_dropped():
    # palm anchor ~ (0.5, 0.41), inside the shrunk box; palm_scale ~0.05 vs face height 0.4/1.78
    labels, rej = _labels_with_face(0.8)
    assert labels == {} and len(rej) == 1


def test_big_hand_in_front_of_face_is_kept():
    labels, rej = _labels_with_face(2.4)
    assert labels == {"right": "open"} and rej == []


def test_low_confidence_hand_inside_face_dropped_even_if_big():
    labels, _ = _labels_with_face(2.4, conf=0.5)
    assert labels == {}


def test_hand_outside_face_box_is_kept_and_no_face_box_changes_nothing():
    e = GestureEngine(cfg(), screen=(1920, 1080))
    for i in range(8):
        e.update([obs(make_hand("right", x=0.2, y=0.7), "Left")], i / 30, face_box=FACE)
    assert e.labels == {"right": "open"}
    labels, rej = _labels_with_face(0.8, face=None)
    assert labels == {"right": "open"} and rej == []


def test_face_box_expires_after_half_a_second():
    e = GestureEngine(cfg(), screen=(1920, 1080))
    e.update([], 0.0, face_box=FACE)
    for i in range(8):
        e.update([obs(make_hand("right", x=0.5, y=0.5, scale=0.8), "Left")], 1.0 + i / 30)
    assert e.labels == {"right": "open"}






# ---- tiling is measured in palm sizes: the same arm movement works near and far
def test_tiling_distance_also_scales_with_the_palm():
    for scale in (0.6, 1.4):
        palm = 0.0875 * scale
        s = Sim()
        s.step(R(0.3, scale=scale), Lh(0.55, scale=scale), n=10)
        for i in range(1, 11):
            d = 2.0 * palm * i / 10                            # both hands 2 palms toward image-right
            s.step(R(0.3 + d, scale=scale), Lh(0.55 + d, scale=scale))
        assert s.gest("palms_left"), scale




# ---- the camera control box follows the desktop
def test_pointer_box_aspect_follows_all_displays():
    def box_for(aspect, span):
        s = Sim()
        s.e.union_aspect, s.e.union_span = aspect, span
        s.step(R(0.4), n=10)
        return s.e.pointer.box
    one, wide, tall = box_for(16 / 9, 1.0), box_for(32 / 9, 2.0), box_for(16 / 18, 1.0)
    fa = 16 / 9
    for box, asp in ((one, 16 / 9), (wide, 32 / 9), (tall, 16 / 18)):
        assert abs(box[2] * fa / box[3] - asp) < 1e-6              # physical aspect == the desktop's
    assert one == (0.15, 0.15, 0.7, 0.7) or all(abs(a - b) < 1e-9 for a, b in zip(one, (0.15, 0.15, 0.7, 0.7)))
    assert wide[2] >= one[2] - 1e-9 and tall[3] <= 0.7 + 1e-9


def test_one_arm_movement_covers_the_whole_wide_desktop():
    s = Sim()
    s.e.union_aspect, s.e.union_span = 32 / 9, 2.0
    s.step(R(0.84), n=15)
    left = s.kinds("move")[-1][1].value
    s2 = Sim()
    s2.e.union_aspect, s2.e.union_span = 32 / 9, 2.0
    s2.step(R(0.16), n=15)
    right = s2.kinds("move")[-1][1].value
    assert left[0] < 0.1 and right[0] > 0.9                        # frame edge to edge = display edge to edge


def test_far_user_gets_the_body_relative_box_and_back_without_flapping():
    from roi import FaceGeom
    s = Sim()
    face = FaceGeom(0.5, 0.35, 0.07)
    s.e.observe_face(face, 0.0, far=False)
    s.step(R(0.4), n=5)
    near_box = s.e.pointer.box
    for _ in range(40):
        s.e.observe_face(face, s.t, far=True)
        s.step(R(0.4))
    far_box = s.e.pointer.box
    assert far_box[2] < near_box[2] * 0.6                          # a small face = a small box (same arm travel)
    assert s.e.cbox.body(s.t)
    s.e.observe_face(None, s.t, far=False)
    assert not s.e.cbox.body(s.t)


# ---------------------------------------------------------------- flicks (either hand, any pose)
POSES = ({}, {"curl": (0, 1, 1, 1)}, {"curl": (0.5, 0.5, 0.5, 0.5)})      # open, point, loose half-closed hand


def test_flick_fires_on_either_hand_in_any_pose_and_names_the_direction():
    for role in ("left", "right"):
        for pose in POSES:
            for direction, gid, other in ((+1, "swipe_left", "swipe_right"), (-1, "swipe_right", "swipe_left")):
                s = Sim()
                s.step(R(0.5, **pose) if role == "right" else None, Lh(0.5, **pose) if role == "left" else None, n=10)
                flick(s, role, 0.5, direction, pose=pose)
                fired = s.gest(gid)
                assert len(fired) == 1 and fired[0][1].value["hand"] == role and fired[0][1].pulse, (role, pose, gid)
                assert not s.gest(other)
                assert s.e.caption(s.t - 1 / 30).endswith("next space" if gid == "swipe_left" else "previous space")


def test_fast_cursor_moves_and_slow_sweeps_are_not_flicks():
    for mode in ("absolute", "relative"):
        for speed in (3, 6, 8):                      # palm sizes / s: brisk cursor moves; flicks start above 10
            s = Sim(pointer_mode=mode)
            s.step(R(0.85), n=10)
            per = speed * palm_of() / 30
            for i in range(45):
                s.step(R(0.85 - per * i))
            assert not s.gest("swipe_left") and not s.gest("swipe_right"), (mode, speed)
            assert s.kinds("move") and s.kinds("move")[-1][1].value[0] > 0.15
    s = Sim()
    s.step(None, Lh(0.9), n=10)
    for i in range(45):
        s.step(None, Lh(0.9 - 8 * palm_of() / 30 * i))
    assert not s.gest("swipe_left") and not s.gest("swipe_right")


def test_flick_needs_travel_a_straight_line_and_no_single_jump():
    s = Sim()
    s.step(None, Lh(0.5), n=10)
    flick(s, "left", 0.5, +1, palms=0.5, frames=2)                        # fast but short
    assert not s.gest("swipe_left")
    s = Sim()
    s.step(None, Lh(0.5), n=10)
    for i in range(1, 5):                                                  # up and a bit sideways: not a sideways flick
        s.step(None, Lh(0.5 + 0.2 * palm_of() * i / 4 * 4, y=0.5 - 0.45 * palm_of() * i * 1.78))
    assert not s.gest("swipe_left") and not s.gest("swipe_right")
    s = Sim()
    s.step(None, Lh(0.5), n=10)
    s.step(None, Lh(0.5 + 2.0 * palm_of()), n=1)                            # one glitchy frame, then it stays
    s.step(None, Lh(0.5 + 2.0 * palm_of()), n=10)
    assert not s.gest("swipe_left") and not s.gest("swipe_right")


def test_return_stroke_does_not_fire_the_other_way():
    s = Sim()
    s.step(None, Lh(0.4), n=10)
    x = flick(s, "left", 0.4, +1)                       # user's left
    s.step(None, Lh(x), n=2)
    flick(s, "left", x, -1)                             # ... and the hand comes back as fast as it went
    s.step(None, Lh(0.4), n=20)
    assert len(s.gest("swipe_left")) == 1 and not s.gest("swipe_right")


def test_rapid_repeated_flicks_each_fire():
    s = Sim()
    s.step(None, Lh(0.3), n=10)
    for k in range(3):                                  # flick, slow return (never a flick), flick again
        x1 = flick(s, "left", 0.3, +1)
        for i in range(1, 16):
            s.step(None, Lh(x1 + (0.3 - x1) * i / 15))
    assert len(s.gest("swipe_left")) == 3 and not s.gest("swipe_right")
    gaps = [b[0] - a[0] for a, b in zip(s.gest("swipe_left"), s.gest("swipe_left")[1:])]
    assert min(gaps) >= s.c["hand"]["flick_gap"]
    s = Sim()                                           # a FAST return is ignored and the next outward flick still fires
    s.step(None, Lh(0.3), n=10)
    x1 = flick(s, "left", 0.3, +1)
    s.step(None, Lh(x1), n=2)
    flick(s, "left", x1, -1)
    s.step(None, Lh(0.3), n=3)
    flick(s, "left", 0.3, +1)
    assert len(s.gest("swipe_left")) == 2 and not s.gest("swipe_right")


def test_flick_on_the_pointer_hand_does_not_throw_the_cursor():
    for mode in ("relative", "absolute"):
        s = Sim(pointer_mode=mode)
        s.step(R(0.5), n=12)
        x = 0.5
        for i in range(12):                             # the cursor is gliding slowly when the flick starts
            x = 0.5 - 0.0015 * i
            s.step(R(x))
        before = s.kinds("move")[-1][1].value
        n0 = len(s.log)
        flick(s, "right", x, +1)
        s.step(R(x + 1.8 * palm_of()), n=4)
        fired = s.gest("swipe_left")
        assert len(fired) == 1
        t_fire = fired[0][0]
        moves = [(t, e.value) for t, e in s.log[n0:] if e.kind == "move"]
        held = [m for t, m in moves if t_fire <= t < t_fire + s.c["hand"]["flick_hold"] - 0.02]
        assert len([1 for t, _ in moves if t == t_fire]) <= 1
        assert held and all(math.dist(m, before) < 0.012 for m in held), mode       # put back (~20 px) and kept
        if mode == "relative":                           # fast motion is discarded: it never leaves in the first place
            assert all(math.dist(m, before) < 0.012 for _, m in moves)


def test_flick_never_during_pinch_drag_or_two_finger_scroll():
    for pose in ({"pinch": 1.0}, {"curl": PEACE}):
        s = Sim()
        s.step(None, Lh(0.5, **pose), n=10)
        flick(s, "left", 0.5, +1, pose=pose)
        assert not s.gest("swipe_left") and not s.gest("swipe_right"), pose
    s = Sim()
    s.step(R(0.5), n=10)
    s.step(R(0.5, **FIST), n=10)                        # a drag is on
    assert s.kinds("drag_start")
    flick(s, "right", 0.5, +1, pose=FIST)
    assert not s.gest("swipe_left")
    s = Sim()
    s.step(R(0.5), n=10)
    s.step(R(0.5, pinch=1.0), n=8)                      # a pinch is on
    flick(s, "right", 0.5, +1, pose={"pinch": 1.0})
    assert not s.gest("swipe_left")


def test_a_flick_beside_a_resting_open_palm_never_tiles_and_both_palms_never_flick():
    s = Sim()
    s.step(R(0.3), Lh(0.6), n=10)
    x = flick(s, "left", 0.6, +1, other=R(0.3))
    s.step(R(0.3), Lh(x), n=20)
    assert len(s.gest("swipe_left")) == 1
    assert not [1 for _, e in s.log if e.kind == "gesture" and e.value["id"].startswith("palms")]
    s = Sim()                                           # tiling off: two hands flicking together fire once
    s.c["tiling"] = False
    s.step(R(0.3), Lh(0.6), n=10)
    for i in range(1, 5):
        s.step(R(0.3 + 0.45 * palm_of() * i), Lh(0.6 + 0.45 * palm_of() * i))
    assert len(s.gest("swipe_left")) == 1


def test_scroll_pose_never_flicks_or_tiles():
    s = Sim()
    s.step(R(0.3), Lh(0.6), n=10)
    for i in range(1, 10):                              # left goes two-finger, both sweep sideways
        s.step(R(0.3 + 0.04 * i), Lh(0.6 + 0.04 * i, curl=PEACE))
    assert not [1 for _, e in s.log if e.kind == "gesture" and (e.value["id"].startswith("palms")
                                                                or e.value.get("hand") == "left")]


def test_flick_trace_names_peak_travel_and_why(capsys):
    s = Sim()
    s.step(None, Lh(0.5), n=10)
    x = flick(s, "left", 0.5, +1)
    s.step(None, Lh(x), n=2)
    flick(s, "left", x, -1)
    out = capsys.readouterr().out
    assert "flick-trace left hand=left peak=" in out and "why=fired swipe_left" in out
    assert "why=return stroke" in out and "palm/s" in out and "travel=" in out


# ---------------------------------------------------------------- relative pointer
def rel_sim(**over):
    s = Sim(pointer_mode="relative", **over)
    s.e.screen, s.e.rects = (2560, 1440), [(0.0, 0.0, 2560.0, 1440.0)]
    return s


def px(s, i=-1):
    n = s.kinds("move")[i][1].value
    return (n[0] * 2559, n[1] * 1439)


def test_relative_gain_is_distance_invariant_and_accelerates():
    def travel(scale, palms, frames, **over):
        s = rel_sim(**over)
        s.e.pointer.hint = (1280.0, 720.0)
        s.step(R(0.7, scale=scale), n=12)
        p0 = px(s)
        d = palms * palm_of(scale) / frames
        for i in range(1, frames + 1):
            s.step(R(0.7 - d * i, scale=scale))               # image-left = the user's right
        s.step(R(0.7 - d * frames, scale=scale), n=20)        # let the smoothing settle
        return px(s)[0] - p0[0]
    near, far = travel(1.0, 1.0, 30), travel(0.4, 1.0, 30)
    assert near > 0 and abs(near / far - 1) < 0.1                    # 1 palm of motion = the same px near and far
    assert 150 < near < 320                                          # slow = precise (about 0.09 screen widths)
    fast = travel(1.0, 1.0, 6)                                       # the same palm in 0.2 s
    assert fast > 1.8 * near
    # pointer_speed levels scale the gain
    lv = [travel(1.0, 1.0, 6, pointer_speed=k) for k in (1, 2, 3, 4)]
    assert lv == sorted(lv) and lv[3] > 2 * lv[0]


def test_relative_brisk_30cm_move_crosses_a_wide_screen():
    s = rel_sim()
    s.e.pointer.hint = (0.0, 720.0)
    s.step(R(0.8), n=12)
    d = 5.0 * palm_of() / 30                                         # 5 palm/s: a brisk, ordinary cursor move
    for i in range(1, 20):                                           # ~3.2 palms: about 30 cm of hand travel
        s.step(R(0.8 - d * i))
    s.step(R(0.8 - d * 19), n=15)
    assert px(s)[0] > 0.8 * 2560 and not s.gest("swipe_left") and not s.gest("swipe_right")


def test_relative_new_track_re_anchors_without_a_jump():
    s = rel_sim()
    s.e.pointer.hint = (1280.0, 720.0)
    s.step(R(0.7), n=12)
    for i in range(12):
        s.step(R(0.7 - 0.006 * i))
    here = px(s)
    assert here[0] > 1280 + 50
    s.step(None, n=30)                                               # the hand leaves the frame ...
    s.e.pointer.hint = here                                          # (the real cursor is where we left it)
    n0 = len(s.log)
    s.step(R(0.2), n=15)                                             # ... and comes back somewhere else
    assert all(math.dist((e.value[0] * 2559, e.value[1] * 1439), here) < 3 for _, e in s.log[n0:] if e.kind == "move")
    for i in range(12):                                              # moving again continues from there
        s.step(R(0.2 + 0.006 * i))
    assert px(s)[0] < here[0] - 50
    s.step(None, n=30)                                               # the user used the trackpad meanwhile
    s.e.pointer.hint = (400.0, 300.0)
    n0 = len(s.log)
    s.step(R(0.5), n=15)
    assert all(math.dist((e.value[0] * 2559, e.value[1] * 1439), (400, 300)) < 3 for _, e in s.log[n0:] if e.kind == "move")
    # a short dropout inside the track (no loss yet) re-anchors too
    s = rel_sim()
    s.step(R(0.7), n=12)
    for i in range(10):
        s.step(R(0.7 - 0.006 * i))
    here = px(s)
    s.step(None, n=4)
    s.step(R(0.5), n=1)
    assert math.dist(px(s), here) < 3


def test_relative_cursor_starts_at_the_real_cursor_and_stays_on_the_displays():
    s = rel_sim()
    s.e.rects = [(0.0, 0.0, 1680.0, 1050.0), (1680.0, -569.0, 1920.0, 1080.0)]        # two displays, offset
    s.e.screen = (3600.0, 1649.0)
    s.e.pointer.hint = (3000.0, -300.0)
    s.step(R(0.8), n=12)
    from desktop import from_norm
    start = from_norm(s.kinds("move")[0][1].value, s.e.rects)
    assert math.dist(start, (3000.0, -300.0)) < 2
    d = 8 * palm_of() / 30
    for direction in (-1, +1, -1):                                   # sweep both ways, far past the ends
        for i in range(40):
            s.step(R(0.5 + direction * 0.3 - direction * d * i * 0.5))
        for _, e in s.log:
            if e.kind == "move":
                pt = from_norm(e.value, s.e.rects)
                assert any(r[0] - 1e-6 <= pt[0] <= r[0] + r[2] + 1e-6 and r[1] - 1e-6 <= pt[1] <= r[1] + r[3] + 1e-6
                           for r in s.e.rects)
    assert max(from_norm(e.value, s.e.rects)[0] for _, e in s.log if e.kind == "move") <= 3599.0 + 1e-6


def test_relative_pinch_freezes_the_cursor_and_clicks_where_it_was():
    s = rel_sim()
    s.step(R(0.6), n=12)
    for i in range(20):
        s.step(R(0.6 - 0.004 * i))
    pre = s.kinds("move")[-1][1].value
    n_moves = len(s.kinds("move"))
    for k in range(1, 12):                                           # the pinch closes while the hand keeps drifting
        s.step(R(0.52 - 0.01 * k, pinch=1.0))
    clicks = s.gest("pinch")
    assert len(clicks) == 1
    cx, cy = clicks[0][1].value["pos"]
    assert math.dist((cx, cy), pre) < 0.03                           # at the position just before the onset
    assert len(s.kinds("move")) <= n_moves + 1 and s.kinds("move")[-1][1].value == (cx, cy)
    s.step(R(0.4), n=8)                                              # released: no jump, continues from the click
    assert math.dist(s.kinds("move")[-1][1].value, (cx, cy)) < 0.01


def test_relative_fist_freezes_then_drags_by_motion():
    s = rel_sim()
    s.step(R(0.6), n=15)
    pre = s.kinds("move")[-1][1].value
    for i in range(7):
        s.step(R(0.6 - 0.003 * i, **FIST))
    ds = s.kinds("drag_start")
    assert len(ds) == 1 and math.dist(ds[0][1].value, pre) < 0.02
    for i in range(20):
        s.step(R(0.58 - 0.006 * i, **FIST))
    dm = s.kinds("drag_move")
    assert len(dm) >= 10 and dm[-1][1].value[0] > ds[0][1].value[0] + 0.03


def test_switching_pointer_mode_at_runtime_releases_a_drag():
    s = rel_sim()
    s.step(R(0.6), n=15)
    s.step(R(0.6, **FIST), n=12)
    assert s.kinds("drag_start") and not s.kinds("drag_end")
    s.c["pointer_mode"] = "absolute"
    s.step(R(0.6, **FIST), n=1)
    assert len(s.kinds("drag_end")) == 1
    assert s.e.pointer.box and s.e.relative is False


# ---------------------------------------------------------------- fist from afar
def test_fist_on_a_small_noisy_hand_is_still_a_fist():
    import random
    from synth import noisy
    from tracking import HandState

    def fist_fraction(**over):
        c = cfg()
        c["hand"].update(over)
        rng, st, hits, total = random.Random(7), HandState(c["hand"]), 0, 0
        for i in range(150):
            # a far hand (palm 0.3 of normal), loosely closed, ~4 px of xy and 12 px of z noise on a 1920 frame
            L = noisy(make_hand("right", scale=0.3, curl=(0.7,) * 4, thumb="curl"), rng, 4 / 1920, 12 / 1920)
            st.update(L, 16 / 9, i / 30)
            if i >= 10:
                total += 1
                hits += st.pose_raw == "fist"
        return hits / total
    new = fist_fraction()
    old = fist_fraction(fist_median=1, fist_relax=0.0)
    assert new > 0.9 and old < 0.7 and new > old + 0.25
    # and a large clean hand is unaffected
    c = cfg()
    st = HandState(c["hand"])
    for i in range(10):
        st.update(make_hand("right", scale=1.0, curl=(1, 1, 1, 1), thumb="curl"), 16 / 9, i / 30)
    assert st.pose_raw == "fist" and st.fist_limit == c["hand"]["fist_reach"]
    # a half-open far hand (fingers loosely bent) is still not a fist
    st = HandState(c["hand"])
    for i in range(20):
        st.update(make_hand("right", scale=0.3, curl=(0.25,) * 4), 16 / 9, i / 30)
    assert st.pose_raw != "fist"


def test_fist_trace_log_line_for_tuning(capsys):
    s = Sim()
    s.step(R(0.5, scale=0.3, **FIST), n=12)
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if l.startswith("fist-trace")]
    assert len(lines) == 1                                           # rate limited
    for key in ("curled=4", "reach i/m/r/p=", "median=", "limit=", "palm=0.0", "pose_raw=fist"):
        assert key in lines[0], key
    s = Sim()
    s.step(R(0.5), n=12)                                             # an open hand logs nothing
    assert "fist-trace" not in capsys.readouterr().out
