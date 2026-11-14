"""Config loading/saving (pure Python). Settings persist to config.json via a debounced saver."""
import copy
import json
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "config.json")
VERSION = "0.3.0"

POINTER_NAMES = ["off", "steady", "calm", "brisk", "fast"]
HEAD_NAMES = ["off", "low", "normal", "high", "max"]
# level -> multiplier on One Euro min_cutoff and beta (higher = snappier, less smoothing)
POINTER_SCALE = {1: 0.6, 2: 1.0, 3: 1.7, 4: 2.8}
# level -> multiplier on head thresholds (higher sensitivity = smaller threshold)
HEAD_SCALE = {1: 1.35, 2: 1.0, 3: 0.75, 4: 0.55}

DEFAULTS = {
    # --- popover settings
    "pointer_speed": 2,           # 0 off, 1 steady, 2 calm, 3 brisk, 4 fast
    "head_level": 2,              # 0 off, 1 low, 2 normal, 3 high, 4 max
    "tiling": True,
    "dwell_click": False,
    "eye_corners": False,         # beta
    "camera_name": None,          # None = auto (built-in camera)
    "swap_hands": False,          # manual override if roles still come out reversed
    "desktop_gadget": True,
    "gadget_floats": True,
    "launch_at_login": False,
    "gadget_origin": None,        # [x, y] in Cocoa screen coords
    "flip_gaze_x": False,
    "camera": {"width": 1280, "height": 720, "fps": 30, "process_width": 960, "face_every": 2},
    "hand": {
        "frame_margin_x": 0.15,   # camera sub-rectangle mapped to the whole screen
        "frame_margin_y": 0.15,
        "min_cutoff": 1.0,        # One Euro on the pointer anchor, in 1/1000-screen units
        "beta": 0.007,
        "deadzone": 1.5,          # 1/1000-screen units
        "ext_deg": 160.0,         # PIP angle above which a finger is extended
        "curl_deg": 110.0,        # ... and below which it is curled
        "vote_frames": 5,
        "pinch_on": 0.25,
        "pinch_off": 0.40,
        "pinch_frames": 2,
        "click_lookback": 0.12,   # click at the cursor position this long before pinch onset
        "buffer_window": 0.3,
        "double_click_gap": 0.4,
        "fist_hold": 0.15,
        "loss_grace": 0.15,
        "dwell_time": 0.9,
        "dwell_radius": 12,       # px
        "dwell_rearm": 40,        # px
        "scroll_gain": 1800,      # px per full frame height of hand travel
        "scroll_deadzone": 0.002,
        "scroll_invert": False,
        "swipe_dist": 0.25,
        "swipe_time": 0.35,
        "swipe_cooldown": 1.0,
        "tile_window": 0.6,
        "tile_move": 0.15,
        "tile_gap": 0.15,
        "tile_cooldown": 1.0,
        "min_detection_conf": 0.6,
        "min_presence_conf": 0.6,
        "min_tracking_conf": 0.5,
    },
    "handedness": {
        "label_weight": 1.0,
        "geometry_weight": 2.0,
        "position_weight": 0.5,
        "vote_tau": 0.4,          # s, exponential vote
        "flip_margin": 0.3,
        "flip_time": 0.5,
        "track_dist": 0.3,
        "track_ttl": 1.0,
    },
    "head": {
        "yaw_deg": 12.0,          # base thresholds (degrees, level 2)
        "pitch_deg": 12.0,
        "yaw_per_deg": 0.0055,    # nose-offset proxy units per degree of yaw
        "pitch_per_deg": 0.006,
        "min_cutoff": 1.2,
        "beta": 0.05,
        "calib_time": 1.0,
        "baseline_tau": 20.0,     # s, slow EMA
        "band": 0.35,             # fraction of the threshold counted as 'near neutral'
        "rise_max": 0.6,          # s from leaving neutral to crossing the threshold
        "return_time": 0.9,       # s allowed beyond the threshold before returning
        "cooldown": 0.8,
        "sleep_hold": 0.6,
        "sleep_cooldown": 5.0,
        "face_loss_reset": 0.5,
    },
    "gaze": {"x_thresh": 0.30, "up_thresh": 0.25, "down_thresh": 0.25, "dwell": 2.0, "grace": 0.3},
    # gaze event "gaze:<corner>" -> action: builtin name, "key:<code>[:mod,mod]", "shell:<cmd>", "script:<osa>"
    "actions": {
        "gaze:bottom-right": "show_desktop",
        "gaze:top-left": "mission_control",
        "gaze:top-right": "notification_center",
        "gaze:bottom-left": "launchpad",
    },
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path=PATH):
    try:
        with open(path) as f:
            return _merge(DEFAULTS, json.load(f))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)


def save(cfg, path=PATH):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)


class Debounced:
    """Calls fn() `delay` seconds after the last poke(); flush() runs it now if pending."""

    def __init__(self, fn, delay=0.3):
        self.fn, self.delay = fn, delay
        self.timer = None
        self.lock = threading.Lock()

    def poke(self):
        with self.lock:
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(self.delay, self._fire)
            self.timer.daemon = True
            self.timer.start()

    def _fire(self):
        with self.lock:
            self.timer = None
        self.fn()

    def flush(self):
        with self.lock:
            pending, self.timer = self.timer, None
            if pending:
                pending.cancel()
        if pending:
            self.fn()


if __name__ == "__main__":
    save(DEFAULTS)
