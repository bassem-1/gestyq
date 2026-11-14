import math
import random

import config
from synth import cfg, make_hand, obs, true_label
from tracking import (FingerStates, HandState, HandTracker, PinchDetector, angle_at, classify_pose,
                      finger_angles, handedness_geometry, iso, palm_anchor, pinch_ratio)

H = config.DEFAULTS["hand"]
HC = config.DEFAULTS["handedness"]


def test_angle_at_basic():
    assert abs(angle_at((0, 0, 0), (1, 0, 0), (2, 0, 0)) - 180) < 1e-6
    assert abs(angle_at((1, 1, 0), (0, 0, 0), (1, -1, 0)) - 90) < 1e-6
    assert abs(angle_at((1, 0, 0), (0, 0, 0), (0, 0, 1)) - 90) < 1e-6      # uses z


def test_open_and_fist_angles_rotation_invariant():
    for rot in (0, 40, 90, 170):
        for curl, want in ((0, "ext"), (1, "curl")):
            L = make_hand(curl=(curl,) * 4)
            c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
            R = [(0.5 + (x - .3) * c - (y - .5) * s, 0.5 + (x - .3) * s + (y - .5) * c, z) for x, y, z in L]
            st = FingerStates(H).update(finger_angles(iso(R)))
            assert all(st[f] == want for f in ("index", "middle", "ring", "pinky")), (rot, curl, st)


def test_finger_hysteresis_holds_in_between():
    fs = FingerStates(H)
    base = {"index": 175, "middle": 175, "ring": 175, "pinky": 175, "thumb": (170, 1.0)}
    assert fs.update(base)["index"] == "ext"
    mid = dict(base, index=130)
    assert fs.update(mid)["index"] == "ext"           # 110..160 keeps previous
    assert fs.update(dict(base, index=100))["index"] == "curl"
    assert fs.update(mid)["index"] == "curl"          # still curled until > 160
    assert fs.update(dict(base, index=165))["index"] == "ext"


def test_thumb_states_and_poses():
    fs = FingerStates(H)
    assert fs.update(finger_angles(iso(make_hand(thumb="ext"))))["thumb"] == "ext"
    fs = FingerStates(H)
    assert fs.update(finger_angles(iso(make_hand(thumb="curl"))))["thumb"] == "curl"
    P = lambda curl: classify_pose(FingerStates(H).update(finger_angles(iso(make_hand(curl=curl)))))
    assert P((0, 0, 0, 0)) == "open"
    assert P((1, 1, 1, 1)) == "fist"
    assert P((0, 0, 1, 1)) == "scroll"
    assert P((0, 1, 1, 1)) == "point"


def test_pinch_ratio_and_palm_anchor_stable():
    open_ = make_hand()
    pinched = make_hand(pinch=1.0)
    assert pinch_ratio(iso(open_)) > 0.8
    assert pinch_ratio(iso(pinched)) < 0.2
    # pinching / fist barely move the palm-centre anchor, a fingertip would move a lot
    a0, a1, a2 = palm_anchor(open_), palm_anchor(pinched), palm_anchor(make_hand(curl=(1, 1, 1, 1)))
    assert math.dist(a0, a1) < 1e-9 and math.dist(a0, a2) < 1e-9
    assert math.dist(open_[8][:2], make_hand(curl=(1, 1, 1, 1))[8][:2]) > 0.05


def test_pinch_hysteresis_and_persistence():
    p = PinchDetector(H)
    p.update(0.2, 0.0)
    assert p.raw and not p.confirmed and p.onset == 0.0     # one frame is not enough
    p.update(0.35, 0.03)                                    # above on but below off: still raw
    assert p.raw and p.confirmed and p.just_confirmed
    p.update(0.39, 0.06)
    assert p.confirmed and not p.just_confirmed
    p.update(0.45, 0.09)
    assert not p.raw and not p.confirmed
    p.update(0.2, 0.12); p.update(0.6, 0.15)                # single blip never confirms
    assert not p.confirmed


def test_geometry_sign_right_hand_negative_cross():
    r = make_hand("right")
    l = make_hand("left")
    assert handedness_geometry(r) > 0.3
    assert handedness_geometry(l) < -0.3


