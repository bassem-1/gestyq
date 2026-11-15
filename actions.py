"""Executes events on macOS with Quartz CGEvents (vision thread). macOS only; no AppKit here.

The REAL pointer is moved: CGWarpMouseCursorPosition + a posted MouseMoved/LeftMouseDragged event,
then CGAssociateMouseAndMouseCursorPosition(True). Clicks, drags, scroll and keys are CGEvents.
"""
import subprocess
import threading
import time

import Quartz

from desktop import Desktop, parse_rect, pick_visible
from gestures import tile_rect
from keys import chord_plan, dictation_script, front_window_script, osa_chord_script

# virtual key codes
K_TAB, K_LEFT, K_RIGHT, K_DOWN, K_UP, K_F11 = 48, 123, 124, 125, 126, 103
CHORD_GAP = 0.012
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


def _osa_out(script, timeout=3.0):
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def query_displays():
    """Active displays as global CG rects [(x, y, w, h)]."""
    err, ids, n = Quartz.CGGetActiveDisplayList(16, None, None)
    rects = []
    for d in list(ids or [])[:n]:
        r = Quartz.CGDisplayBounds(d)
        rects.append((r.origin.x, r.origin.y, r.size.width, r.size.height))
    if not rects:
        r = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        rects = [(r.origin.x, r.origin.y, r.size.width, r.size.height)]
    return rects


class Actions:
    def __init__(self, cfg, state):
        self.cfg, self.state = cfg, state
        self.lock = threading.RLock()
        self.dragging = False
        self.last = None
        self.desktop = Desktop(query_displays())
        self._poll_t = 0.0

    # -- geometry (multi-display)
    def refresh_displays(self):
        """Any thread. -> True when the layout changed."""
        try:
            return self.desktop.set(query_displays())
        except Exception as e:
            print("display query failed:", e)
            return False

    def watch_displays(self):
        """Main thread: CG reconfiguration callback (the 2 s poll in bounds() is the fallback)."""
        def cb(display, flags, info):
            if not flags & Quartz.kCGDisplayBeginConfigurationFlag:
                self.refresh_displays()
        self._cb = cb                                   # keep alive
        try:
            Quartz.CGDisplayRegisterReconfigurationCallback(cb, None)
        except Exception as e:
            print("display callback unavailable:", e)

    def bounds(self):
        now = time.monotonic()
        if now - self._poll_t > 2.0:
            self._poll_t = now
            self.refresh_displays()
        return self.desktop.bounds()

    def to_px(self, nx, ny):
        return self.desktop.to_px(nx, ny)

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
    def chord(self, code, mods=()):
        """Explicit modifier downs -> key down/up -> modifier ups, ~12 ms apart, HID event source."""
        if not is_trusted():
            _osa(osa_chord_script(code, mods))
            return
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        for c, down, flags, is_mod in chord_plan(code, mods):
            ev = Quartz.CGEventCreateKeyboardEvent(src, c, down)
            if is_mod:
                Quartz.CGEventSetType(ev, Quartz.kCGEventFlagsChanged)
            Quartz.CGEventSetFlags(ev, flags)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            time.sleep(CHORD_GAP)

    def scroll(self, dy):
        ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitPixel, 1, int(dy))
        self._post(ev)

    def run_action(self, spec):
        if not spec:
            return
        spec = BUILTIN.get(spec, spec)
        if spec.startswith("key:"):
            parts = spec.split(":")
            self.chord(int(parts[1]), parts[2].split(",") if len(parts) > 2 else [])
        elif spec.startswith("shell:"):
            subprocess.Popen(spec[6:], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif spec.startswith("script:"):
            _osa(spec[7:])

    # -- tiling (osascript): within the display holding the front window
    def tile(self, mode):
        scr = self.state.get().get("screen")
        if scr:
            threading.Thread(target=self._tile, args=(mode, scr), daemon=True).start()

    def _tile(self, mode, scr):
        vis = pick_visible(parse_rect(_osa_out(front_window_script())), scr["screens"], scr["primary_h"],
                           scr.get("main", 0))
        if not vis:
            return
        x, y, w, h = tile_rect(mode, vis, scr["primary_h"])
        _osa(f'''tell application "System Events"
  set p to first application process whose frontmost is true
  try
    set position of front window of p to {{{x}, {y}}}
    set size of front window of p to {{{w}, {h}}}
    set position of front window of p to {{{x}, {y}}}
  end try
end tell''')

    # -- dictation
    def dictation(self):
        threading.Thread(target=self._dictation, daemon=True).start()

    def _dictation(self):
        if _osa_out(dictation_script(), 4.0) != "ok":
            self.run_action(self.cfg.get("actions", {}).get("dictation"))

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
                    self.chord(K_RIGHT if v == "right" else K_LEFT, ["control"])
                elif k == "tile":
                    self.tile(v)
                elif k == "dictation":
                    self.dictation()
                elif k == "head":
                    if v == "next_app":
                        self.chord(K_TAB, ["command"])
                    elif v == "prev_app":
                        self.chord(K_TAB, ["command", "shift"])
                    elif v == "sleep":
                        subprocess.Popen(["pmset", "displaysleepnow"], stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
                elif k == "gaze":
                    spec = self.cfg["actions"].get(f"gaze:{v}")
                    if spec:
                        self.run_action(spec)
        except Exception as e:      # never kill the vision thread
            print("action error:", k, v, e)
