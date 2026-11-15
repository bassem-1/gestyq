"""Air-writing ink (pure Python): stroke geometry and the Writer, the pen + segmentation state machine.

Units are PALM SIZES, x to the user's right, y DOWN. The Writer is stepped once per frame for the pointer hand
(see GestureEngine); it turns the index fingertip into strokes and decides when a letter is finished.
"""
import math
from bisect import bisect_left

from filters import OneEuro2D

DEFAULTS = {"pause": 0.6, "still": 0.5, "still_radius": 0.12, "arm_delay": 0.5, "cursor_hold": 0.15,
            "min_ink": 0.5, "min_size": 0.6, "min_cutoff": 2.0, "beta": 0.02}
OTHER_GRACE = 0.25        # s the pen stays down through "other" (a foreshortened index)
DROP_TAIL = 0.06          # s of samples dropped on pen up (the fingers opening drags the tip)
SAMPLE_DIST = 0.02        # palm sizes between samples
MAX_POINTS = 600
PARK_RADIUS = 0.15
LETTER_TIMEOUT = 6.0
SHORT_STROKE = (0.25, 0.15)      # a stroke shorter than this many palm sizes AND seconds is a slip
PALM_TAU = 0.15
PIN = (0.40, 0.35)        # where a letter's first point sits in the canvas ink area


# ---------------------------------------------------------------- geometry
def path_len(pts):
    return sum(math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))


def bbox(strokes):
    """(x0, y0, x1, y1) of all points, or None."""
    pts = [p for s in strokes for p in s]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def resample(strokes, n=32):
    """n points equally spaced along the ink: strokes are walked in drawing order, no ink between strokes."""
    pts, cum = [], []
    for s in strokes:
        for i, p in enumerate(s):
            cum.append((cum[-1] if cum else 0.0) + (math.dist(pts[-1], p) if pts and i else 0.0))
            pts.append(tuple(p))
    if not pts:
        return []
    total = cum[-1]
    if total <= 1e-9:
        return [pts[0]] * n
    out = []
    for k in range(n):
        target = total * k / (n - 1)
        j = max(1, bisect_left(cum, target))
        j = min(j, len(pts) - 1)
        seg = cum[j] - cum[j - 1]
        if seg <= 1e-12:
            out.append(pts[j])
            continue
        t = min(max((target - cum[j - 1]) / seg, 0.0), 1.0)
        out.append((pts[j - 1][0] + t * (pts[j][0] - pts[j - 1][0]), pts[j - 1][1] + t * (pts[j][1] - pts[j - 1][1])))
    return out


