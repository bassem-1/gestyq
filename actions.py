"""Executes events on macOS with Quartz CGEvents (vision thread). macOS only; no AppKit here.

The REAL pointer is moved: CGWarpMouseCursorPosition + a posted MouseMoved/LeftMouseDragged event,
then CGAssociateMouseAndMouseCursorPosition(True). Clicks, drags, scroll and keys are CGEvents.
"""
import subprocess
import threading
import time

import Quartz

from gestures import tile_rect

# virtual key codes
K_TAB, K_LEFT, K_RIGHT, K_DOWN, K_UP, K_F11 = 48, 123, 124, 125, 126, 103
MODS = {"control": Quartz.kCGEventFlagMaskControl, "command": Quartz.kCGEventFlagMaskCommand,
        "option": Quartz.kCGEventFlagMaskAlternate, "shift": Quartz.kCGEventFlagMaskShift}
BUILTIN = {
    "mission_control": "key:126:control",
    "show_desktop": "key:103",
    "launchpad": "shell:open -a Launchpad",
    "notification_center": (
        'script:tell application "System Events" to tell process "ControlCenter" to '
        'click menu bar item 1 of menu bar 1 whose description is "Clock"'),
}


def is_trusted():
    from ApplicationServices import AXIsProcessTrusted
    return bool(AXIsProcessTrusted())


def request_trust():
    """Shows the system prompt and opens the Accessibility pane."""
    from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _osa(script):
    try:
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


class Actions:
    def __init__(self, cfg, state):
        self.cfg, self.state = cfg, state
        self.lock = threading.RLock()
        self.dragging = False
        self.last = None
        self._b, self._bt = None, 0.0

    # -- geometry
    def bounds(self):
        now = time.monotonic()
        if self._b is None or now - self._bt > 2.0:
            r = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
            self._b, self._bt = (r.origin.x, r.origin.y, r.size.width, r.size.height), now
        return self._b

    def to_px(self, nx, ny):
        x, y, w, h = self.bounds()
        return (x + nx * (w - 1), y + ny * (h - 1))

    def location(self):
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return (loc.x, loc.y)

    @staticmethod
    def _post(ev):
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

    # -- pointer
    def move_to(self, pt, dragging=False):
        prev = self.last or pt
        Quartz.CGWarpMouseCursorPosition(pt)
        typ = Quartz.kCGEventLeftMouseDragged if dragging else Quartz.kCGEventMouseMoved
        ev = Quartz.CGEventCreateMouseEvent(None, typ, pt, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventDeltaX, int(round(pt[0] - prev[0])))
        Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventDeltaY, int(round(pt[1] - prev[1])))
        self._post(ev)
        Quartz.CGAssociateMouseAndMouseCursorPosition(True)
        self.last = pt

    def _button(self, pt, down, right=False, count=1):
        if right:
            typ = Quartz.kCGEventRightMouseDown if down else Quartz.kCGEventRightMouseUp
            btn = Quartz.kCGMouseButtonRight
        else:
            typ = Quartz.kCGEventLeftMouseDown if down else Quartz.kCGEventLeftMouseUp
            btn = Quartz.kCGMouseButtonLeft
        ev = Quartz.CGEventCreateMouseEvent(None, typ, pt, btn)
        Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, count)
        self._post(ev)

    def click(self, pt, count=1, right=False):
        pt = pt or self.location()
        self.move_to(pt)
        self._button(pt, True, right, count)
        self._button(pt, False, right, count)

    def release_all(self):
        """Never leave a mouse button down."""
        with self.lock:
            if self.dragging:
                self._button(self.last or self.location(), False)
                self.dragging = False

    # -- keys / scroll
    def key(self, code, flags=0):
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, code, down)
            Quartz.CGEventSetFlags(ev, flags)
            self._post(ev)

    def scroll(self, dy):
        ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitPixel, 1, int(dy))
        self._post(ev)

    def run_action(self, spec):
        spec = BUILTIN.get(spec, spec)
        if spec.startswith("key:"):
            parts = spec.split(":")
            flags = 0
            for m in (parts[2].split(",") if len(parts) > 2 else []):
                flags |= MODS.get(m, 0)
            self.key(int(parts[1]), flags)
        elif spec.startswith("shell:"):
            subprocess.Popen(spec[6:], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif spec.startswith("script:"):
            _osa(spec[7:])

    # -- tiling (osascript, as v2)
    def tile(self, mode):
        scr = self.state.get().get("screen")
        if not scr:
            return
        x, y, w, h = tile_rect(mode, scr["visible"], scr["primary_h"])
        _osa(f'''tell application "System Events"
  set p to first application process whose frontmost is true
  try
    set position of front window of p to {{{x}, {y}}}
    set size of front window of p to {{{w}, {h}}}
    set position of front window of p to {{{x}, {y}}}
  end try
end tell''')

    # -- dispatch
    def execute(self, ev):
        k, v = ev.kind, ev.value
        try:
            with self.lock:
                if k == "move":
                    self.move_to(self.to_px(*v), self.dragging)
                elif k == "drag_move":
                    self.move_to(self.to_px(*v), True)
                elif k == "click":
                    self.click(self.to_px(v[0], v[1]), v[2])
                elif k == "right_click":
                    self.click(self.to_px(*v) if v else None, 1, right=True)
                elif k == "drag_start":
                    pt = self.to_px(*v)
                    self.move_to(pt)
                    self._button(pt, True)
                    self.dragging = True
                elif k == "drag_end":
                    if self.dragging:
                        pt = self.to_px(*v) if v else self.last or self.location()
                        self.move_to(pt, True)
                        self._button(pt, False)
                        self.dragging = False
                elif k == "scroll":
                    self.scroll(v)
                elif k == "space":
                    self.key(K_RIGHT if v == "right" else K_LEFT, MODS["control"])
                elif k == "tile":
                    self.tile(v)
                elif k == "head":
                    if v == "next_app":
                        self.key(K_TAB, MODS["command"])
                    elif v == "prev_app":
                        self.key(K_TAB, MODS["command"] | MODS["shift"])
                    elif v == "sleep":
                        subprocess.Popen(["pmset", "displaysleepnow"], stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
                elif k == "gaze":
                    spec = self.cfg["actions"].get(f"gaze:{v}")
                    if spec:
                        self.run_action(spec)
        except Exception as e:      # never kill the vision thread
            print("action error:", k, v, e)
