"""Executes events on macOS with Quartz CGEvents (vision thread). macOS only.

The REAL pointer is moved: CGWarpMouseCursorPosition + a posted MouseMoved/LeftMouseDragged event,
then CGAssociateMouseAndMouseCursorPosition(True). Clicks, drags, scroll and keys are CGEvents.
Pointer, button and scroll events carry a HID-system-state event source, so they count as user activity for
the idle / display-sleep timer like a real mouse. Hand activity also wakes a sleeping display (wake_display).
Every event is resolved to a gesture id (bindings.gesture_of) and runs the action bound to it in
cfg["bindings"] (bindings.action_for); the action ids are bindings.ACTIONS. Media / volume keys are
NX system-defined events (built with AppKit.NSEvent, imported lazily, posted as CGEvents).
"""
import ctypes
import queue
import subprocess
import threading
import time

import Quartz

import bindings
from desktop import Desktop, guard_corners, parse_rect, pick_visible
from gestures import tile_rect

# virtual key codes
K_TAB, K_LEFT, K_RIGHT, K_DOWN, K_UP, K_F11, K_3 = 48, 123, 124, 125, 126, 103, 20
K_M, K_F = 46, 3
K_CMD, K_SHIFT, K_OPT, K_CTRL = 55, 56, 58, 59
ARROWS = (K_LEFT, K_RIGHT, K_DOWN, K_UP)
FN_FLAG = Quartz.kCGEventFlagMaskSecondaryFn
NUMPAD_FLAG = Quartz.kCGEventFlagMaskNumericPad
KEY_STEP = 0.01        # s between the steps of a key sequence
KEY_GAP = 0.06         # s between two queued chords (quick successive flicks: each plays out alone, none is dropped)
KEY_HOLD = 0.07        # s the modifiers stay down after the main key (cmd+tab needs the switcher to register)
NX_SOUND_UP, NX_SOUND_DOWN, NX_PLAY = 0, 1, 16     # NX_KEYTYPE_*
MODS = {"control": Quartz.kCGEventFlagMaskControl, "command": Quartz.kCGEventFlagMaskCommand,
        "option": Quartz.kCGEventFlagMaskAlternate, "shift": Quartz.kCGEventFlagMaskShift}
# modifier key presses, in press order: (virtual key, flag)
MOD_KEYS = ((K_CTRL, MODS["control"]), (K_OPT, MODS["option"]), (K_SHIFT, MODS["shift"]), (K_CMD, MODS["command"]))
NOTIFICATION_CENTER = (
    'tell application "System Events" to tell process "ControlCenter" to '
    'click menu bar item 1 of menu bar 1 whose description is "Clock"')
DISPLAY_POLL = 1.0            # s between display layout queries from the vision thread (cheap CG calls)
FRONT_WINDOW = '''tell application "System Events"
  set p to first application process whose frontmost is true
  try
    set {x, y} to position of front window of p
    set {w, h} to size of front window of p
    return (x as text) & "," & (y as text) & "," & (w as text) & "," & (h as text)
  end try
end tell
return ""'''
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


