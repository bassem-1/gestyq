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
