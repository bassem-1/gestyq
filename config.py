"""Config loading/saving (pure Python). The repo's config.json is the SHIPPED defaults (regenerate it with
`python3 config.py`); the running app keeps the user's settings in
~/Library/Application Support/gestyq/config.json (env GESTYQ_CONFIG overrides, used by tests)."""
import copy
import json
import os
import threading

import bindings
import cameras

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "config.json")          # shipped defaults, never written by the app
USER_PATH = os.path.expanduser("~/Library/Application Support/gestyq/config.json")
VERSION = "0.3.0"
CONFIG_VERSION = 9


def user_path():
    return os.environ.get("GESTYQ_CONFIG") or USER_PATH

POINTER_NAMES = ["off", "steady", "calm", "brisk", "fast"]
HEAD_NAMES = ["off", "low", "normal", "high", "max"]
# level -> multiplier on One Euro min_cutoff and beta (higher = snappier, less smoothing)
POINTER_SCALE = {1: 0.6, 2: 1.0, 3: 1.7, 4: 2.8}
# level -> multiplier on the relative pointer's gain (palm-size motion -> cursor px), 1-4
GAIN_SCALE = {1: 0.7, 2: 1.0, 3: 1.45, 4: 2.0}
# level -> multiplier on head thresholds (higher sensitivity = smaller threshold)
HEAD_SCALE = {1: 1.35, 2: 1.0, 3: 0.75, 4: 0.55}

