"""Live view / recording helpers shared by the vision thread and the app window (pure Python).

camera_wanted decides whether the vision thread has the camera; Recorder writes landmark sessions
as JSON lines; GestureLog keeps the last recognised gestures for the window."""
import json
import os
import time
from collections import deque

import bindings

RECORD_DIR = os.path.expanduser("~/Library/Application Support/gestyq/recordings")
PREVIEW_FPS = 15
LOG_SIZE = 8


def camera_wanted(enabled):
    """The camera runs exactly while gestyq is on. The window being open changes nothing: off is camera off."""
    return bool(enabled)


def mode_label(enabled):
    return "on" if enabled else "off · camera off"


def frame_record(t, aspect, hands):
    """One recording line (dict). hands: [HandObs-like with .lms, .label, .conf]."""
    return {"t": round(float(t), 4), "aspect": round(float(aspect), 4),
            "hands": [{"lms": [[round(float(c), 5) for c in p[:3]] for p in h.lms],
                       "label": str(h.label), "conf": round(float(h.conf), 3)} for h in hands]}


def recording_path(now=None, directory=RECORD_DIR):
    return os.path.join(directory, time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + ".jsonl")


class Recorder:
    """Not thread safe on purpose: owned by the vision thread."""

    def __init__(self, directory=RECORD_DIR):
        self.directory, self.f, self.path, self.t0 = directory, None, None, 0.0

    @property
    def active(self):
        return self.f is not None

    def start(self, now):
        if self.f:
            return self.path
        os.makedirs(self.directory, exist_ok=True)
        self.path = recording_path(directory=self.directory)
        self.f = open(self.path, "w")
        self.t0 = now
        return self.path

    def write(self, t, aspect, hands):
        if self.f:
            self.f.write(json.dumps(frame_record(t, aspect, hands), separators=(",", ":")) + "\n")

    def stop(self):
        if self.f:
            self.f.close()
            self.f = None

    def elapsed(self, now):
        return int(now - self.t0) if self.f else 0


def recording_label(active, elapsed):
    return f"recording · {int(elapsed)} s" if active else "record"


class GestureLog:
    """Last recognised gestures. Each entry: (seq, t, gesture id). Thread safe enough for the
    vision thread writing and a snapshot copy being published."""

    def __init__(self, size=LOG_SIZE):
        self.items, self.seq = deque(maxlen=size), 0

    def add(self, gid, now):
        self.seq += 1
        self.items.append((self.seq, now, gid))

    def add_events(self, events, now):
        for e in events:
            gid = bindings.gesture_of(e)
            if gid in bindings.GESTURES:
                self.add(gid, now)

    def snapshot(self):
        return list(self.items)

    def clear(self):
        self.items.clear()


def log_line(gid, cfg):
    g = bindings.GESTURES[gid]
    act = bindings.ACTIONS[bindings.action_for(cfg, gid)]["label"]
    return f"{g['label']} → {act}"


def finger_letters(fingers):
    """{'thumb': 'ext', ...} -> 'T I M R P' style, upper = extended."""
    return " ".join(k[0].upper() if v == "ext" else k[0] for k, v in fingers.items())


def meter_fraction(ratio, top=0.7):
    return max(0.0, min(1.0, ratio / top))

