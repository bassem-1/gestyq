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

    def gest(self, gid):
        return [(t, e) for t, e in self.log if e.kind == "gesture" and e.value["id"] == gid]


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


def test_left_open_swipe_changes_space_and_cooldown():
    s = Sim()
    s.step(None, Lh(0.7), n=10)
    for i in range(8):
        s.step(None, Lh(0.7 - 0.045 * i))                          # fast move toward image-left = user's right
    assert len(s.gest("swipe_right")) == 1 and not s.gest("swipe_left")   # user's right
    for i in range(8):
        s.step(None, Lh(0.4 + 0.045 * i))
    assert len(s.gest("swipe_right")) + len(s.gest("swipe_left")) == 1  # 1 s cooldown


def test_slow_left_hand_motion_is_not_a_swipe():
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


def test_scroll_pose_never_swipes_or_tiles():
    s = Sim()
    s.step(R(0.3), Lh(0.6), n=10)                       # both palms open and still
    for i in range(1, 10):                              # left hand goes two-finger and both sweep
        s.step(R(0.3 + 0.04 * i), Lh(0.6 + 0.04 * i, curl=PEACE))
    assert not [1 for _, e in s.log if e.kind == "gesture"]
    s = Sim()                                           # two fingers (read as scroll) -> open -> fast move
    s.step(None, Lh(0.7, curl=PEACE), n=6)
    for i in range(10):
        s.step(None, Lh(0.7 - 0.045 * i))               # within scroll_veto: must not swipe
    assert not s.gest("swipe_left") and not s.gest("swipe_right")


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
    for i in range(8):
        s.step(None, Lh(0.7 - 0.045 * i))
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


def test_swipe_survives_blurred_frames_mid_motion():
    """Real swipes (gestyq.log traces) lose the open label for a few blurred frames mid-motion."""
    s = Sim()
    s.step(None, Lh(0.7), n=10)
    for i in range(10):
        blur = (0.5, 0.5, 0.5, 0.5) if 2 <= i <= 4 else (0, 0, 0, 0)
        s.step(None, Lh(0.7 - 0.02 * i, curl=blur))
    assert len(s.gest("swipe_right")) == 1


def test_short_natural_swipe_fires():
    """Measured swipes cover 0.12-0.2 of the frame in ~0.4 s."""
    s = Sim()
    s.step(None, Lh(0.5), n=10)
    for i in range(12):
        s.step(None, Lh(0.5 + 0.012 * i))       # 0.13 toward image-right = user's left, in 0.4 s
    assert len(s.gest("swipe_left")) == 1 and not s.gest("swipe_right")


# ---- swipes and tiling are measured in palm sizes: the same arm movement works near and far
def swipe_at(scale, travel_palms, direction=-1, frames=12):
    """A left-hand open palm of the given size (distance) sweeping `travel_palms` palm sizes in `frames`."""
    palm = scale * 0.0875                                       # synth hand: palm_scale 0.0875 at scale 1
    s = Sim()
    s.step(None, Lh(0.5, scale=scale), n=10)
    for i in range(frames):
        s.step(None, Lh(0.5 + direction * travel_palms * palm * i / (frames - 1), scale=scale))
    return s


def test_swipe_needs_the_same_palm_travel_near_and_far():
    need = cfg()["hand"]["swipe_dist"]
    for scale in (0.5, 0.8, 1.0, 1.5):                          # far ... near
        fired = swipe_at(scale, need * 1.4)
        assert len(fired.gest("swipe_right")) == 1 and not fired.gest("swipe_left"), scale
        short = swipe_at(scale, need * 0.6)
        assert not short.gest("swipe_right") and not short.gest("swipe_left"), scale


def test_a_far_hand_swipe_is_a_small_frame_distance_and_a_near_one_a_big_one():
    far = swipe_at(0.5, 1.6, +1)          # 1.6 palms of a half-size hand = 0.07 of the frame
    near = swipe_at(1.5, 1.6, +1)         # 0.21 of the frame
    assert len(far.gest("swipe_left")) == 1 and len(near.gest("swipe_left")) == 1
    # the old fixed 0.12-of-frame rule would have missed the far one and fired on a flick of the near one
    flick_near = swipe_at(1.5, 0.7, +1)   # 0.09 of the frame, but only 0.7 palms
    assert not flick_near.gest("swipe_left")


def test_swipe_floor_ignores_jitter_sized_movement_of_a_tiny_hand():
    s = swipe_at(0.15, 3.0)               # a hand so far away that 3 palms are 0.04 of the frame: noise
    assert not s.gest("swipe_right") and not s.gest("swipe_left")


def test_tiling_distance_also_scales_with_the_palm():
    for scale in (0.6, 1.4):
        palm = 0.0875 * scale
        s = Sim()
        s.step(R(0.3, scale=scale), Lh(0.55, scale=scale), n=10)
        for i in range(1, 11):
            d = 2.0 * palm * i / 10                            # both hands 2 palms toward image-right
            s.step(R(0.3 + d, scale=scale), Lh(0.55 + d, scale=scale))
        assert s.gest("palms_left"), scale


def test_trace_lines_are_printed_for_a_swipe_and_a_tile(capsys):
    swipe_at(1.0, 2.0)
    s = Sim()
    s.step(R(0.3), Lh(0.55), n=10)
    for i in range(1, 11):
        s.step(R(0.3 + 0.02 * i), Lh(0.55 + 0.02 * i))
    out = capsys.readouterr().out
    assert "swipe-trace" in out and "tile-trace" in out and "roles-trace" in out


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
