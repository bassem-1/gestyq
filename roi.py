"""Adaptive zoom geometry (pure Python): face-relative scale, ROI planning with hysteresis,
growing the crop around a hand that left it, merging hands found in the crop and in the whole frame,
and mapping crop-normalised landmarks back to full-frame normalised coordinates."""
import math
from dataclasses import dataclass, replace

from filters import clamp

CROP_ASPECT = 16 / 9
FULL = (0.0, 0.0, 1.0, 1.0)
CENTER = (0.2, 0.2, 0.6, 0.6)


@dataclass
class FaceGeom:
    cx: float        # face centre x, normalised full frame
    eye_y: float     # approx eye line y
    w: float         # face width / frame width


def face_geom(face):
    """FaceGeom from a head.FaceObs (full-frame coords) or None."""
    w = abs(face.right[0] - face.left[0])
    if w < 1e-4:
        return None
    return FaceGeom((face.left[0] + face.right[0]) / 2,
                    face.top[1] + 0.4 * (face.chin[1] - face.top[1]), w)


def zoom_rect(g, frame_aspect, widths=7.0, min_w=0.2, eye_frac=0.2):
    """Normalised full-frame crop (x, y, w, h): `widths` face widths wide (shoulders and raised arms), 16:9, centred
    on the face horizontally, the eyes `eye_frac` down the crop (head top above, waist at the bottom), clamped to
    the frame. 7 widths x 16:9 = 3.9 widths tall: 0.8 above the eyes, 3.1 below (about 47 cm for a 15 cm face)."""
    w = min(max(widths * g.w, min_w), 1.0, CROP_ASPECT / frame_aspect)
    h = w * frame_aspect / CROP_ASPECT
    return (clamp(g.cx - w / 2, 0.0, 1.0 - w), clamp(g.eye_y - h * eye_frac, 0.0, 1.0 - h), w, h)


def inside(rect, pt):
    return rect[0] <= pt[0] <= rect[0] + rect[2] and rect[1] <= pt[1] <= rect[1] + rect[3]


def contains(rect, other):
    return (rect[0] <= other[0] + 1e-9 and rect[1] <= other[1] + 1e-9
            and other[0] + other[2] <= rect[0] + rect[2] + 1e-9 and other[1] + other[3] <= rect[1] + rect[3] + 1e-9)


def grow(rect, pts, pad, frame_aspect):
    """`rect` enlarged to take in every point with `pad` frame widths of margin (clamped to the frame)."""
    x0, y0, x1, y1 = rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]
    py = pad * frame_aspect
    for px_, py_ in pts:
        x0, x1 = min(x0, px_ - pad), max(x1, px_ + pad)
        y0, y1 = min(y0, py_ - py), max(y1, py_ + py)
    x0, y0, x1, y1 = clamp(x0, 0.0, 1.0), clamp(y0, 0.0, 1.0), clamp(x1, 0.0, 1.0), clamp(y1, 0.0, 1.0)
    return (x0, y0, max(x1 - x0, 0.05), max(y1 - y0, 0.05))


def merge_hands(base, extra, dist=0.06):
    """Hands from the crop (`base`) plus hands the full-frame pass found: an extra hand whose wrist is within `dist`
    (frame widths, either axis scaled alike) of a base wrist is the same hand and dropped. At most two hands."""
    out = list(base)
    for o in extra:
        if len(out) >= 2:
            break
        if all(math.hypot(o.lms[0][0] - b.lms[0][0], o.lms[0][1] - b.lms[0][1]) > dist for b in out):
            out.append(o)
    return out


def rect_to_px(rect, W, H):
    x, y, w, h = rect
    x0, y0 = int(round(x * W)), int(round(y * H))
    return x0, y0, max(2, min(int(round(w * W)), W - x0)), max(2, min(int(round(h * H)), H - y0))


def map_point(p, rect):
    return (rect[0] + p[0] * rect[2], rect[1] + p[1] * rect[3]) + tuple(p[2:])


def map_landmarks(lms, rect):
    """Crop-normalised (x, y, z) -> full-frame normalised. z scales with the crop width."""
    rx, ry, rw, rh = rect
    return [(rx + p[0] * rw, ry + p[1] * rh, p[2] * rw) for p in lms]


