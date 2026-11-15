"""Gesture -> action bindings (pure Python). The single source of truth shared by the engine
(gestures.py / head.py / gaze.py), the executor (actions.py) and the app window (ui/).

A *gesture* is something the user does; an *action* is what the mac does. cfg["bindings"] maps
gesture id -> action id. Users change bindings in the app window; nothing here is hard-coded
elsewhere.
"""

# ---------------------------------------------------------------- actions
# kind: "discrete" fires once; "drag" / "scroll" are continuous and only valid on continuous gestures.
# needs_pos: the action happens at a screen position (the gesture's position, else the cursor).
ACTIONS = {
    "none":                {"label": "nothing",              "kind": "discrete"},
    "left_click":          {"label": "click",                "kind": "discrete", "needs_pos": True},
    "double_click":        {"label": "double click",         "kind": "discrete", "needs_pos": True},
    "right_click":         {"label": "right click",          "kind": "discrete", "needs_pos": True},
    "middle_click":        {"label": "middle click",         "kind": "discrete", "needs_pos": True},
    "drag":                {"label": "drag",                 "kind": "drag"},
    "scroll":              {"label": "scroll",               "kind": "scroll"},
    "scroll_inverted":     {"label": "scroll (inverted)",    "kind": "scroll"},
    "next_space":          {"label": "next space",           "kind": "discrete"},
    "prev_space":          {"label": "previous space",       "kind": "discrete"},
    "mission_control":     {"label": "mission control",      "kind": "discrete"},
    "app_windows":         {"label": "app windows",          "kind": "discrete"},
    "show_desktop":        {"label": "show desktop",         "kind": "discrete"},
    "launchpad":           {"label": "launchpad",            "kind": "discrete"},
    "notification_center": {"label": "notification center",  "kind": "discrete"},
    "next_app":            {"label": "next app",             "kind": "discrete"},
    "prev_app":            {"label": "previous app",         "kind": "discrete"},
    "tile_left":           {"label": "tile window left",     "kind": "discrete"},
    "tile_right":          {"label": "tile window right",    "kind": "discrete"},
    "tile_fill":           {"label": "maximize",             "kind": "discrete"},
    "tile_center":         {"label": "centre window",        "kind": "discrete"},
    "minimize":            {"label": "minimize",             "kind": "discrete"},
    "full_screen":         {"label": "full screen",          "kind": "discrete"},
    "play_pause":          {"label": "play / pause",         "kind": "discrete"},
    "volume_up":           {"label": "volume up",            "kind": "discrete"},
    "volume_down":         {"label": "volume down",          "kind": "discrete"},
    "screenshot":          {"label": "screenshot",           "kind": "discrete"},
    "display_sleep":       {"label": "display sleep",        "kind": "discrete"},
}

DISCRETE = [a for a, d in ACTIONS.items() if d["kind"] == "discrete"]

