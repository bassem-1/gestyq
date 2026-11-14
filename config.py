"""Config loading/saving (pure Python). The repo's config.json is the SHIPPED defaults (regenerate it with
`python3 config.py`); the running app keeps the user's settings in
~/Library/Application Support/gestyq/config.json (env GESTYQ_CONFIG overrides, used by tests)."""
import copy
import json
import os
import threading

import bindings

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "config.json")          # shipped defaults, never written by the app
USER_PATH = os.path.expanduser("~/Library/Application Support/gestyq/config.json")
VERSION = "0.3.0"
CONFIG_VERSION = 3


def user_path():
    return os.environ.get("GESTYQ_CONFIG") or USER_PATH

POINTER_NAMES = ["off", "steady", "calm", "brisk", "fast"]
HEAD_NAMES = ["off", "low", "normal", "high", "max"]
# level -> multiplier on One Euro min_cutoff and beta (higher = snappier, less smoothing)
POINTER_SCALE = {1: 0.6, 2: 1.0, 3: 1.7, 4: 2.8}
# level -> multiplier on head thresholds (higher sensitivity = smaller threshold)
HEAD_SCALE = {1: 1.35, 2: 1.0, 3: 0.75, 4: 0.55}

DEFAULTS = {
    "config_version": CONFIG_VERSION,
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
        "ext_deg": 155.0,         # PIP angle above which a finger is extended ...
        "soft_deg": 135.0,        # ... or above this when the tip is also far from the wrist (reach_ext)
        "curl_deg": 125.0,        # PIP angle below which a finger is curled
        "reach_ext": 1.6,         # wrist-tip / wrist-MCP distance: straight ~1.9, half curled ~1.4
        "reach_curl": 1.3,        # below this the tip is folded toward the palm
        "fist_reach": 1.25,       # a fist needs every fingertip under this (a pinch keeps the index out)
        "fist_pinch_reach": 1.05, # ... unless thumb meets index AND the index tip is held out beyond this
        "vote_frames": 3,
        "open_frames": 4,         # consecutive 'open' frames before swipe / tiling may fire
        "scroll_veto": 0.6,       # s after a two-finger frame during which swipe / tiling are blocked
        "pinch_on": 0.35,         # 2D thumb-index distance / palm size; real contact reads 0.1-0.3
        "pinch_off": 0.55,
        "pinch_frames": 2,
        "pinch_miss": 1,          # noisy frames a pinch survives
        "click_lookback": 0.12,   # click at the cursor position this long before pinch onset
        "buffer_window": 0.3,
        "double_click_gap": 0.4,
        "fist_hold": 0.15,
        "loss_grace": 0.15,
        "dwell_time": 0.9,
        "dwell_radius": 12,       # px
        "dwell_rearm": 40,        # px
        "scroll_gain": 3000,      # px per full frame height of hand travel (10 cm is about a page)
        "scroll_deadzone": 0.0008,
        "scroll_invert": False,
        "swipe_dist": 0.18,       # fraction of frame width ...
        "swipe_time": 0.45,       # ... within this many s (0.25 in 0.35 s was faster than a natural swipe)
        "swipe_cooldown": 1.0,
        "tile_window": 0.6,
        "tile_move": 0.15,
        "tile_gap": 0.15,
        "tile_cooldown": 1.0,
        "spawn_frames": 5,        # a new hand must be seen this many frames in a row before it acts
        "face_hold": 0.5,         # s the last face box keeps vetoing
        "face_palm_ratio": 0.4,   # hand inside the face box and palm < this x face height = phantom
        "face_min_conf": 0.6,     # ... or handedness confidence below this
        "min_detection_conf": 0.7,
        "min_presence_conf": 0.7,
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
    # gesture id -> action id (see bindings.py); the app window edits this
    "bindings": dict(bindings.DEFAULT_BINDINGS),
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


# values the old default config shipped with and that were retuned: a saved copy of an OLD default
# must not pin the new default (the app used to write its whole config).
LEGACY_DEFAULTS = {"hand": {"ext_deg": 160.0, "curl_deg": 110.0, "vote_frames": 5, "pinch_on": 0.25,
                            "pinch_off": 0.40, "scroll_gain": 1800, "scroll_deadzone": 0.002,
                            "swipe_dist": 0.25, "swipe_time": 0.35,
                            "min_detection_conf": 0.6, "min_presence_conf": 0.6}}


def _upgrade(raw):
    """Old file layout -> current (pure, returns a new dict)."""
    raw = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    if raw.get("config_version", 1) < CONFIG_VERSION:
        for sec, old in LEGACY_DEFAULTS.items():
            for k, v in old.items():
                if isinstance(raw.get(sec), dict) and raw[sec].get(k) == v:
                    del raw[sec][k]
        raw["config_version"] = CONFIG_VERSION
    actions = raw.pop("actions", None)             # v0.3 gaze map "gaze:top-left" -> action
    if isinstance(actions, dict):
        b = raw.setdefault("bindings", {})
        for k, v in actions.items():
            g = "gaze_" + k.split(":", 1)[-1].replace("-", "_")
            if k.startswith("gaze:") and g in bindings.GESTURES and v in bindings.choices(g):
                b.setdefault(g, v)
    return raw


def _read(path):
    with open(path) as f:
        return json.load(f)


def load(path=None):
    """Merge a settings file onto DEFAULTS. No path = the user's file (GESTYQ_CONFIG or
    ~/Library/Application Support/gestyq); if that file does not exist yet, a customised repo
    config.json (old versions wrote their settings there) is migrated into it once."""
    if path is None:
        path = user_path()
        if not os.path.exists(path):
            try:
                shipped = _merge(DEFAULTS, _upgrade(_read(PATH)))
            except (OSError, ValueError):
                shipped = None
            if shipped is not None and shipped != DEFAULTS:
                try:
                    save(shipped, path)
                except OSError:
                    pass
                return shipped
    try:
        return _merge(DEFAULTS, _upgrade(_read(path)))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)


def save(cfg, path=None):
    path = path or user_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
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
    save(DEFAULTS, PATH)      # regenerate the shipped config.json
