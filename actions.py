"""Executes events on macOS with Quartz CGEvents (vision thread). macOS only.

The REAL pointer is moved: CGWarpMouseCursorPosition + a posted MouseMoved/LeftMouseDragged event,
then CGAssociateMouseAndMouseCursorPosition(True). Clicks, drags, scroll and keys are CGEvents.
Every event is resolved to a gesture id (bindings.gesture_of) and runs the action bound to it in
cfg["bindings"] (bindings.action_for); the action ids are bindings.ACTIONS. Media / volume keys are
NX system-defined events (built with AppKit.NSEvent, imported lazily, posted as CGEvents).
"""
import subprocess
import threading
import time

import Quartz

import bindings
from gestures import tile_rect

# virtual key codes
K_TAB, K_LEFT, K_RIGHT, K_DOWN, K_UP, K_F11, K_3 = 48, 123, 124, 125, 126, 103, 20
NX_SOUND_UP, NX_SOUND_DOWN, NX_PLAY = 0, 1, 16     # NX_KEYTYPE_*
MODS = {"control": Quartz.kCGEventFlagMaskControl, "command": Quartz.kCGEventFlagMaskCommand,
        "option": Quartz.kCGEventFlagMaskAlternate, "shift": Quartz.kCGEventFlagMaskShift}
NOTIFICATION_CENTER = (
    'tell application "System Events" to tell process "ControlCenter" to '
    'click menu bar item 1 of menu bar 1 whose description is "Clock"')
DOUBLE_CLICK_WINDOW = 0.6     # s: a double_click right after a click only adds the second click


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
        self._last_click = -1e9

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

    def _button(self, pt, down, right=False, count=1, middle=False):
        if middle:
            typ = Quartz.kCGEventOtherMouseDown if down else Quartz.kCGEventOtherMouseUp
            btn = Quartz.kCGMouseButtonCenter
        elif right:
            typ = Quartz.kCGEventRightMouseDown if down else Quartz.kCGEventRightMouseUp
            btn = Quartz.kCGMouseButtonRight
        else:
            typ = Quartz.kCGEventLeftMouseDown if down else Quartz.kCGEventLeftMouseUp
            btn = Quartz.kCGMouseButtonLeft
        ev = Quartz.CGEventCreateMouseEvent(None, typ, pt, btn)
        Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, count)
        self._post(ev)

    def click(self, pt, count=1, right=False, button=None):
        pt = pt or self.location()
        self.move_to(pt)
        mid = button == "middle"
        self._button(pt, True, right, count, mid)
        self._button(pt, False, right, count, mid)

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

    def media_key(self, key):
        """NX system key (play/pause, volume): key down + up as system-defined events."""
        from AppKit import NSEvent
        for flags, state in ((0xa00, 0xa), (0xb00, 0xb)):
            ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                14, (0, 0), flags, 0, 0, 0, 8, (key << 16) | (state << 8), -1)
            self._post(ev.CGEvent())

    @staticmethod
    def _run(args):
        try:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

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

    # -- actions (ids: bindings.ACTIONS)
    def run(self, action, pos=None, value=None):
        """Run one bound action. pos = screen px for the click actions (else the cursor)."""
        c = self.click
        now = time.monotonic()
        if action == "none":
            return
        if action == "left_click":
            c(pos); self._last_click = now
        elif action == "double_click":
            if now - self._last_click < DOUBLE_CLICK_WINDOW:     # the pinch already clicked once
                c(pos, 2)
            else:
                c(pos, 1); c(pos, 2)
            self._last_click = -1e9
        elif action == "right_click":
            c(pos, 1, right=True)
        elif action == "middle_click":
            c(pos, 1, button="middle")
        elif action == "scroll":
            self.scroll(value or 0)
        elif action == "scroll_inverted":
            self.scroll(-(value or 0))
        elif action == "next_space":
            self.key(K_RIGHT, MODS["control"])
        elif action == "prev_space":
            self.key(K_LEFT, MODS["control"])
        elif action == "mission_control":
            self.key(K_UP, MODS["control"])
        elif action == "app_windows":
            self.key(K_DOWN, MODS["control"])
        elif action == "show_desktop":
            self.key(K_F11)
        elif action == "launchpad":
            self._run(["open", "-a", "Launchpad"])
        elif action == "notification_center":
            _osa(NOTIFICATION_CENTER)
        elif action == "next_app":
            self.key(K_TAB, MODS["command"])
        elif action == "prev_app":
            self.key(K_TAB, MODS["command"] | MODS["shift"])
        elif action in ("tile_left", "tile_right", "tile_fill", "tile_center"):
            self.tile(action[5:])
        elif action == "play_pause":
            self.media_key(NX_PLAY)
        elif action == "volume_up":
            self.media_key(NX_SOUND_UP)
        elif action == "volume_down":
            self.media_key(NX_SOUND_DOWN)
        elif action == "screenshot":
            self.key(K_3, MODS["command"] | MODS["shift"])        # full screen, the system's own save location
        elif action == "display_sleep":
            self._run(["pmset", "displaysleepnow"])

    def execute(self, ev):
        k, v = ev.kind, ev.value
        try:
            with self.lock:
                if k == "move":
                    self.move_to(self.to_px(*v), self.dragging)
                elif k == "drag_move":
                    self.move_to(self.to_px(*v), True)
                elif k == "drag_end":
                    if self.dragging:
                        pt = self.to_px(*v) if v else self.last or self.location()
                        self.move_to(pt, True)
                        self._button(pt, False)
                        self.dragging = False
                else:
                    gid = bindings.gesture_of(ev)
                    if gid is None:
                        return
                    action = bindings.action_for(self.cfg, gid)
                    if k == "drag_start":
                        if action == "drag":
                            pt = self.to_px(*v)
                            self.move_to(pt)
                            self._button(pt, True)
                            self.dragging = True
                    elif k == "scroll":
                        self.run(action, value=v)
                    else:
                        pos = v.get("pos") if k == "gesture" else None
                        self.run(action, self.to_px(*pos) if pos else None)
        except Exception as e:      # never kill the vision thread
            print("action error:", k, v, e)