def normalize(pts):
    """Centroid to the origin, uniform scale by the larger side of the bounding box (aspect is kept)."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    s = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
    cx, cy = sum(xs) / len(pts), sum(ys) / len(pts)
    return [((x - cx) / s, (y - cy) / s) for x, y in pts]


def fit(box, first, area_w, area_h, scale0, pad=8.0):
    """Ink placement on the canvas -> (scale, ox, oy): screen = (ox + x * scale, oy + y * scale), in points.
    The first point is pinned at PIN of the area at scale0; nothing moves while the box (plus pad) stays inside.
    Once it would leave, the box is centred and the scale shrinks to fit."""
    scale = float(scale0)
    ox, oy = PIN[0] * area_w - first[0] * scale, PIN[1] * area_h - first[1] * scale
    if box is None:
        return scale, ox, oy
    x0, y0, x1, y1 = box
    if (ox + x0 * scale >= pad and ox + x1 * scale <= area_w - pad
            and oy + y0 * scale >= pad and oy + y1 * scale <= area_h - pad):
        return scale, ox, oy
    bw, bh = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    scale = min(scale, (area_w - 2 * pad) / bw, (area_h - 2 * pad) / bh)
    return scale, area_w / 2 - (x0 + x1) / 2 * scale, area_h / 2 - (y0 + y1) / 2 * scale


# ---------------------------------------------------------------- the pen
class Out:
    """What Writer.step returns for one frame."""
    __slots__ = ("pen", "freeze", "busy", "commit", "tip", "result")

    def __init__(self):
        self.pen = self.freeze = self.busy = False
        self.commit = None       # [[(x, y), ...], ...] a finished letter, ready to recognise
        self.tip = None          # filtered fingertip (palm units) or None without a hand
        self.result = None       # "small" when ink was dropped for being too small


class Writer:
    def __init__(self, cfg=None):
        w = (cfg or {}).get("write", cfg) if cfg else {}
        self.c = {**DEFAULTS, **{k: v for k, v in (w or {}).items() if k in DEFAULTS}}
        self.filt = OneEuro2D(self.c["min_cutoff"], self.c["beta"])
        self.shown_at = None
        self.reset()

    def reset(self):
        self.filt.reset()
        self.was_active = False
        self.palm = None
        self.t_prev = None
        self.raw_prev = None
        self.P = (0.0, 0.0)            # track-local palm-space position
        self.ref_raw, self.ref_P = (0.0, 0.0), (0.0, 0.0)
        self.pos = None
        self.pen = False
        self.last_pen = -1e9
        self.pen_up_t = None
        self.other_t = None
        self.parked = None
        self._clear()

    def _clear(self):
        self.strokes = []
        self.cur = None                # [(t, x, y)] of the stroke in progress
        self.t0 = None                 # first point of the letter
        self.still_p, self.still_t = None, 0.0

    # -- state
    @property
    def busy(self):
        return bool(self.strokes) or bool(self.cur)

    def ink(self):
        """Strokes as tuples of tuples (palm units), the one in progress last."""
        out = [tuple((x, y) for _, x, y in s) for s in self.strokes]
        if self.cur:
            out.append(tuple((x, y) for _, x, y in self.cur))
        return tuple(s for s in out if s)

    def _length(self):
        return sum(path_len([(x, y) for _, x, y in s]) for s in self.strokes + ([self.cur] if self.cur else []))

    def discard(self):
        """Drop pending ink silently (flick left)."""
        self._clear()
        self.parked = self.pos if self.pen else None

    # -- commit
    def _commit(self, now):
        """Finish the letter: -> (strokes or None, "small" or None). Always clears the ink."""
        if self.cur:
            self.strokes.append(self.cur)
            self.cur = None
        strokes = [[(x, y) for _, x, y in s] for s in self.strokes if len(s) > 0]
        self._clear()
        self.parked = self.pos if self.pen else None
        if not strokes:
            return None, None
        length = sum(path_len(s) for s in strokes)
        b = bbox(strokes)
        side = max(b[2] - b[0], b[3] - b[1])
        if length < self.c["min_ink"] or side < self.c["min_size"]:
            return None, ("small" if length >= 0.25 else None)
        return strokes, None

    def commit_now(self, now):
        """Commit the pending letter at once (flick right) -> strokes or None."""
        if not self.busy:
            return None
        if self.pen and self.cur:
            self._end_stroke(now, keep_tail=True)
        return self._commit(now)[0]

    def _end_stroke(self, now, keep_tail=False):
        s = self.cur
        self.cur = None
        if not s:
            return
        if not keep_tail:
            s = [p for p in s if p[0] <= now - DROP_TAIL]
        if not s:
            return
        pts = [(x, y) for _, x, y in s]
        if path_len(pts) < SHORT_STROKE[0] and s[-1][0] - s[0][0] < SHORT_STROKE[1]:
            return
        self.strokes.append(s)

    # -- per frame
    def step(self, hs, lms, aspect, now, active, free=True):
        out = Out()
        c = self.c
        if not active:
            if self.was_active:
                self.reset()
            return out
        if not self.was_active:
            self.was_active = True
            if self.shown_at is None:
                self.shown_at = now
        hand = hs is not None and lms is not None
        armed = self.shown_at is not None and now - self.shown_at >= c["arm_delay"]
        if hand:
            dt = (now - self.t_prev) if self.t_prev is not None else None
            a = 1.0 if dt is None or dt > 1.0 else 1 - math.exp(-dt / PALM_TAU)
            self.palm = hs.palm if self.palm is None else self.palm + a * (hs.palm - self.palm)
            raw = (1.0 - lms[8][0], lms[8][1] / aspect)
            if (self.raw_prev is None or dt is None or dt >= 0.2) or not (self.busy or self.pen):
                self.ref_raw, self.ref_P = raw, self.P       # idle or a new track: re-anchor, nothing moves
            # position = anchor + offset from the anchor in LIVE palm sizes, so a hand that moves closer (palm
            # doubles) mid-letter does not stretch the letter
            self.P = (self.ref_P[0] + (raw[0] - self.ref_raw[0]) / self.palm,
                      self.ref_P[1] + (raw[1] - self.ref_raw[1]) / self.palm)
            self.raw_prev = raw
            fx, fy = self.filt(self.P[0] * 100.0, self.P[1] * 100.0, now)
            self.pos = (fx / 100.0, fy / 100.0)
            out.tip = self.pos
        else:
            self.raw_prev = None
            self.filt.reset()
            self.pos = None
        self.t_prev = now
        # -- pen
        label = hs.label if hand else "none"
        pinching = bool(hand and hs.pinch.raw)
        if label == "point" and not pinching and free and armed:
            want, self.other_t = True, None
        elif self.pen and label == "other" and not pinching and free and armed:
            if self.other_t is None:
                self.other_t = now
            want = now - self.other_t <= OTHER_GRACE
        else:
            want, self.other_t = False, None
        if want and not self.pen:
            self.pen = True
            self.pen_up_t = None
            if self.parked is None:
                self._start_stroke(now)
        elif not want and self.pen:
            self.pen = False
            self.parked = None
            self.pen_up_t = now
            self._end_stroke(now)
            if not self.strokes:
                self._clear()
        if self.pen:
            self.last_pen = now
            self._pen_frame(now, out)
        elif self.busy and self.pen_up_t is not None and now - self.pen_up_t >= c["pause"]:
            out.commit, out.result = self._commit(now)
        out.pen = self.pen
        out.freeze = self.pen
        out.busy = self.busy
        return out

    def _start_stroke(self, now):
        if self.pos is None:
            return
        if not self.strokes:
            self.t0 = now
        self.cur = [(now, *self.pos)]
        self.still_p, self.still_t = self.pos, now

    def _pen_frame(self, now, out):
        c = self.c
        if self.pos is None:
            return
        if self.parked is not None:
            if math.dist(self.pos, self.parked) <= PARK_RADIUS:
                return
            self.parked = None
            self._start_stroke(now)
            return
        if self.cur is None:
            self._start_stroke(now)
            return
        last = self.cur[-1]
        if math.dist(self.pos, last[1:]) >= SAMPLE_DIST and sum(len(s) for s in self.strokes) + len(self.cur) < MAX_POINTS:
            self.cur.append((now, *self.pos))
        if math.dist(self.pos, self.still_p) > c["still_radius"]:
            self.still_p, self.still_t = self.pos, now
        elif now - self.still_t >= c["still"] and self._length() >= 0.05:
            self.cur = [p for p in self.cur if p[0] <= self.still_t]
            out.commit, out.result = self._commit(now)
            return
        if self.t0 is not None and now - self.t0 >= LETTER_TIMEOUT:
            out.commit, out.result = self._commit(now)

    def view(self, armed_now=None):
        """The pieces of the canvas snapshot the Writer knows."""
        return {"strokes": self.ink(), "tip": None if self.pos is None else (round(self.pos[0], 3), round(self.pos[1], 3)),
                "pen": self.pen, "hand": self.pos is not None}

    def armed(self, now):
        return self.shown_at is not None and now - self.shown_at >= self.c["arm_delay"]
