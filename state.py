"""Lock-protected state shared between the vision thread and the UI (pure Python)."""
import threading


class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.d = {
            "enabled": False,       # app starts OFF
            "camera": "off",        # off | starting | ok | no camera
            "caption": "paused",
            "pulse_n": 0,           # increments on every fired action
            "hands": 0,
            "camera_uid": None,     # device actually in use (may differ from the saved choice) ...
            "camera_name": "",
            "camera_note": "",      # ... and why, e.g. "iphone camera not found · using facetime hd camera"
            "window_open": False,   # app window shown (the camera is NOT started by it: off means camera off)
            "live": None,           # window only, while the camera runs: {n, t, jpg, aspect, debug, head, gestures, caption}
            "recording": None,      # {active, elapsed} while the window is open
            "ink": None,            # air-writing canvas snapshot (gestures.GestureEngine.ink), None while the canvas is away
            "write": False,         # the canvas is up (the engine may type)
            "screen": None,         # {"visible": (x, y, w, h), "primary_h": h}, published by the UI thread
        }
        self.commands = []

    def update(self, **kw):
        with self.lock:
            self.d.update(kw)

    def get(self):
        with self.lock:
            return dict(self.d)

    def pulse(self):
        with self.lock:
            self.d["pulse_n"] += 1

    def command(self, name, value=None):
        with self.lock:
            self.commands.append((name, value))

    def pop_commands(self):
        with self.lock:
            out, self.commands = self.commands, []
            return out