def map_face(face, rect):
    if face is None or rect == FULL:
        return face
    out = replace(face, **{k: map_point(getattr(face, k), rect) for k in ("nose", "left", "right", "top", "chin")})
    if face.box is not None:
        x0, y0 = map_point(face.box[:2], rect)
        x1, y1 = map_point(face.box[2:], rect)
        out = replace(out, box=(x0, y0, x1, y1))
    return out


@dataclass
class Plan:
    rect: tuple
    zoom: bool
    face_frac: float     # 0 when no face


class RoiPlanner:
    """Decides which part of the full-resolution frame feeds the detectors."""

    def __init__(self, h, face_ttl=0.7):
        self.h, self.face_ttl = h, face_ttl
        self.reset()

    def reset(self):
        self.face, self.face_t = None, -1e9
        self.zoom = False
        self.roi = None          # held rect (moves only on > shift)
        self.sm = None           # EMA of the target rect
        self.t = None
        self.hand_t = None
        self.alt = 0
        self.mem = []                             # [(t, (x, y))] wrists of recently seen hands (full-frame coords)
        self.grown = None                         # the crop grown around a hand outside it

    def observe_face(self, g, now):
        if g is not None:
            self.face, self.face_t = g, now

    def observe_hands(self, wrists, now):
        """Wrists (full-frame normalised) of the hands found this frame, in the crop or in the whole frame. Each is
        remembered for roi_hand_ttl s (a new sighting within 0.15 of an old one replaces it)."""
        ttl = self.h.get("roi_hand_ttl", 0.8)
        self.mem = [(t, w) for t, w in self.mem if now - t <= ttl
                    and all(math.hypot(w[0] - n[0], w[1] - n[1]) > 0.15 for n in wrists)]
        self.mem += [(now, tuple(w[:2])) for w in wrists]

    def _with_hands(self, rect, now, frame_aspect):
        """While zoomed, a hand found OUTSIDE the crop (by the periodic full-frame pass) grows the crop to take it in,
        and keeps it that way while the hand is seen and for roi_hand_ttl s after, so the hand is tracked from the
        next frame on instead of being re-acquired every few frames. The grown crop is held (like the crop itself)
        until it no longer fits."""
        h = self.h
        ttl = h.get("roi_hand_ttl", 0.8)
        out = [w for t, w in self.mem if now - t <= ttl and not inside(rect, w)]
        if not out:
            self.grown = None
            return rect
        pad = h.get("roi_hand_pad", 0.10)
        g = self.grown
        if g is None or not contains(g, grow(rect, out, pad, frame_aspect)):
            self.grown = grow(rect, out, 1.6 * pad, frame_aspect)        # with slack, so jitter does not re-plan it
        return self.grown

    def plan(self, now, hands_seen, frame_aspect):
        h = self.h
        if self.hand_t is None or hands_seen:
            self.hand_t = now
        hand_recent = now - self.hand_t <= 1.0
        g = self.face if now - self.face_t <= self.face_ttl else None
        frac = g.w if g else 0.0
        if g:
            if not self.zoom and frac < h["far_face_frac"]:
                self.zoom = True
            elif self.zoom and frac > h["near_face_frac"]:
                self.zoom = False
        elif self.zoom and not hand_recent:
            self.zoom = False
        if not self.zoom:
            self.roi = self.sm = self.grown = None
            self.t = now
            if g is None and not hand_recent:        # nobody found: alternate full / centre crop
                self.alt += 1
                return Plan(CENTER if self.alt % 2 else FULL, False, 0.0)
            return Plan(FULL, False, frac)
        if g:
            tgt = zoom_rect(g, frame_aspect, h["roi_face_widths"], eye_frac=h.get("roi_eye_frac", 0.2))
            if self.sm is None:
                self.sm = tgt
            else:
                a = 1 - math.exp(-clamp(now - self.t, 0.0, 0.5) / h["roi_tau"])
                self.sm = tuple(s + a * (t - s) for s, t in zip(self.sm, tgt))
            self.t = now
            r = self.roi
            if r is None:
                self.roi = self.sm
            else:
                s = self.sm
                lim = h["roi_shift"]
                if (abs((s[0] + s[2] / 2) - (r[0] + r[2] / 2)) > lim * r[2]
                        or abs((s[1] + s[3] / 2) - (r[1] + r[3] / 2)) > lim * r[3]
                        or abs(s[2] / r[2] - 1) > lim):
                    self.roi = s
        rect = self.roi or FULL
        if rect != FULL:
            rect = self._with_hands(rect, now, frame_aspect)
        return Plan(rect, True, frac)
