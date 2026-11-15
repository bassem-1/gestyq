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


def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def palm_scale(L):
    """Hand size in frame widths: mean of palm width (5-17) and palm length (0-9), both in the image
    plane. Two measures so turning the hand sideways OR pointing it at the camera shrinks only one."""
    return 0.5 * (dist2(L[5], L[17]) + dist2(L[0], L[9]))


def pinch_ratio(L):
    """Thumb tip - index tip distance in the IMAGE PLANE (x, y only) over palm_scale. MediaPipe's z is
    noisy and scaled differently from x/y; including it inflated the ratio and hid real pinches."""
    s = palm_scale(L)
    return dist2(L[4], L[8]) / s if s > 1e-6 else 9.0


Z_WEIGHT = 0.5      # z counts half in reach distances (noisy)


def _dz(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (Z_WEIGHT * (a[2] - b[2])) ** 2)


def finger_reach(L):
    """Per finger: wrist-to-tip distance over wrist-to-MCP distance. ~1.8-1.9 straight, ~1.4 half curled,
    ~0.8-1.0 curled into the palm. Unlike a joint angle it survives foreshortening (finger pointing
    at the camera), because tip and MCP shrink together."""
    out = {}
    for name, (m, p, t) in FINGERS.items():
        d = _dz(L[m], L[0])
        out[name] = _dz(L[t], L[0]) / d if d > 1e-6 else 1.0
    return out


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
    """ext / curl per finger with hysteresis. Two independent cues are combined:
      angle  - PIP interior angle (180 straight)
      reach  - wrist-to-tip over wrist-to-MCP (see finger_reach), robust to foreshortening
    extended evidence: angle > ext_deg, or (angle > soft_deg and reach > reach_ext)
    curled evidence:   angle < curl_deg, or reach < reach_curl
    A finger switches only on evidence for the other state; first sight needs extended evidence to
    read 'ext', so a loose, half-curled finger reads curled (a peace sign stays a peace sign)."""

    def __init__(self, h):
        self.ext_deg, self.curl_deg = h["ext_deg"], h["curl_deg"]
        self.soft_deg = h.get("soft_deg", 135.0)
        self.reach_ext, self.reach_curl = h.get("reach_ext", 1.6), h.get("reach_curl", 1.3)
        self.state = {}
        self.reach = {}

    def reset(self):
        self.state = {}
        self.reach = {}

    def _finger(self, a, r, prev):
        if r is None:                       # angle-only (no landmarks available)
            ext_ev, curl_ev = a > self.ext_deg, a < self.curl_deg
            if prev is None:
                return "ext" if a > (self.ext_deg + self.curl_deg) / 2 else "curl"
        else:
            ext_ev = a > self.ext_deg or (a > self.soft_deg and r > self.reach_ext)
            curl_ev = a < self.curl_deg or r < self.reach_curl
            if prev is None:
                return "ext" if ext_ev and not curl_ev else "curl"
        if prev == "ext":
            return "curl" if curl_ev else "ext"
        return "ext" if ext_ev else "curl"

    def update(self, ang, reach=None):
        st = {}
        self.reach = dict(reach or {})
        for name in FOUR:
            st[name] = self._finger(ang[name], (reach or {}).get(name), self.state.get(name))
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


def median(vals):
    v = sorted(vals)
    n = len(v)
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


def fist_limit(h, palm):
    """fist_reach, relaxed for small hands. A far hand's landmarks are a few pixels off, which inflates every
    tip-to-wrist distance (noise only adds length), so the limit grows by up to fist_relax as palm_scale falls
    from fist_palm_ref to 0."""
    ref = max(h.get("fist_palm_ref", 0.06), 1e-6)
    return h.get("fist_reach", 1.25) + h.get("fist_relax", 0.25) * clamp(1.0 - palm / ref, 0.0, 1.0)


def classify_pose(st, reach=None, fist_reach=1.25):
    """open (all four fingers extended) | scroll (index+middle up, ring+pinky folded) | point |
    fist | other. `reach` (finger_reach) makes 'fist' strict: every fingertip must be close to the
    palm. A pinch bends the index to meet the thumb and is NOT a fist. Ambiguous poses -> 'other',
    which does nothing, rather than 'open' (which can swipe / tile)."""
    e = [st[f] == "ext" for f in FOUR]
    if not any(e):
        if reach is None or all(reach[f] < fist_reach for f in FOUR):
            return "fist"
        return "other"
    if e[0] and e[1] and not e[2] and not e[3]:
        return "scroll"
    if e[0] and not any(e[1:]):
        return "point"
    if all(e):
        return "open"
    return "other"