DEFAULTS = {
    "config_version": CONFIG_VERSION,
    # --- popover settings
    "pointer_speed": 2,           # 0 off, 1 steady, 2 calm, 3 brisk, 4 fast
    "pointer_mode": "relative",   # relative: the hand moves the cursor like a mouse (any place in the frame);
                                  # absolute: a camera sub-rectangle maps onto the displays
    "writing_case": "upper",      # air-writing types capitals ("upper") or lowercase ("lower")
    "hot_corners": True,          # False: gesture-driven cursor stays 4 px away from the display corners
    "head_level": 2,              # 0 off, 1 low, 2 normal, 3 high, 4 max
    "tiling": True,
    "dwell_click": False,
    "eye_corners": False,         # beta
    "camera_id": None,            # AVCaptureDevice uniqueID of the chosen camera; None = auto (built-in camera)
    "camera_name": None,          # its name, for display only
    "swap_hands": False,          # manual override if roles still come out reversed
    "desktop_gadget": True,
    "gadget_floats": True,
    "launch_at_login": False,
    "gadget_after_quit": True,    # a tiny helper keeps the gadget on the desktop while gestyq is not running
    "gadget_origin": None,        # [x, y] in Cocoa screen coords
    "flip_gaze_x": False,
    # asks for width x height (falls back to 1280x720); detection sees `process_width` of it, or a full-resolution
    # crop around the upper body when the user is far (see roi.py). zoom_face_every = face frames while head
    # and eye corners are off (the face is then only the near / far reference).
    "camera": {"width": 1920, "height": 1080, "fps": 30, "process_width": 960, "face_every": 2,
               "zoom_face_every": 6,
               "zoom_process_width": 1280},     # detector input width while zoomed (never upscaled)
    "hand": {
        "frame_margin_x": 0.15,   # absolute mode: camera sub-rectangle mapped to the whole screen
        "frame_margin_y": 0.15,
        "min_cutoff": 1.2,        # One Euro on the pointer anchor, in 1/100-palm units
        "beta": 0.025,            # speed coefficient: smoothing lag 56 -> ~30 ms at 1 palm/s (was 1.0 / 0.007)
        "deadzone": 1.5,          # 1/1000-screen units
        "ext_deg": 155.0,         # PIP angle above which a finger is extended ...
        "soft_deg": 135.0,        # ... or above this when the tip is also far from the wrist (reach_ext)
        "curl_deg": 125.0,        # PIP angle below which a finger is curled
        "reach_ext": 1.6,         # wrist-tip / wrist-MCP distance: straight ~1.9, half curled ~1.4
        "reach_curl": 1.3,        # below this the tip is folded toward the palm
        "fist_reach": 1.25,       # a fist needs every fingertip under this (a pinch keeps the index out)
        "fist_pinch_reach": 1.05, # ... unless thumb meets index AND the index tip is held out beyond this
        "fist_median": 5,         # the fist test uses the median of the last k reach values per finger ...
        "fist_relax": 0.25,       # ... and fist_reach grows by up to this for small (far) hands, whose landmarks are noisy
        "fist_palm_ref": 0.06,    # palm_scale (frame widths) at and above which no relaxation applies
        "vote_frames": 3,
        "open_frames": 4,         # consecutive 'open' frames before swipe / tiling may fire
        "scroll_veto": 0.6,       # s after a two-finger frame during which swipe / tiling are blocked
        "pinch_on": 0.35,         # 2D thumb-index distance / palm size; real contact reads 0.1-0.3
        "pinch_off": 0.55,
        "pinch_frames": 2,
        "pinch_miss": 1,          # noisy frames a pinch survives
        "click_lookback": 0.12,   # click at the cursor position this long before pinch onset
        "buffer_window": 0.45,    # s of cursor positions kept (click lookback, flick restore)
        "rel_gain": 0.08,         # relative pointer: reference-display widths per palm size of hand travel, slow ...
        "rel_knee": 2.9,          # ... growing as 1 + (speed / knee)^2 (speed in palm sizes / s) ...
        "rel_max_gain": 0.45,     # ... up to this. 5 palm/s -> 0.31, so ~30 cm (3.2 palms) in 0.65 s crosses the screen
        "rel_deadzone": 1.0,      # 1/100 palm size of hand travel ignored (landmark jitter)
        "corner_px": 4,           # hot_corners off: gesture cursor stays this far from display corners
        "rel_gap": 0.1,           # s without frames after which a hand is re-anchored (no cursor jump)
        "double_click_gap": 0.4,
        "fist_hold": 0.15,
        "loss_grace": 0.15,
        "dwell_time": 0.9,
        "dwell_radius": 12,       # px
        "dwell_rearm": 40,        # px
        "scroll_gain": 3000,      # px per full frame height of hand travel (10 cm is about a page)
        "scroll_deadzone": 0.0008,
        "scroll_invert": False,
        # flick (either hand, any pose): a short burst of sideways speed, measured in palm sizes (palm_scale ~0.10
        # frame widths at a desk) so near and far hands behave alike. Cursor moves run 2-6 palm/s, a flick > 10.
        "flick_speed": 10.0,      # palm sizes / s, peak over >= flick_span
        "flick_span": 0.05,       # s over which the speed is measured
        "flick_travel": 0.8,      # palm sizes of sideways travel ...
        "flick_time": 0.25,       # ... within this many s
        "flick_vert": 0.8,        # max vertical / sideways travel
        "flick_gap": 0.35,        # s between flicks (rapid repeats each fire)
        "flick_return": 0.6,      # s after a flick during which the opposite direction (the return stroke) is ignored
        "flick_hold": 0.2,        # s the pointer hand's cursor stays put after a flick
        "tile_window": 0.6,
        "tile_move": 1.4,         # palm sizes of centre travel ...
        "tile_gap": 1.4,          # ... or of change in the gap between the palms
        "tile_cooldown": 1.0,
        "tile_both": 0.5,         # palm sizes EACH palm must travel (so one hand's flick never tiles)
        "spawn_frames": 5,        # a new hand must be seen this many frames in a row before it acts
        "face_hold": 0.5,         # s the last face box keeps vetoing
        "face_palm_ratio": 0.4,   # hand inside the face box and palm < this x face height = phantom
        "face_min_conf": 0.6,     # ... or handedness confidence below this
        # hands resting on the face / head are ignored (restface.py)
        "rest_filter": True,
        "rest_scale_x": 1.4,      # head region: face box width x this, centred
        "rest_up": 0.5,           # ... extended this many face heights above the box (top of the head)
        "rest_down": 0.3,         # ... and this many below it (chin / jaw band)
        "rest_still_time": 0.3,   # s a hand in the region must be still to count as resting
        "rest_speed": 0.5,        # still = palm centre extent below this many palm sizes / s
        "rest_overlap": 0.5,      # or this share of its landmarks inside the face box
        "rest_keep": 3.0,         # s an already-ignored hand is still judged against the last face box
        "min_detection_conf": 0.7,
        "min_presence_conf": 0.7,
        "min_tracking_conf": 0.5,
        # adaptive zoom + body-relative pointer box (face width / frame width = the distance reference)
        # at a desk the face is ~0.25-0.35 of a 16:9 frame (0.35 at arm's length from the screen, 0.25 at ~80 cm
        # leaning back); zoom engages only when sitting back beyond that, and the gap stops flapping.
        "far_face_frac": 0.22,    # enter zoom below this face width ...
        "near_face_frac": 0.27,   # ... leave it above this
        "roi_face_widths": 7.0,   # crop width in face widths (shoulders + raised arms); height: head to waist
        "roi_eye_frac": 0.2,      # the eyes sit this far down the crop (head top above, waist below)
        "full_every": 5,          # while zoomed: a full-frame hand detection every N frames, to re-acquire hands
                                  # that left the crop
        "merge_dist": 0.06,       # wrists closer than this (frame widths) are the same hand when merging
        "roi_hand_pad": 0.10,     # frame widths of margin around a hand found outside the crop
        "roi_hand_ttl": 0.8,      # s the crop stays grown around such a hand after it was last seen
        "roi_tau": 0.3,           # s, EMA of the crop
        "roi_shift": 0.10,        # the crop moves only when its target shifts more than this
        "box_face_widths": 4.5,   # far: control box width in face widths (0.72 of the frame at far_face_frac)
        "box_offset_x": 1.2,      # far: face widths toward the pointer hand's shoulder
        "box_offset_y": 1.5,      # far: face widths below the eyes
        "box_tau": 0.4,           # s, EMA of the control box
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
    # air-writing: when a text field is clicked a small black canvas appears; the index fingertip draws, a letter
    # ends when the tip is still for `still` s or the pen is up for `pause` s (see ink.py, recognizer.py)
    "write": {
        "enabled": True,          "trigger": "click",       "recognizer": "templates",
        "pause": 0.6,             "still": 0.5,             "still_radius": 0.12,      # s, s, palm sizes
        "arm_delay": 0.5,         "idle_hide": 12.0,        "poll": 0.2,
        "cursor_hold": 0.15,      "click_guard": 0.25,
        "min_ink": 0.5,           "min_size": 0.6,          # palm sizes: shorter / smaller ink is dropped
        "reject": 0.28,           "margin": 0.02,           "user_weight": 0.9,   "max_user": 5,
        "min_cutoff": 2.0,        "beta": 0.02,             "ink_scale": 48,      # ink_scale: points per palm size
    },
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
LEGACY_DEFAULTS = {"hand": {"min_cutoff": 1.0, "beta": 0.007, "ext_deg": 160.0, "curl_deg": 110.0, "vote_frames": 5, "pinch_on": 0.25,
                            "pinch_off": 0.40, "scroll_gain": 1800, "scroll_deadzone": 0.002,
                            "tile_move": 0.15, "tile_gap": 0.15, "min_detection_conf": 0.6, "min_presence_conf": 0.6,
                            "far_face_frac": 0.16, "near_face_frac": 0.20, "buffer_window": 0.3},
                   "camera": {"width": 1280, "height": 720},
                   "bindings": {"palms_together": "tile_center"}}      # v8: palms together = minimize

# keys that no longer exist (the open-palm swipe became the flick)
OBSOLETE = {"hand": ("swipe_dist", "swipe_min", "swipe_time", "swipe_cooldown", "swipe_grace")}


def _upgrade(raw):
    """Old file layout -> current (pure, returns a new dict)."""
    raw = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    if raw.get("config_version", 1) < CONFIG_VERSION:
        for sec, old in LEGACY_DEFAULTS.items():
            for k, v in old.items():
                olds = v if isinstance(v, tuple) else (v,)          # every default a key ever shipped with
                if isinstance(raw.get(sec), dict) and k in raw[sec] and raw[sec][k] in olds:
                    del raw[sec][k]
        for sec, keys in OBSOLETE.items():
            for k in keys:
                if isinstance(raw.get(sec), dict):
                    raw[sec].pop(k, None)
        if cameras.is_continuity(raw.get("camera_name")):         # an accidental click on the old one-click row
            raw["camera_name"] = None
            raw.pop("camera_id", None)
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
