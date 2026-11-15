"""Desktop model (pure Python): display rects in global CG coordinates (origin top-left of the
primary display, y down), the union box, dead-area clamping, the aspect-adapted pointer control
box (fixed-margin or body-relative) and Cocoa <-> top-left helpers."""
import math
import threading

from filters import clamp

CROP_FREE = (0.0, 0.0, 1.0, 1.0)


# ------------------------------------------------------------------ displays
def union(rects):
    """Bounding box (x, y, w, h) of display rects."""
    if not rects:
        return (0.0, 0.0, 1920.0, 1080.0)
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return (x0, y0, x1 - x0, y1 - y0)


def _clamp_in(pt, r):
    return (min(max(pt[0], r[0]), r[0] + max(r[2] - 1, 0)), min(max(pt[1], r[1]), r[1] + max(r[3] - 1, 0)))


def span_of(rects):
    if not rects:
        return 1.0
    ref = next((r for r in rects if r[0] == 0 and r[1] == 0), rects[0])
    return max(union(rects)[2] / max(ref[2], 1.0), 0.1)


def clamp_to_displays(pt, rects):
    """pt unchanged if inside a display, else the nearest point inside any display (L-shaped
    layouts leave dead areas inside the union box)."""
    if not rects:
        return pt
    best, bd = pt, math.inf
    for r in rects:
        q = _clamp_in(pt, r)
        d = math.hypot(q[0] - pt[0], q[1] - pt[1])
        if d == 0:
            return pt
        if d < bd:
            best, bd = q, d
    return best


def to_point(nx, ny, rects):
    """Normalised control-box coords -> union bounding box -> clamped into a display."""
    x, y, w, h = union(rects)
    return clamp_to_displays((x + clamp(nx) * (w - 1), y + clamp(ny) * (h - 1)), rects)


class Desktop:
    """Thread-safe display list shared by the vision thread, the UI thread and CG callbacks."""

    def __init__(self, rects=None):
        self.lock = threading.Lock()
        self._rects = [tuple(r) for r in (rects or [(0.0, 0.0, 1920.0, 1080.0)])]

    def set(self, rects):
        """-> True when the layout changed."""
        rects = [tuple(float(v) for v in r) for r in rects if r[2] > 0 and r[3] > 0]
        if not rects:
            return False
        with self.lock:
            if rects == self._rects:
                return False
            self._rects = rects
            return True

    def rects(self):
        with self.lock:
            return list(self._rects)

    def count(self):
        with self.lock:
            return len(self._rects)

    def bounds(self):
        return union(self.rects())

    def aspect(self):
        b = self.bounds()
        return b[2] / max(b[3], 1.0)

    def span(self):
        """Union width / width of the reference (primary) display: 1 for one display, 2 for two
        equal displays side by side."""
        return span_of(self.rects())

    def to_px(self, nx, ny):
        return to_point(nx, ny, self.rects())


# ------------------------------------------------------------------ Cocoa coordinates
def cocoa_to_topleft(rect, primary_h):
    """Cocoa global rect (bottom-left origin, relative to the PRIMARY screen's height) -> top-left
    origin rect as used by CG / System Events. Correct for displays above/below/left/right."""
    x, y, w, h = rect
    return (x, primary_h - (y + h), w, h)


def parse_rect(s):
    """'x,y,w,h' (as printed by osascript) -> tuple or None."""
    try:
        v = tuple(float(p) for p in str(s).strip().replace(" ", "").split(","))
    except ValueError:
        return None
    return v if len(v) == 4 else None


def _overlap(a, b):
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def pick_visible(window, screens, primary_h, main=0):
    """Cocoa visible frame of the screen holding `window` (top-left (x, y, w, h), centre first, then
    largest overlap); falls back to the main screen. screens: [{"frame", "visible"}, ...] in Cocoa."""
    if not screens:
        return None
    main = main if 0 <= main < len(screens) else 0
    if window:
        frames = [cocoa_to_topleft(s["frame"], primary_h) for s in screens]
        cx, cy = window[0] + window[2] / 2, window[1] + window[3] / 2
        for s, f in zip(screens, frames):
            if f[0] <= cx < f[0] + f[2] and f[1] <= cy < f[1] + f[3]:
                return s["visible"]
        ov = [_overlap(window, f) for f in frames]
        if max(ov) > 0:
            return screens[ov.index(max(ov))]["visible"]
    return screens[main]["visible"]


# ------------------------------------------------------------------ control box
def control_box(cx, cy, w, aspect, frame_aspect, usable=CROP_FREE, span=1.0):
    """Camera-frame box (normalised x0, y0, w, h) whose PHYSICAL aspect equals the desktop aspect
    (width/height). `w` is the width for ONE reference display; the box grows with the desktop
    (width x span, height from the aspect), so hand travel per screen-cm stays constant in both axes
    (two side by side: twice as wide; two stacked: twice as tall). Capped to `usable` (uniformly)
    and shifted to fit in it. frame_aspect = frame width / frame height."""
    ux, uy, uw, uh = usable
    aspect = max(aspect, 0.1)
    w = w * span
    h = w * frame_aspect / aspect
    s = min(1.0, uw / w, uh / h)
    w, h = w * s, h * s
    return (clamp(cx - w / 2, ux, ux + uw - w), clamp(cy - h / 2, uy, uy + uh - h), w, h)


def margin_box(h, aspect, frame_aspect, span=1.0):
    """The no-face box: centred, width 1 - 2*margin_x, height capped to 1 - 2*margin_y."""
    mx, my = h["frame_margin_x"], h["frame_margin_y"]
    return control_box(0.5, 0.5, 1 - 2 * mx, aspect, frame_aspect, (mx, my, 1 - 2 * mx, 1 - 2 * my), span)


def body_box(g, h, aspect, frame_aspect, side=1, span=1.0):
    """Body-relative box from a FaceGeom: width box_face_widths x face width, centred toward the
    pointer hand's shoulder (side=+1: the user's right = image-left) and below the eyes."""
    fw = g.w
    cx = g.cx - side * h["box_offset_x"] * fw
    cy = g.eye_y + h["box_offset_y"] * fw * frame_aspect
    return control_box(cx, cy, h["box_face_widths"] * fw, aspect, frame_aspect, CROP_FREE, span)


class ControlBox:
    """EMA-smoothed pointer control box. Body-relative only while the camera is zoomed (the user is
    far) and a face was seen in the last `face_ttl` s, else the fixed-margin box. Frozen while a
    pinch/drag is active."""

    def __init__(self, h, face_ttl=1.0):
        self.h, self.face_ttl = h, face_ttl
        self.reset()

    def reset(self):
        self.face, self.face_t = None, -1e9
        self.far = False
        self.box = None
        self.t = None

    def set_far(self, far):
        self.far = bool(far)

    def observe_face(self, g, now):
        if g is not None:
            self.face, self.face_t = g, now

    def body(self, now):
        return self.far and self.face is not None and now - self.face_t <= self.face_ttl

    def update(self, now, frozen, aspect, frame_aspect, side=1, span=1.0):
        if self.body(now):
            tgt = body_box(self.face, self.h, aspect, frame_aspect, side, span)
        else:
            tgt = margin_box(self.h, aspect, frame_aspect, span)
        if self.box is None:
            self.box = tgt
        elif not frozen:
            a = 1 - math.exp(-clamp(now - self.t, 0.0, 0.5) / self.h["box_tau"])
            self.box = tuple(b + a * (t - b) for b, t in zip(self.box, tgt))
        self.t = now
        return self.box
