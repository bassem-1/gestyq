"""Adaptive zoom geometry (pure Python): face-relative scale, ROI planning with hysteresis,
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


def zoom_rect(g, frame_aspect, widths=7.0, min_w=0.2):
    """Normalised full-frame crop (x, y, w, h): `widths` face widths wide, 16:9, centred on the
    face horizontally, face (eyes) at the upper third, clamped to the frame."""
    w = min(max(widths * g.w, min_w), 1.0, CROP_ASPECT / frame_aspect)
    h = w * frame_aspect / CROP_ASPECT
    return (clamp(g.cx - w / 2, 0.0, 1.0 - w), clamp(g.eye_y - h / 3, 0.0, 1.0 - h), w, h)


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
    return replace(face, **{k: map_point(getattr(face, k), rect) for k in ("nose", "left", "right", "top", "chin")})


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

    def observe_face(self, g, now):
        if g is not None:
            self.face, self.face_t = g, now

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
            self.roi = self.sm = None
            self.t = now
            if g is None and not hand_recent:        # nobody found: alternate full / centre crop
                self.alt += 1
                return Plan(CENTER if self.alt % 2 else FULL, False, 0.0)
            return Plan(FULL, False, frac)
        if g:
            tgt = zoom_rect(g, frame_aspect, h["roi_face_widths"])
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
        return Plan(self.roi or FULL, True, frac)