def _osa_out(script, timeout=3.0):
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def query_displays():
    """Active displays as global CG rects [(x, y, w, h)] (origin top-left of the primary display, y down)."""
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
        self._last_click = -1e9
        self._keyq, self._keythread = queue.Queue(), None
        self._src = None
        self._assertion = 0

    # -- geometry: the pointer covers the union of all active displays
    def refresh_displays(self):
        """Any thread. Re-reads the display layout; -> True when it changed. A change drops a held
        drag (its start point may no longer exist) so the button never stays down."""
        try:
            changed = self.desktop.set(query_displays())
        except Exception as e:
            print("display query failed:", e)
            return False
        if changed:
            print("displays:", self.desktop.rects(), flush=True)
            self.release_all()
            self.last = None
        return changed

    def bounds(self):
        """Union of the displays (x, y, w, h); re-queried every DISPLAY_POLL s."""
        now = time.monotonic()
        if now - self._poll_t > DISPLAY_POLL:
            self._poll_t = now
            self.refresh_displays()
        return self.desktop.bounds()

    def to_px(self, nx, ny):
        """Normalised control-box point -> global CG point on a display (dead areas snap to the nearest). With
        cfg["hot_corners"] off the point stays corner_px (4) away from every display corner (edges stay reachable)."""
        pt = self.desktop.to_px(nx, ny)
        if not self.cfg.get("hot_corners", True):
            pt = guard_corners(pt, self.desktop.rects(), self.cfg["hand"].get("corner_px", 4))
        return pt

    def location(self):
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return (loc.x, loc.y)

    @staticmethod
    def _post(ev):
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

    def source(self):
        """HID system state event source: events made with it are indistinguishable from hardware for the idle timer."""
        if self._src is None:
            self._src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        return self._src

    # -- display sleep / wake
    @staticmethod
    def display_asleep():
        try:
            return bool(Quartz.CGDisplayIsAsleep(Quartz.CGMainDisplayID()))
        except Exception:
            return False

    def _declare_user_activity(self):
        """IOPMAssertionDeclareUserActivity(kIOPMUserActiveLocal): what a trackpad touch does. Raises on failure."""
        iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        iokit.IOPMAssertionDeclareUserActivity.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint32)]
        iokit.IOPMAssertionDeclareUserActivity.restype = ctypes.c_int
        iokit.IOPMAssertionRelease.argtypes = [ctypes.c_uint32]
        iokit.IOPMAssertionRelease.restype = ctypes.c_int
        if self._assertion:                                 # release the previous one (a new one every >= 2 s)
            iokit.IOPMAssertionRelease(self._assertion)
            self._assertion = 0
        name = cf.CFStringCreateWithCString(None, b"gestyq hand activity", 0x08000100)      # kCFStringEncodingUTF8
        aid = ctypes.c_uint32(0)
        try:
            r = iokit.IOPMAssertionDeclareUserActivity(name, 0, ctypes.byref(aid))           # 0 = kIOPMUserActiveLocal
        finally:
            cf.CFRelease(name)
        if r != 0:
            raise OSError(f"IOPMAssertionDeclareUserActivity returned {r}")
        self._assertion = aid.value

    def wake_display(self):
        """Wake the display like a trackpad touch; falls back to `caffeinate -u -t 2`."""
        try:
            self._declare_user_activity()
        except Exception as e:
            print("user activity assertion failed, using caffeinate:", e, flush=True)
            self._run(["caffeinate", "-u", "-t", "2"])

    # -- pointer
    def move_to(self, pt, dragging=False):
        prev = self.last or pt
        Quartz.CGWarpMouseCursorPosition(pt)
        typ = Quartz.kCGEventLeftMouseDragged if dragging else Quartz.kCGEventMouseMoved
        ev = Quartz.CGEventCreateMouseEvent(self.source(), typ, pt, Quartz.kCGMouseButtonLeft)
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
        ev = Quartz.CGEventCreateMouseEvent(self.source(), typ, pt, btn)
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
        """Queue a key chord. A worker thread plays it (real modifier key presses and short holds), so
        the vision thread never sleeps."""
        if self._keythread is None:
            self._keythread = threading.Thread(target=self._key_worker, daemon=True, name="gestyq-keys")
            self._keythread.start()
        self._keyq.put((code, flags))

    def _key_worker(self):
        while True:
            code, flags = self._keyq.get()
            try:
                self.key_sequence(code, flags)
                time.sleep(KEY_GAP)
            except Exception as e:
                print("key error:", code, flags, e)

    @staticmethod
    def key_flags(code, flags):
        """Flags a real key press carries: arrows also have fn + numpad set, F-keys have fn. Mission
        Control's ctrl+arrow hotkeys ignore arrow events without them."""
        if code in ARROWS:
            return flags | FN_FLAG | NUMPAD_FLAG
        if code == K_F11:
            return flags | FN_FLAG
        return flags

    def key_sequence(self, code, flags=0, sleep=time.sleep):
        """modifier downs (flags accumulate) -> key down/up with the full flags -> hold -> modifier ups
        in reverse (flags decrease). The release of the held Command is what commits cmd+tab."""
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        mods = [(k, f) for k, f in MOD_KEYS if flags & f]
        cur = 0

        def post(kc, down, fl):
            ev = Quartz.CGEventCreateKeyboardEvent(src, kc, down)
            Quartz.CGEventSetFlags(ev, fl)
            self._post(ev)

        for kc, f in mods:
            cur |= f
            post(kc, True, cur)
            sleep(KEY_STEP)
        full = self.key_flags(code, flags)
        post(code, True, full)
        sleep(KEY_STEP)
        post(code, False, full)
        if mods:
            sleep(KEY_HOLD)
        for kc, f in reversed(mods):
            cur &= ~f
            post(kc, False, cur)
            sleep(KEY_STEP)

    def scroll(self, dy):
        ev = Quartz.CGEventCreateScrollWheelEvent(self.source(), Quartz.kCGScrollEventUnitPixel, 1, int(dy))
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
        """On the display holding the front window (found by asking System Events; osascript is slow,
        so off the vision thread)."""
        scr = self.state.get().get("screen")
        if scr:
            threading.Thread(target=self._tile, args=(mode, scr), daemon=True, name="gestyq-tile").start()

    def _tile(self, mode, scr):
        vis = pick_visible(parse_rect(_osa_out(FRONT_WINDOW)), scr["screens"], scr["primary_h"], scr.get("main", 0))
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
        elif action == "minimize":
            self.key(K_M, MODS["command"])                          # front window to the dock
        elif action == "full_screen":
            self.key(K_F, MODS["command"] | MODS["control"])        # toggle the front window's full screen
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
                    self.move_to(self.to_px(*v), self.dragging)     # a dropped drag (display change) just moves
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
