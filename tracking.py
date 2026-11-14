"""Hand geometry, finger state, pinch and handedness. Pure Python: no cv2/mediapipe/AppKit.

Landmarks are 21 (x, y, z) tuples in MediaPipe's normalised image space of an UNMIRRORED frame
(x right, y down). `aspect` = frame width / height, used to make x, y, z isotropic.
"""
import math
from collections import deque
from dataclasses import dataclass

from filters import MajorityVote, clamp

PALM_IDS = (0, 5, 9, 13, 17)
FINGERS = {"index": (5, 6, 8), "middle": (9, 10, 12), "ring": (13, 14, 16), "pinky": (17, 18, 20)}
FOUR = ("index", "middle", "ring", "pinky")


@dataclass
class HandObs:
    lms: list            # 21 x (x, y, z)
    label: str = ""      # MediaPipe handedness label, as reported for the unmirrored frame
    conf: float = 0.0


# ------------------------------------------------------------------ geometry
def iso(lms, aspect=1.0):
    """Scale y by 1/aspect so x, y, z share one unit (frame widths)."""
    return [(p[0], p[1] / aspect, p[2]) for p in lms]


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def norm(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def dist3(a, b):
    return norm(sub(a, b))


def angle_at(a, b, c):
    """Interior angle in degrees at b between b->a and b->c (3D). Straight = 180."""
    u, v = sub(a, b), sub(c, b)
    nu, nv = norm(u), norm(v)
    if nu < 1e-9 or nv < 1e-9:
        return 180.0
    cos = (u[0] * v[0] + u[1] * v[1] + u[2] * v[2]) / (nu * nv)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def palm_anchor(lms):
    """Pointer anchor: mean of wrist + the four finger MCPs (raw normalised x, y). Pinching or
    curling the fingers barely moves it, unlike a fingertip."""
    n = len(PALM_IDS)
    return (sum(lms[i][0] for i in PALM_IDS) / n, sum(lms[i][1] for i in PALM_IDS) / n)


def palm_width(L):
    return dist3(L[5], L[17])


def pinch_ratio(L):
    """3D distance thumb tip - index tip, divided by palm width (landmarks 5-17)."""
    w = palm_width(L)
    return dist3(L[4], L[8]) / w if w > 1e-6 else 9.0


def finger_angles(L):
    """PIP interior angle for four fingers + thumb (IP angle, tip-to-index-MCP / palm width)."""
    out = {name: angle_at(L[m], L[p], L[t]) for name, (m, p, t) in FINGERS.items()}
    w = max(palm_width(L), 1e-6)
    out["thumb"] = (angle_at(L[2], L[3], L[4]), dist3(L[4], L[5]) / w)
    return out


def handedness_geometry(lms):
    """Geometric 'is this the user's RIGHT hand' value in [-1, 1] (positive = right).

    Derivation (unmirrored frame, image x right / y down, palm toward the camera, fingers up):
    the camera faces the user, so the user's right hand is at image-left, and with the palm facing
    the camera the thumb/index side is toward image-RIGHT of the pinky. With wrist at the origin,
    index_mcp = (+a, -h) and pinky_mcp = (-b, -h'), so the 2D cross product
        (index_mcp - wrist) x (pinky_mcp - wrist) = a*(-h') - (-h)*(-b) < 0
    for a RIGHT hand and > 0 for a LEFT hand. We return -cross / (|v1||v2|) = -sin(angle) so right
    is positive. Caveat: with the BACK of the hand to the camera the sign flips; the label and
    position votes keep that case mostly right."""
    w, i, p = lms[0], lms[5], lms[17]
    v1 = (i[0] - w[0], i[1] - w[1])
    v2 = (p[0] - w[0], p[1] - w[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    return -(v1[0] * v2[1] - v1[1] * v2[0]) / (n1 * n2)


# ------------------------------------------------------------------ finger state
class FingerStates:
    """ext / curl per finger with hysteresis (Schmitt trigger on the PIP angle)."""

    def __init__(self, h):
        self.ext_deg, self.curl_deg = h["ext_deg"], h["curl_deg"]
        self.state = {}

    def reset(self):
        self.state = {}

    def _angle(self, name, a, prev):
        if prev is None:   # first sight: split the difference
            return "ext" if a > (self.ext_deg + self.curl_deg) / 2 else "curl"
        if prev == "ext":
            return "curl" if a < self.curl_deg else "ext"
        return "ext" if a > self.ext_deg else "curl"

    def update(self, ang):
        st = {}
        for name in FOUR:
            st[name] = self._angle(name, ang[name], self.state.get(name))
        ip, ratio = ang["thumb"]
        prev = self.state.get("thumb")
        if prev is None:
            st["thumb"] = "ext" if (ip > 140 and ratio > 0.65) else "curl"
        elif prev == "ext":
            st["thumb"] = "curl" if (ip < 120 or ratio < 0.5) else "ext"
        else:
            st["thumb"] = "ext" if (ip > 150 and ratio > 0.8) else "curl"
        self.state = st
        return st


def classify_pose(st):
    e = [st[f] == "ext" for f in FOUR]
    if not any(e):
        return "fist"
    if e[0] and e[1] and not e[2] and not e[3]:
        return "scroll"
    if e[0] and not any(e[1:]):
        return "point"
    if sum(e) >= 3:
        return "open"
    return "other"


class PinchDetector:
    """Hysteresis on the pinch ratio; `confirmed` only after >= min_frames consecutive frames."""

    def __init__(self, h):
        self.on, self.off, self.min_frames = h["pinch_on"], h["pinch_off"], h["pinch_frames"]
        self.reset()

    def reset(self):
        self.raw = self.confirmed = self.just_confirmed = False
        self.onset = None
        self.frames = 0

    def update(self, ratio, now, allowed=True):
        was = self.confirmed
        if not self.raw:
            if allowed and ratio < self.on:
                self.raw, self.onset, self.frames = True, now, 1
        elif ratio > self.off:
            self.raw = self.confirmed = False
            self.onset, self.frames = None, 0
        else:
            self.frames += 1
        if self.raw and self.frames >= self.min_frames:
            self.confirmed = True
        self.just_confirmed = self.confirmed and not was


class HandState:
    """Per-role feature pipeline: angles -> finger states -> pose -> 5-frame vote, plus pinch."""

    def __init__(self, h):
        self.h = h
        self.fingers = FingerStates(h)
        self.pinch = PinchDetector(h)
        self.vote = MajorityVote(h["vote_frames"])
        self.reset()

    def reset(self):
        self.fingers.reset()
        self.pinch.reset()
        self.vote.reset()
        self.label, self.label_since = "none", 0.0
        self.pose_raw = "none"
        self.states = {}
        self.ratio = 9.0
        self.anchor = (0.5, 0.5)
        self.fist_raw = False

    def update(self, lms, aspect, now):
        L = iso(lms, aspect)
        self.states = self.fingers.update(finger_angles(L))
        self.pose_raw = classify_pose(self.states)
        self.fist_raw = self.pose_raw == "fist"
        self.ratio = pinch_ratio(L)
        self.pinch.update(self.ratio, now, allowed=not self.fist_raw)
        self.anchor = palm_anchor(lms)
        lab = self.vote.push(self.pose_raw)
        if lab != self.label:
            self.label, self.label_since = lab, now
        return self


# ------------------------------------------------------------------ handedness
def instant_score(obs, hcfg):
    """> 0 means 'user's right hand'. Combines MediaPipe label, geometry and position prior."""
    # MediaPipe assumes a mirrored (selfie) input. Our frame is unmirrored, so its "Left" is the
    # user's right hand.
    label = (1.0 if obs.label == "Left" else -1.0 if obs.label == "Right" else 0.0) * clamp(obs.conf)
    geo = math.tanh(handedness_geometry(obs.lms) / 0.15)
    wx = obs.lms[0][0]
    pos = clamp((0.5 - wx) * 2.0, -1.0, 1.0)     # right hand tends to sit on the image-left half
    return hcfg["label_weight"] * label + hcfg["geometry_weight"] * geo + hcfg["position_weight"] * pos


class _Track:
    _next = 0

    def __init__(self, obs, score, now):
        _Track._next += 1
        self.id = _Track._next
        self.wrist = obs.lms[0][:2]
        self.vote = score
        self.score = score
        self.t = now
        self.seen = now
        self.role = None
        self.flip_since = None


@dataclass
class TrackedHand:
    role: str            # "right" | "left" (after swap_hands)
    vote: float
    score: float
    obs: HandObs
    track_id: int


class HandTracker:
    """Tracks up to two hands by nearest wrist, accumulates an exponential vote per track and
    assigns the roles. A role only flips when the vote is decisively reversed for > flip_time."""

    def __init__(self, hcfg):
        self.c = hcfg
        self.tracks = []

    def reset(self):
        self.tracks = []

    def _match(self, obs_list, now):
        pairs = []
        for oi, o in enumerate(obs_list):
            for ti, t in enumerate(self.tracks):
                pairs.append((math.hypot(o.lms[0][0] - t.wrist[0], o.lms[0][1] - t.wrist[1]), oi, ti))
        pairs.sort()
        used_o, used_t, out = set(), set(), {}
        for d, oi, ti in pairs:
            if d > self.c["track_dist"] or oi in used_o or ti in used_t:
                continue
            used_o.add(oi)
            used_t.add(ti)
            out[oi] = self.tracks[ti]
        return out

    def update(self, obs_list, now, swap=False):
        c = self.c
        obs_list = list(obs_list)[:2]
        self.tracks = [t for t in self.tracks if now - t.seen <= c["track_ttl"]]
        matched = self._match(obs_list, now)
        cur = []
        for oi, o in enumerate(obs_list):
            s = instant_score(o, c)
            t = matched.get(oi)
            if t is None:
                t = _Track(o, s, now)
                self.tracks.append(t)
            else:
                dt = clamp(now - t.t, 0.0, 0.25)
                t.vote += (1.0 - math.exp(-dt / c["vote_tau"])) * (s - t.vote)
            t.score, t.t, t.seen, t.wrist = s, now, now, o.lms[0][:2]
            cur.append((t, o))
        self._assign([t for t, _ in cur], now)
        out = []
        for t, o in cur:
            role = t.role
            if swap:
                role = "left" if role == "right" else "right"
            out.append(TrackedHand(role, t.vote, t.score, o, t.id))
        return out

    def _assign(self, ts, now):
        c = self.c
        margin, ft = c["flip_margin"], c["flip_time"]
        if len(ts) == 1:
            t = ts[0]
            want = "right" if t.vote >= 0 else "left"
            if t.role is None:
                t.role = want
            elif want != t.role and abs(t.vote) > margin:
                if t.flip_since is None:
                    t.flip_since = now
                elif now - t.flip_since >= ft:
                    t.role, t.flip_since = want, None
            else:
                t.flip_since = None
            return
        if len(ts) != 2:
            return
        a, b = sorted(ts, key=lambda t: t.id)       # stable order so the flip timer lives on one track
        diff = a.vote - b.vote
        want_a = "right" if diff >= 0 else "left"
        opp = lambda r: "left" if r == "right" else "right"
        if a.role and b.role and a.role != b.role:           # established and distinct
            if want_a != a.role and abs(diff) > 2 * margin:
                if a.flip_since is None:
                    a.flip_since = now
                elif now - a.flip_since >= ft:
                    a.role, b.role, a.flip_since = opp(a.role), opp(b.role), None
            else:
                a.flip_since = None
            b.flip_since = None
        elif a.role and not b.role:
            b.role = opp(a.role)
        elif b.role and not a.role:
            a.role = opp(b.role)
        else:                                                 # none / same role: force distinct
            a.role, b.role = want_a, opp(want_a)
            a.flip_since = b.flip_since = None
