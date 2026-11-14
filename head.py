"""Head gestures from our own face geometry (pure Python).

Frame is UNMIRRORED. Raw proxies, as specified:
    yaw_raw   = (nose.x - mid(x234, x454)) / face_width
    pitch_raw = (nose.y - mid(y10,  y152)) / face_height
Sign convention (derived, no invert flags): the camera faces the user, so when the user turns to
THEIR right the nose moves toward image-LEFT -> yaw_raw decreases. When the user tilts the head UP
the nose moves up in the image -> pitch_raw decreases. We therefore define
    yaw   = -yaw_raw   / yaw_per_deg    (degrees-equivalent, + = user's right)
    pitch = -pitch_raw / pitch_per_deg  (degrees-equivalent, + = up)
The facial transformation matrix (if present) gives yaw/pitch in degrees with the same signs after
the conversion in matrix_to_deg; both are fused by averaging, and the matrix sign is verified at
runtime against the proxy (AxisFusion) because matrix conventions are easy to get backwards.
"""
import math
from dataclasses import dataclass
from typing import Optional

from events import Event
from filters import OneEuro


@dataclass
class FaceObs:
    nose: tuple          # landmark 1  (x, y) normalised, unmirrored
    left: tuple          # landmark 234
    right: tuple         # landmark 454
    top: tuple           # landmark 10
    chin: tuple          # landmark 152
    matrix: Optional[list] = None   # 4x4 facial transformation matrix


def raw_proxies(f):
    w = abs(f.right[0] - f.left[0])
    h = abs(f.chin[1] - f.top[1])
    if w < 1e-6 or h < 1e-6:
        return None
    yaw = (f.nose[0] - (f.left[0] + f.right[0]) / 2) / w
    pitch = (f.nose[1] - (f.top[1] + f.chin[1]) / 2) / h
    return yaw, pitch


def matrix_to_deg(m):
    """(yaw_deg, pitch_deg) with + = user's right / up, from a 4x4 matrix whose third column is the
    face forward axis in camera space (x right, y up, +z toward camera)."""
    r02, r12, r22 = float(m[0][2]), float(m[1][2]), float(m[2][2])
    yaw = -math.degrees(math.atan2(r02, r22))
    pitch = math.degrees(math.atan2(r12, math.hypot(r02, r22)))
    return yaw, pitch


class AxisFusion:
    """Averages proxy and matrix angles; flips the matrix sign if it anti-correlates with the proxy."""

    def __init__(self, evidence=60.0, decay=0.995):
        self.evidence, self.decay = evidence, decay
        self.reset()

    def reset(self):
        self.mp = self.mm = None
        self.cov = 0.0

    @property
    def sign(self):
        return -1.0 if self.cov < -self.evidence else 1.0

    def __call__(self, proxy, matrix):
        if matrix is None:
            return proxy
        if self.mp is None:
            self.mp, self.mm = proxy, matrix
        self.mp += 0.02 * (proxy - self.mp)
        self.mm += 0.02 * (matrix - self.mm)
        self.cov = self.cov * self.decay + (proxy - self.mp) * (matrix - self.mm)
        return 0.5 * (proxy + self.sign * matrix)


