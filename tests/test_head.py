import math

import config
from head import AxisFusion, FaceObs, HeadTracker, matrix_to_deg, raw_proxies
from synth import cfg

HZ = 15.0


def face(yaw_deg=0.0, pitch_deg=0.0, matrix=False):
    """Synthetic UNMIRRORED face. yaw_deg>0 = user turns to THEIR right (nose moves to image-left)."""
    c = config.DEFAULTS["head"]
    w, h = 0.2, 0.28
    cx, cy = 0.5, 0.5
    nose_x = cx - yaw_deg * c["yaw_per_deg"] * w
    nose_y = cy + 0.02 * h - pitch_deg * c["pitch_per_deg"] * h      # up = smaller y
    m = None
    if matrix:
        y, p = math.radians(-yaw_deg), math.radians(pitch_deg)
        m = [[math.cos(y), 0, math.sin(y), 0], [math.sin(y) * math.sin(p) * 0, math.cos(p), math.sin(p), 0],
             [-math.sin(y), 0, math.cos(y), 0], [0, 0, 0, 1]]
    return FaceObs((nose_x, nose_y), (cx - w / 2, cy), (cx + w / 2, cy), (cx, cy - h / 2), (cx, cy + h / 2), m)


class Rig:
    def __init__(self, level=2, **kw):
        self.c = cfg()
        self.h = HeadTracker(self.c)
        self.t = 0.0
        self.level = level
        self.events = []
        self.kw = kw

    def run(self, seq, dragging=False):
        for yaw, pitch in seq:
            ev = self.h.update(face(yaw, pitch, **self.kw), self.t, self.level, dragging)
            self.events += [(self.t, e.value) for e in ev]
            self.t += 1 / HZ

    def hold(self, secs, yaw=0.0, pitch=0.0):
        self.run([(yaw, pitch)] * int(secs * HZ))

    def ramp(self, secs, y0, y1, p0=0.0, p1=0.0):
        n = max(int(secs * HZ), 1)
        self.run([(y0 + (y1 - y0) * i / n, p0 + (p1 - p0) * i / n) for i in range(1, n + 1)])

    def values(self):
        return [v for _, v in self.events]


def calibrated():
    r = Rig()
    r.hold(1.3)
    assert r.h.calibrated
    return r


def test_signs_deterministic_unmirrored():
    c = config.DEFAULTS["head"]
    yaw_r, _ = raw_proxies(face(20, 0))
    assert yaw_r < 0                           # user's right: nose moves toward image-left
    _, pitch_up = raw_proxies(face(0, 20))
    assert pitch_up < pitch_up * 0 + raw_proxies(face(0, 0))[1]
    h = HeadTracker(cfg())
    my, mp = h.measure(face(20, 15))
    assert my > 0 and mp > 0                   # + right / + up after the sign definition
    my, mp = h.measure(face(-20, -15))
    assert my < 0 and mp < 0


def test_matrix_signs_agree_with_proxy():
    y, p = matrix_to_deg(face(20, 15, matrix=True).matrix)
    assert abs(y - 20) < 0.5 and abs(p - 15) < 0.5


def test_fusion_corrects_flipped_matrix_sign():
    f = AxisFusion()
    out = []
    for i in range(400):
        v = 12 * math.sin(i / 8)
        out.append(f(v, -v))                   # matrix anti-correlated with the proxy
    assert f.sign == -1.0
    assert abs(out[-1] - 12 * math.sin(399 / 8)) < 1.0
    g = AxisFusion()
    for i in range(400):
        v = 12 * math.sin(i / 8)
        g(v, v)
    assert g.sign == 1.0


def test_calibration_one_second_then_no_events_before():
    r = Rig()
    r.hold(0.8)
    assert not r.h.calibrated
    r.run([(30, 0)] * 2)                 # would be a big turn, but still calibrating
    assert not r.events
    r.hold(0.5)
    assert r.h.calibrated


def test_turn_right_and_return_is_next_app():
    r = calibrated()
    r.ramp(0.25, 0, 25); r.hold(0.1, 25); r.ramp(0.25, 25, 0); r.hold(0.5)
    assert r.values() == ["next_app"]


def test_turn_left_and_return_is_prev_app():
    r = calibrated()
    r.ramp(0.25, 0, -25); r.hold(0.1, -25); r.ramp(0.25, -25, 0); r.hold(0.5)
    assert r.values() == ["prev_app"]