class PinchDetector:
    """Hysteresis on the pinch ratio (on below pinch_on, off above pinch_off); `confirmed` after
    pinch_frames good frames. A pinch survives up to pinch_miss consecutive bad frames (landmark
    noise) before it is dropped, so one jittery frame neither cancels a click nor splits it in two."""

    def __init__(self, h):
        self.on, self.off, self.min_frames = h["pinch_on"], h["pinch_off"], h["pinch_frames"]
        self.max_miss = h.get("pinch_miss", 1)
        self.reset()

    def reset(self):
        self.raw = self.confirmed = self.just_confirmed = False
        self.onset = None
        self.frames = 0
        self.miss = 0

    def update(self, ratio, now, allowed=True):
        was = self.confirmed
        if not self.raw:
            if allowed and ratio < self.on:
                self.raw, self.onset, self.frames, self.miss = True, now, 1, 0
        elif ratio > self.off:
            self.miss += 1
            if self.miss > self.max_miss:
                self.raw = self.confirmed = False
                self.onset, self.frames, self.miss = None, 0, 0
        else:
            self.miss = 0
            self.frames += 1
        if self.raw and self.frames >= self.min_frames:
            self.confirmed = True
        self.just_confirmed = self.confirmed and not was


class HandState:
    """Per-role feature pipeline: angles + reach -> finger states -> pose -> vote, plus pinch.
    Also keeps `open_frames` (consecutive raw 'open' frames) and `scroll_seen` (last time the raw pose
    was two-finger) so swipe / tiling can demand a confident open palm."""

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
        self.reach = {}
        self.ratio = 9.0
        self.anchor = (0.5, 0.5)
        self.palm = 0.1               # palm_scale in frame widths (distance reference for swipe / tiling)
        self.fist_raw = False
        self.reach_hist = deque(maxlen=max(1, int(self.h.get("fist_median", 5))))
        self.reach_med = {}
        self.reach_fist = {}
        self.fist_limit = self.h.get("fist_reach", 1.25)
        self.open_frames = 0
        self.scroll_seen = -1e9

    def confident_open(self, now):
        """All four fingers extended for open_frames in a row, and no two-finger pose lately."""
        return (self.label == "open" and self.open_frames >= self.h.get("open_frames", 4)
                and now - self.scroll_seen > self.h.get("scroll_veto", 0.6))

    def update(self, lms, aspect, now):
        L = iso(lms, aspect)
        self.reach = finger_reach(L)
        self.palm = max(palm_scale(L), 1e-3)
        self.reach_hist.append(self.reach)
        self.reach_med = {f: median([r[f] for r in self.reach_hist]) for f in FOUR}
        # fist test: the lower of this frame's and the median reach. A closing hand is a fist at once (no extra
        # latency, so a pinch cannot slip in first); a noise spike on one finger is outvoted by the median.
        self.reach_fist = {f: min(self.reach[f], self.reach_med[f]) for f in FOUR}
        self.fist_limit = fist_limit(self.h, self.palm)
        self.states = self.fingers.update(finger_angles(L), self.reach)
        self.pose_raw = classify_pose(self.states, self.reach_fist, self.fist_limit)
        self.ratio = pinch_ratio(L)
        if (self.pose_raw == "fist" and (self.ratio < self.pinch.on or self.pinch.raw)
                and self.reach_fist["index"] > self.h.get("fist_pinch_reach", 1.05)
                + (self.fist_limit - self.h.get("fist_reach", 1.25))):
            self.pose_raw = "other"        # thumb on a bent index that is still held out: a pinch, not a fist
        self.fist_raw = self.pose_raw == "fist"
        self.pinch.update(self.ratio, now, allowed=not self.fist_raw)
        self.anchor = palm_anchor(lms)
        self.open_frames = self.open_frames + 1 if self.pose_raw == "open" else 0
        if self.pose_raw == "scroll":
            self.scroll_seen = now
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
        self.frames = 1          # consecutive frames seen (spawn gate)
        self.live = False        # seen >= spawn_frames in a row: may get a role and act


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

    def __init__(self, hcfg, spawn_frames=1):
        self.c = hcfg
        self.spawn_frames = max(1, int(spawn_frames))
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
        keep = set(map(id, matched.values()))        # a new track missing one frame was a blip: forget it
        self.tracks = [t for t in self.tracks if t.live or id(t) in keep]
        cur = []
        for oi, o in enumerate(obs_list):
            s = instant_score(o, c)
            t = matched.get(oi)
            if t is None:
                t = _Track(o, s, now)
                t.live = self.spawn_frames <= 1
                self.tracks.append(t)
            else:
                t.frames += 1
                if t.frames >= self.spawn_frames:
                    t.live = True
                dt = clamp(now - t.t, 0.0, 0.25)
                t.vote += (1.0 - math.exp(-dt / c["vote_tau"])) * (s - t.vote)
            t.score, t.t, t.seen, t.wrist = s, now, now, o.lms[0][:2]
            cur.append((t, o))
        cur = [(t, o) for t, o in cur if t.live]
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