def feed(tr, frames, t0=0.0, dt=1 / 30):
    out = None
    for i, f in enumerate(frames):
        out = tr.update(f, t0 + i * dt)
    return out


def test_wrong_labels_on_clear_right_hand_still_right():
    random.seed(3)
    tr = HandTracker(HC)
    roles = []
    for i in range(120):
        lab = random.choice(["Left", "Right"]) if i % 2 else "Right"      # 'Right' = wrong for unmirrored
        out = tr.update([obs(make_hand("right", x=0.3), lab, random.uniform(0.6, 0.95))], i / 30)
        roles.append(out[0].role)
    assert set(roles) == {"right"}


def test_wrong_labels_on_clear_left_hand_still_left_even_on_wrong_side():
    tr = HandTracker(HC)
    roles = [tr.update([obs(make_hand("left", x=0.3), "Left", 0.95)], i / 30)[0].role for i in range(60)]
    assert set(roles) == {"left"}          # geometry beats label (+) and position prior (+)


def test_two_hands_never_share_a_role():
    random.seed(5)
    tr = HandTracker(HC)
    for i in range(150):
        # both hands wear the same wrong label; right hand geometry at left, left at right
        lab = "Right"
        out = tr.update([obs(make_hand("left", x=0.7), lab, 0.9), obs(make_hand("right", x=0.3), lab, 0.9)], i / 30)
        assert {h.role for h in out} == {"right", "left"}
    by = {h.role: h.obs.lms[0][0] for h in out}
    assert by["right"] < by["left"]


def test_two_identical_geometry_hands_still_distinct():
    tr = HandTracker(HC)
    for i in range(60):
        out = tr.update([obs(make_hand("right", x=0.3)), obs(make_hand("right", x=0.7))], i / 30)
        assert sorted(h.role for h in out) == ["left", "right"]


def test_new_second_hand_does_not_steal_established_role():
    tr = HandTracker(HC)
    for i in range(60):
        tr.update([obs(make_hand("right", x=0.3))], i / 30)
    # a second hand shows up with a confusing (right-looking) score; the established hand keeps 'right'
    for i in range(60, 100):
        out = tr.update([obs(make_hand("right", x=0.3)), obs(make_hand("right", x=0.7), "Left", 0.9)], i / 30)
        roles = {h.track_id: h.role for h in out}
        assert sorted(roles.values()) == ["left", "right"]
    assert next(h for h in out if h.obs.lms[0][0] < 0.5).role == "right"


def test_role_flips_only_after_sustained_reversal():
    tr = HandTracker(HC)
    t = 0.0
    for _ in range(90):
        out = tr.update([obs(make_hand("right", x=0.5), "Left", 0.9)], t); t += 1 / 30
    assert out[0].role == "right"
    # 0.3 s of reversed evidence: no flip
    for _ in range(9):
        out = tr.update([obs(make_hand("right", x=0.5, back=True), "Right", 0.9)], t); t += 1 / 30
    assert out[0].role == "right"
    # sustained reversal: flips, but not instantly
    flipped_at = None
    for i in range(90):
        out = tr.update([obs(make_hand("right", x=0.5, back=True), "Right", 0.9)], t); t += 1 / 30
        if out[0].role == "left" and flipped_at is None:
            flipped_at = i / 30
    assert flipped_at is not None and flipped_at > 0.3


def test_swap_override_and_tracking_across_frames():
    tr = HandTracker(HC)
    a = tr.update([obs(make_hand("right", x=0.3))], 0.0, swap=True)
    assert a[0].role == "left"
    # a hand drifting slowly keeps its identity
    tr = HandTracker(HC)
    ids = {tr.update([obs(make_hand("right", x=0.3 + 0.002 * i))], i / 30)[0].track_id for i in range(30)}
    assert len(ids) == 1


def test_handstate_vote_smooths_flicker():
    hs = HandState(H)
    labels = []
    for i in range(30):
        curl = (1, 1, 1, 1) if i % 7 == 3 else (0, 0, 0, 0)       # one-frame fist glitch
        hs.update(make_hand(curl=curl), 1.0, i / 30)
        labels.append(hs.label)
    assert set(labels) == {"open"}