class _Axis:
    """Excursion detector: leave the neutral band quickly, cross the threshold, come back."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.state = "idle"       # idle | armed | wait
        self.leave_t = None
        self.cross_t = 0.0
        self.sign = 0

    def update(self, d, th, now, c):
        """Returns +1 / -1 when a quick out-and-back excursion completes, else 0."""
        lo = th * c["band"]
        if self.state == "idle":
            if abs(d) <= lo:
                self.leave_t = None
            else:
                if self.leave_t is None:
                    self.leave_t = now
                if abs(d) >= th:
                    if now - self.leave_t <= c["rise_max"]:
                        self.state, self.cross_t = "armed", now
                        self.sign = 1 if d > 0 else -1
                    else:
                        self.state = "wait"      # slow drift: never a gesture
        elif self.state == "armed":
            if abs(d) <= lo:
                self.state, self.leave_t = "idle", None
                return self.sign if now - self.cross_t <= c["return_time"] else 0
            if now - self.cross_t > c["return_time"]:
                self.state = "wait"
        else:
            if abs(d) <= lo:
                self.state, self.leave_t = "idle", None
        return 0


class HeadTracker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.c = cfg["head"]
        self.f_yaw = OneEuro(self.c["min_cutoff"], self.c["beta"], max_gap=0.6)
        self.f_pitch = OneEuro(self.c["min_cutoff"], self.c["beta"], max_gap=0.6)
        self.fuse_yaw, self.fuse_pitch = AxisFusion(), AxisFusion()
        self.yaw_ax = _Axis()
        self.reset()

    def reset(self):
        """Call when head gestures are switched on / the camera restarts: starts the 1 s calibration."""
        self.f_yaw.reset(); self.f_pitch.reset()
        self.yaw_ax.reset()
        self.calib_start = None
        self.calib = []
        self.base = None
        self.yaw = self.pitch = 0.0       # filtered, degrees-equivalent
        self.d_yaw = self.d_pitch = 0.0   # relative to baseline
        self.last_seen = -1e9
        self.last_fire = -1e9
        self.last_sleep = -1e9
        self.up_state, self.up_leave, self.up_since = "idle", None, 0.0
        self.prev = None
        self.last_event = None

    @property
    def calibrated(self):
        return self.base is not None

    def thresholds(self, level):
        s = {1: 1.35, 2: 1.0, 3: 0.75, 4: 0.55}.get(level, 1.0)
        return self.c["yaw_deg"] * s, self.c["pitch_deg"] * s

    def measure(self, face):
        """-> (yaw, pitch) unfiltered, degrees-equivalent (+ right, + up); None if degenerate."""
        p = raw_proxies(face)
        if p is None:
            return None
        yaw = -p[0] / self.c["yaw_per_deg"]
        pitch = -p[1] / self.c["pitch_per_deg"]
        if face.matrix is not None:
            my, mp = matrix_to_deg(face.matrix)
            yaw, pitch = self.fuse_yaw(yaw, my), self.fuse_pitch(pitch, mp)
        return yaw, pitch

    def update(self, face, now, level=2, dragging=False):
        """face: FaceObs or None. Returns a list of Events (kind 'head', value next_app/prev_app/sleep)."""
        c = self.c
        if face is None:
            if now - self.last_seen > c["face_loss_reset"]:
                self.f_yaw.reset(); self.f_pitch.reset()
                self.yaw_ax.reset()
                self.up_state, self.up_leave, self.prev = "idle", None, None
            return []
        m = self.measure(face)
        if m is None:
            return []
        self.last_seen = now
        yaw = self.f_yaw(m[0], now)
        pitch = self.f_pitch(m[1], now)
        self.yaw, self.pitch = yaw, pitch
        if self.base is None:                       # calibration window
            if self.calib_start is None:
                self.calib_start = now
            self.calib.append((yaw, pitch))
            if now - self.calib_start >= c["calib_time"] and len(self.calib) >= 3:
                self.base = [sum(v[0] for v in self.calib) / len(self.calib),
                             sum(v[1] for v in self.calib) / len(self.calib)]
            self.prev = (now, yaw, pitch)
            return []
        yth, pth = self.thresholds(level)
        dy, dp = yaw - self.base[0], pitch - self.base[1]
        self.d_yaw, self.d_pitch = dy, dp
        # very slow baseline EMA, only near neutral and still
        dt = 0.05
        speed = 0.0
        if self.prev:
            dt = max(now - self.prev[0], 1e-3)
            speed = max(abs(yaw - self.prev[1]), abs(pitch - self.prev[2])) / dt
        self.prev = (now, yaw, pitch)
        if abs(dy) < 0.5 * yth and abs(dp) < 0.5 * pth and speed < 8.0:
            k = 1 - math.exp(-min(dt, 0.5) / c["baseline_tau"])
            self.base[0] += dy * k
            self.base[1] += dp * k
        if level <= 0 or dragging:
            self.yaw_ax.reset()
            self.up_state, self.up_leave = "idle", None
            return []
        ev = []
        r = self.yaw_ax.update(dy, yth, now, c)
        if r and now - self.last_fire >= c["cooldown"]:
            self.last_fire = now
            ev.append(self._ev("next_app" if r > 0 else "prev_app"))
        # tilt up quickly past the threshold and HOLD -> display sleep (slow drift never arms)
        lo = pth * c["band"]
        if dp <= lo:
            self.up_state, self.up_leave = "idle", None
        elif self.up_state == "idle":
            if self.up_leave is None:
                self.up_leave = now
            if dp >= pth:
                if now - self.up_leave <= c["rise_max"]:
                    self.up_state, self.up_since = "hold", now
                else:
                    self.up_state = "wait"
        elif self.up_state == "hold":
            if dp < pth * 0.9:
                self.up_state = "wait"
            elif now - self.up_since >= c["sleep_hold"]:
                self.up_state = "done"
                if now - self.last_sleep >= c["sleep_cooldown"]:
                    self.last_sleep = now
                    ev.append(self._ev("sleep"))
        return ev

    def _ev(self, what):
        self.last_event = what
        return Event("head", what, pulse=True)