def test_cooldown_and_rearm_need_return_to_neutral():
    r = calibrated()
    for _ in range(2):                      # second turn lands inside the 0.8 s cooldown
        r.ramp(0.2, 0, 25); r.ramp(0.2, 25, 0); r.hold(0.3)
    assert r.values() == ["next_app"]
    r.hold(1.0)
    r.ramp(0.2, 0, 25); r.ramp(0.2, 25, 0); r.hold(0.3)
    assert r.values() == ["next_app", "next_app"]


def test_staying_turned_does_not_fire_or_rearm():
    r = calibrated()
    r.ramp(0.25, 0, 25); r.hold(3.0, 25)
    assert not r.events
    r.ramp(0.25, 25, 0); r.hold(0.5)
    assert not r.events                     # took too long (> 0.9 s) -> not a gesture


def test_slow_drift_never_fires():
    r = calibrated()
    r.ramp(30.0, 0, 30, 0, 20)              # posture slowly drifts far past every threshold
    r.ramp(5.0, 30, 0, 20, 0)
    r.hold(2.0)
    assert not r.events


def test_slow_drift_inside_band_is_absorbed_by_baseline():
    r = calibrated()
    b0 = r.h.base[0]
    r.ramp(60.0, 0, 3)                       # tiny posture drift near neutral
    r.hold(60.0, 3)
    assert r.h.base[0] > b0 + 0.5            # baseline followed (slowly)
    assert not r.events


def test_every_level_scales_threshold():
    for level, amp, fire in ((1, 14, False), (1, 22, True), (4, 11, True), (4, 4, False)):
        r = Rig(level=level)
        r.hold(1.3)
        r.ramp(0.2, 0, amp); r.ramp(0.2, amp, 0); r.hold(0.5)
        assert (len(r.events) == 1) == fire, (level, amp, r.events)
    r = Rig(level=0)
    r.hold(1.3); r.ramp(0.2, 0, 30); r.ramp(0.2, 30, 0)
    assert not r.events


def test_ignored_while_dragging():
    r = calibrated()
    r.run([(0, 0)] * 3)
    for y in [i * 5 for i in range(6)] + [25 - i * 5 for i in range(6)]:
        r.run([(y, 0)], dragging=True)
    assert not r.events


def test_head_up_hold_sleeps_once_with_long_cooldown():
    r = calibrated()
    r.ramp(0.3, 0, 0, 0, 22)
    r.hold(0.4, 0, 22)
    assert not r.events                      # not held long enough
    r.hold(0.4, 0, 22)
    assert r.values() == ["sleep"]
    r.hold(1.0, 0, 22)
    r.ramp(0.3, 0, 0, 22, 0); r.hold(0.5)
    r.ramp(0.3, 0, 0, 0, 22); r.hold(1.0, 0, 22)
    assert r.values() == ["sleep"]           # 5 s cooldown still running
    r.ramp(0.3, 0, 0, 22, 0); r.hold(6.0)
    r.ramp(0.3, 0, 0, 0, 22); r.hold(1.0, 0, 22)
    assert r.values() == ["sleep", "sleep"]


def test_quick_nod_up_does_not_sleep_and_slow_tilt_does_not():
    r = calibrated()
    r.ramp(0.2, 0, 0, 0, 22); r.ramp(0.2, 0, 0, 22, 0); r.hold(1)
    assert not r.events
    r.ramp(20.0, 0, 0, 0, 30); r.hold(3.0, 0, 30)
    assert not r.events


def test_matrix_fusion_path_fires_too():
    r = Rig(matrix=True)
    r.hold(1.3)
    r.ramp(0.25, 0, 25); r.ramp(0.25, 25, 0); r.hold(0.5)
    assert r.values() == ["next_app"]


def test_noise_does_not_fire():
    import random
    random.seed(2)
    r = calibrated()
    r.run([(random.gauss(0, 1.2), random.gauss(0, 1.2)) for _ in range(900)])
    assert not r.events


def test_face_loss_then_return_is_safe():
    r = calibrated()
    for i in range(30):
        r.h.update(None, r.t, 2); r.t += 1 / HZ
    r.hold(1.0)
    assert not r.events
