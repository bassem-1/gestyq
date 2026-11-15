"""Text-field focus for air-writing: when the canvas shows and where it goes.

Pure (importable anywhere): classify(), place_canvas(), CanvasGate. The Accessibility-API reader that produces the
Focus values is axreader.FocusReader (macOS only).
"""
from collections import namedtuple

Focus = namedtuple("Focus", "kind frame pid token")      # kind: "text" | "secure" | None; frame: (x, y, w, h) top-left

TEXT_ROLES = ("AXTextField", "AXTextArea", "AXComboBox", "AXSearchField")
CANVAS_SIZE = (320, 200)
CLICK_WINDOW = 1.0         # s a click may precede the focus it caused (browsers lag)
READ_GRACE = 0.4           # s a failed read is tolerated while the canvas is up
TALL = 240                 # fields taller than this get the canvas inside their bottom-right corner


def classify(role, subrole, value_settable, has_text_range, own_process=False):
    """-> "text" | "secure" | None"""
    if own_process:
        return None
    if subrole == "AXSecureTextField":
        return "secure"
    if role in TEXT_ROLES or subrole == "AXSearchField":
        return "text"
    if has_text_range and value_settable:
        return "text"
    return None


def _rect_dist(px, py, r):
    x, y, w, h = r
    dx = max(x - px, 0, px - (x + w))
    dy = max(y - py, 0, py - (y + h))
    return dx * dx + dy * dy


def place_canvas(field, screens, size=CANVAS_SIZE, gap=8):
    """Top-left corner (x, y) for the canvas, all in global top-left coordinates. field and screens: (x, y, w, h)."""
    w, h = size
    fx, fy, fw, fh = field
    cx, cy = fx + fw / 2, fy + fh / 2
    scr = min(screens, key=lambda r: _rect_dist(cx, cy, r)) if screens else (0, 0, 1920, 1080)
    sx, sy, sw, sh = scr
    x, y = fx, None
    if fh <= TALL:
        below = fy + fh + gap
        above = fy - gap - h
        if below + h <= sy + sh:
            y = below
        elif above >= sy:
            y = above
    if y is None:
        x, y = fx + fw - w - 16, fy + fh - h - 16
    x = min(max(x, sx), sx + sw - w)
    y = min(max(y, sy), sy + sh - h)
    return (x, y)


class CanvasGate:
    """Decides when the canvas is visible. step(now, focus, enabled, click) -> visible.

    focus: Focus | None (None = the read failed). click: (t, (x, y)) of the latest left mouse-down (real or
    synthetic) or None. Show: a text field is focused and a click not older than CLICK_WINDOW lies inside it
    (trigger "focus": any change of the focused text element). Stay while the same element is focused; hide when
    focus moves, gestyq or the setting goes off, a secure field is focused, or no ink for idle_hide seconds."""

    def __init__(self, trigger="click", idle_hide=12.0):
        self.trigger, self.idle_hide = trigger, idle_hide
        self.reset()

    def reset(self):
        self.visible = False
        self.token = None
        self.shown_at = None
        self.last_ok = -1e9
        self.last_ink = -1e9
        self.used_click = -1e9          # clicks up to this time are spent (they showed or hid the canvas already)
        self.seen_token = None

    def note_ink(self, now):
        self.last_ink = now

    def _hide(self, now):
        self.visible, self.token = False, None
        self.used_click = max(self.used_click, now)
        return False

    def step(self, now, focus, enabled, click):
        if not enabled:
            self.seen_token = None
            return self._hide(now) if self.visible else False
        if focus is None:
            if self.visible and now - self.last_ok > READ_GRACE:
                return self._hide(now)
            return self.visible
        self.last_ok = now
        if focus.kind != "text":
            self.seen_token = None
            return self._hide(now) if self.visible else False
        if self.visible:
            if focus.token != self.token:
                self.visible, self.token = False, None
            elif self.idle_hide > 0 and now - max(self.shown_at, self.last_ink) > self.idle_hide:
                return self._hide(now)
            else:
                return True
        # not visible: show?
        show = False
        if self.trigger == "focus":
            show = focus.token != self.seen_token
        elif click is not None:
            t, (x, y) = click
            fx, fy, fw, fh = focus.frame
            inside = fx - 4 <= x <= fx + fw + 4 and fy - 4 <= y <= fy + fh + 4
            show = inside and 0 <= now - t <= CLICK_WINDOW and t > self.used_click
        self.seen_token = focus.token
        if show:
            self.visible, self.token, self.shown_at = True, focus.token, now
            self.last_ink = -1e9
            if click is not None:
                self.used_click = max(self.used_click, click[0])
        return self.visible