# ---------------------------------------------------------------- gestures
# group: section in the app window. kind: "discrete" | "drag" | "scroll" (which action kinds fit).
# hand: "pointer" (right by default), "command" (left by default), "either" (any hand), "both", "head", "eyes".
# Order here is the order shown in the app window.
GESTURES = {
    "pinch":          {"group": "pointer hand", "hand": "pointer", "kind": "discrete", "label": "pinch",
                       "how": "touch thumb and index tips, then let go"},
    "double_pinch":   {"group": "pointer hand", "hand": "pointer", "kind": "discrete", "label": "double pinch",
                       "how": "two pinches within 0.4 s; fires on the second one"},
    "fist":           {"group": "pointer hand", "hand": "pointer", "kind": "drag", "label": "fist hold",
                       "how": "close the hand for 0.15 s; open it to finish"},
    "dwell":          {"group": "pointer hand", "hand": "pointer", "kind": "discrete", "label": "dwell",
                       "how": "hold the cursor still for 0.9 s (dwell click switch)"},
    "left_pinch":     {"group": "command hand", "hand": "command", "kind": "discrete", "label": "pinch",
                       "how": "touch thumb and index tips on the other hand"},
    "two_finger":     {"group": "command hand", "hand": "command", "kind": "scroll", "label": "two fingers",
                       "how": "index and middle up, ring and pinky folded; move up or down"},
    "swipe_left":     {"group": "either hand", "hand": "either", "kind": "discrete", "label": "flick left",
                       "how": "flick either hand to your left, like waving a fly away"},
    "swipe_right":    {"group": "either hand", "hand": "either", "kind": "discrete", "label": "flick right",
                       "how": "flick either hand to your right, like waving a fly away"},
    "palms_left":     {"group": "both hands", "hand": "both", "kind": "discrete", "label": "both palms left",
                       "how": "both palms open, move together to your left"},
    "palms_right":    {"group": "both hands", "hand": "both", "kind": "discrete", "label": "both palms right",
                       "how": "both palms open, move together to your right"},
    "palms_apart":    {"group": "both hands", "hand": "both", "kind": "discrete", "label": "palms apart",
                       "how": "both palms open, spread them apart"},
    "palms_together": {"group": "both hands", "hand": "both", "kind": "discrete", "label": "palms together",
                       "how": "both palms open, bring them together"},
    "head_right":     {"group": "head", "hand": "head", "kind": "discrete", "label": "turn right",
                       "how": "turn your head right and back"},
    "head_left":      {"group": "head", "hand": "head", "kind": "discrete", "label": "turn left",
                       "how": "turn your head left and back"},
    "head_up":        {"group": "head", "hand": "head", "kind": "discrete", "label": "tilt up",
                       "how": "tilt your head up and hold 0.6 s"},
    "gaze_top_left":     {"group": "eyes · beta", "hand": "eyes", "kind": "discrete", "label": "look top left",
                          "how": "look at the top-left corner for 2 s"},
    "gaze_top_right":    {"group": "eyes · beta", "hand": "eyes", "kind": "discrete", "label": "look top right",
                          "how": "look at the top-right corner for 2 s"},
    "gaze_bottom_left":  {"group": "eyes · beta", "hand": "eyes", "kind": "discrete", "label": "look bottom left",
                          "how": "look at the bottom-left corner for 2 s"},
    "gaze_bottom_right": {"group": "eyes · beta", "hand": "eyes", "kind": "discrete", "label": "look bottom right",
                          "how": "look at the bottom-right corner for 2 s"},
}

DEFAULT_BINDINGS = {
    "pinch": "left_click",
    "double_pinch": "double_click",
    "fist": "drag",
    "dwell": "left_click",
    "left_pinch": "right_click",
    "two_finger": "scroll",
    "swipe_left": "next_space",        # flick to the user's left -> next space (trackpad convention)
    "swipe_right": "prev_space",
    "palms_left": "tile_left",
    "palms_right": "tile_right",
    "palms_apart": "tile_fill",
    "palms_together": "minimize",
    "head_right": "next_app",
    "head_left": "prev_app",
    "head_up": "display_sleep",
    "gaze_top_left": "mission_control",
    "gaze_top_right": "notification_center",
    "gaze_bottom_left": "launchpad",
    "gaze_bottom_right": "show_desktop",
}


def choices(gesture):
    """Action ids that may be bound to this gesture, in display order."""
    kind = GESTURES[gesture]["kind"]
    special = {"drag": ["drag"], "scroll": ["scroll", "scroll_inverted"]}.get(kind, [])
    return special + DISCRETE


def action_for(cfg, gesture):
    """Bound action id, falling back to the default when missing or invalid."""
    a = (cfg.get("bindings") or {}).get(gesture)
    return a if a in choices(gesture) else DEFAULT_BINDINGS[gesture]


def groups():
    """[(group, [gesture ids])] in display order."""
    out = []
    for g, d in GESTURES.items():
        if not out or out[-1][0] != d["group"]:
            out.append((d["group"], []))
        out[-1][1].append(g)
    return out


HEAD_GESTURE = {"next_app": "head_right", "prev_app": "head_left", "sleep": "head_up"}


def gesture_of(ev):
    """Gesture id behind an engine Event, or None (pointer moves, drag moves/ends).

    Event contract:  Event("gesture", {"id": gesture_id, "pos": (nx, ny) | None})  for discrete
    hand gestures; continuous ones keep their kinds ("drag_start" -> fist, "scroll" -> two_finger);
    head.py still emits Event("head", "next_app"|"prev_app"|"sleep") and gaze.py
    Event("gaze", "top-left"|...)."""
    k, v = ev.kind, ev.value
    if k == "gesture":
        return v["id"]
    if k == "drag_start":
        return "fist"
    if k == "scroll":
        return "two_finger"
    if k == "head":
        return HEAD_GESTURE.get(v)
    if k == "gaze":
        return "gaze_" + str(v).replace("-", "_")
    return None
