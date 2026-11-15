import ast
import glob
import json
import os
import time

import config
import login
from state import SharedState
from ui import theme

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_config_defaults_roundtrip_and_shipped_json(tmp_path):
    p = tmp_path / "c.json"
    config.save(config.DEFAULTS, str(p))
    assert config.load(str(p)) == config.DEFAULTS
    p.write_text(json.dumps({"hand": {"pinch_on": 0.2}, "pointer_speed": 3}))
    c = config.load(str(p))
    assert c["hand"]["pinch_on"] == 0.2 and c["hand"]["pinch_off"] == config.DEFAULTS["hand"]["pinch_off"]
    assert c["pointer_speed"] == 3
    assert config.load(str(tmp_path / "missing.json")) == config.DEFAULTS
    with open(os.path.join(ROOT, "config.json")) as f:
        assert json.load(f) == config.DEFAULTS


def test_spec_defaults():
    h = config.DEFAULTS["hand"]
    assert (h["pinch_on"], h["pinch_off"], h["pinch_frames"]) == (0.35, 0.55, 2)
    assert h["loss_grace"] == 0.15 and h["fist_hold"] == 0.15 and h["click_lookback"] == 0.12
    assert h["ext_deg"] == 155 and h["curl_deg"] == 125 and h["vote_frames"] == 3
    assert h["dwell_time"] == 0.9 and h["dwell_radius"] == 12 and h["dwell_rearm"] == 40
    assert config.DEFAULTS["dwell_click"] is False and config.DEFAULTS["eye_corners"] is False
    assert config.DEFAULTS["swap_hands"] is False and config.DEFAULTS["launch_at_login"] is False


def test_bindings_default_and_old_actions_key_dropped():
    import bindings
    assert config.DEFAULTS["bindings"] == bindings.DEFAULT_BINDINGS and "actions" not in config.DEFAULTS


def test_old_config_migrates_actions_and_drops_old_tuned_defaults(tmp_path):
    p = tmp_path / "old.json"
    p.write_text(json.dumps({
        "pointer_speed": 4, "gadget_origin": [3, 4],
        "hand": {"pinch_on": 0.25, "ext_deg": 160.0, "pinch_frames": 3, "scroll_gain": 1800},
        "actions": {"gaze:top-left": "launchpad", "gaze:top-right": "no_such_action", "gaze:bottom-left": "key:1"}}))
    c = config.load(str(p))
    assert "actions" not in c and c["pointer_speed"] == 4 and c["gadget_origin"] == [3, 4]
    assert c["bindings"]["gaze_top_left"] == "launchpad"                       # known id: migrated
    assert c["bindings"]["gaze_top_right"] == config.DEFAULTS["bindings"]["gaze_top_right"]    # unknown: default
    assert c["bindings"]["gaze_bottom_left"] == config.DEFAULTS["bindings"]["gaze_bottom_left"]
    h = c["hand"]
    assert h["pinch_on"] == config.DEFAULTS["hand"]["pinch_on"] and h["ext_deg"] == config.DEFAULTS["hand"]["ext_deg"]
    assert h["scroll_gain"] == config.DEFAULTS["hand"]["scroll_gain"] and h["pinch_frames"] == 3
    # a user's explicit binding wins over the legacy map
    p.write_text(json.dumps({"actions": {"gaze:top-left": "launchpad"}, "bindings": {"gaze_top_left": "none"}}))
    assert config.load(str(p))["bindings"]["gaze_top_left"] == "none"


def test_user_settings_path_env_override_and_first_load_migration(tmp_path, monkeypatch):
    user = tmp_path / "support" / "config.json"
    shipped = tmp_path / "repo.json"
    monkeypatch.setenv("GESTYQ_CONFIG", str(user))
    assert config.user_path() == str(user) and config.USER_PATH != str(user)
    monkeypatch.setattr(config, "PATH", str(shipped))
    shipped.write_text(json.dumps(config.DEFAULTS))             # untouched shipped defaults: nothing to migrate
    assert config.load() == config.DEFAULTS and not user.exists()
    shipped.write_text(json.dumps({"launch_at_login": True, "gadget_origin": [9, 9]}))
    c = config.load()                                           # customised repo file: copied once
    assert c["launch_at_login"] is True and user.exists()
    assert json.load(open(user))["gadget_origin"] == [9, 9]
    shipped.write_text(json.dumps({"launch_at_login": False}))
    assert config.load()["launch_at_login"] is True             # the user file now wins
    c["pointer_speed"] = 4
    config.save(c)                                              # default path = user file
    assert json.load(open(user))["pointer_speed"] == 4 and json.load(open(shipped)) == {"launch_at_login": False}


def test_tests_are_isolated_from_the_real_settings_file():
    assert config.user_path() != config.USER_PATH and "gestyq-test-" in config.user_path()


def test_debounced_saves_once_after_quiet_period():
    calls = []
    d = config.Debounced(lambda: calls.append(1), 0.05)
    for _ in range(5):
        d.poke()
    time.sleep(0.2)
    assert calls == [1]
    d.poke()
    d.flush()
    assert calls == [1, 1]
    d.flush()
    assert calls == [1, 1]


def test_login_plist(tmp_path):
    p = str(tmp_path / "LaunchAgents" / "x.plist")
    login.set_enabled(True, "/opt/gestyq", p)
    assert login.is_enabled(p)
    import plistlib
    d = plistlib.load(open(p, "rb"))
    assert d["Label"] == "com.gestyq.app" and d["ProgramArguments"][-1] == "/opt/gestyq/run.sh"
    login.set_enabled(False, "/opt/gestyq", p)
    assert not login.is_enabled(p)
    login.set_enabled(True, "/opt/gestyq", p, app="/Applications/gestyq.app")
    d = plistlib.load(open(p, "rb"))
    assert d["ProgramArguments"] == ["/usr/bin/open", "-a", "/Applications/gestyq.app", "--args", "--background"]


def test_state_starts_off_and_counts_pulses():
    s = SharedState()
    assert s.get()["enabled"] is False and s.get()["caption"] == "paused"
    s.pulse(); s.pulse()
    assert s.get()["pulse_n"] == 2
    s.command("x", 1)
    assert s.pop_commands() == [("x", 1)] and s.pop_commands() == []


def test_theme_tokens():
    assert theme.RED == (1.0, 26 / 255, 46 / 255)
    assert (theme.A_FG, theme.A_FG2, theme.A_DIM, theme.A_LINE, theme.A_WASH) == (1.0, 0.55, 0.32, 0.16, 0.08)
    assert (theme.PAD, theme.ROW, theme.RADIUS, theme.CONTROL_RADIUS) == (16, 32, 10, 6)
    assert (theme.SIZE_STATE, theme.SIZE_TITLE, theme.SIZE_SMALL) == (22, 13, 11)
    assert theme.POPOVER_W == 300 and theme.GADGET == 140 and theme.GADGET_RADIUS == 22


def test_ui_sources_follow_the_rules():
    forbidden = ("NSShadow", "setShadow", "NSGradient", "whiteColor", "grayColor", "NSImage.imageWithSystemSymbolName",
                 "systemSymbol", "pyautogui", "lightGray", "darkGray", "systemBlue", "controlAccent")
    for path in glob.glob(os.path.join(ROOT, "ui", "*.py")) + [os.path.join(ROOT, "app.py")]:
        src = open(path).read()
        for word in forbidden:
            assert word not in src, (path, word)
        tree = ast.parse(src)
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body \
                    and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                docs.add(id(node.body[0].value))
        for node in ast.walk(tree):
            # user-visible strings (anything with a space) are lowercase
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs \
                    and " " in node.value.strip():
                assert node.value == node.value.lower(), (path, node.value)


def test_no_overlay_and_no_pyautogui_anywhere():
    names = [os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.py"))]
    assert "overlay.py" not in names
    for p in glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "ui", "*.py")):
        if p.endswith("test_misc.py"):
            continue
        assert "pyautogui" not in open(p).read(), p
    assert "pyautogui" not in open(os.path.join(ROOT, "requirements.txt")).read()


def test_pure_modules_have_no_platform_imports():
    pure = ["bindings", "filters", "tracking", "gestures", "head", "gaze", "events", "config", "state", "login",
            "desktop", "roi", "preview", "wake"]
    banned = ("cv2", "mediapipe", "AppKit", "Quartz", "Foundation", "objc", "AVFoundation", "ApplicationServices")
    for m in pure:
        tree = ast.parse(open(os.path.join(ROOT, m + ".py")).read())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            for name in mods:
                assert name.split(".")[0] not in banned, (m, name)






def test_customised_detection_conf_survives_upgrade(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"config_version": 2, "hand": {"min_detection_conf": 0.8}}))
    assert config.load(str(p))["hand"]["min_detection_conf"] == 0.8


def test_old_hand_defaults_are_dropped_on_load(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"config_version": 2, "hand": {
        "min_detection_conf": 0.6, "min_presence_conf": 0.6, "tile_move": 0.15, "pinch_on": 0.2}}))
    h = config.load(str(p))["hand"]
    assert h["min_detection_conf"] == 0.7 and h["min_presence_conf"] == 0.7
    d = config.DEFAULTS["hand"]
    assert h["tile_move"] == d["tile_move"] and h["pinch_on"] == 0.2


def test_v4_defaults_move_to_hd_camera_and_palm_units(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"config_version": 4, "camera": {"width": 1280, "height": 720, "fps": 24},
                             "hand": {"tile_move": 0.15, "tile_gap": 0.3}}))
    c, d = config.load(str(p)), config.DEFAULTS
    assert (c["camera"]["width"], c["camera"]["height"]) == (1920, 1080) and c["camera"]["fps"] == 24
    assert c["hand"]["tile_move"] == d["hand"]["tile_move"] and c["hand"]["tile_gap"] == 0.3


def test_v6_migration_to_relative_pointer_flicks_and_the_new_zoom(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"config_version": 6, "pointer_speed": 3, "hand": {
        "swipe_dist": 1.15, "swipe_min": 0.04, "swipe_time": 0.5, "swipe_cooldown": 0.7, "swipe_grace": 0.3,
        "far_face_frac": 0.16, "near_face_frac": 0.20, "buffer_window": 0.3, "pinch_on": 0.2}}))
    c, d = config.load(str(p)), config.DEFAULTS
    assert config.CONFIG_VERSION == 7 and c["config_version"] == 7
    assert c["pointer_mode"] == "relative" and c["hot_corners"] is True and c["pointer_speed"] == 3
    h = c["hand"]
    assert not [k for k in h if k.startswith("swipe_")]                  # the open-palm swipe is gone
    assert (h["far_face_frac"], h["near_face_frac"], h["buffer_window"]) == (0.22, 0.27, 0.45)
    assert h["pinch_on"] == 0.2                                           # a real customisation survives
    # a deliberately tuned zoom threshold from an old file is NOT the old default, so it also survives
    p.write_text(json.dumps({"config_version": 6, "hand": {"far_face_frac": 0.12}}))
    assert config.load(str(p))["hand"]["far_face_frac"] == 0.12
    # the chosen mode is kept
    p.write_text(json.dumps({"config_version": 7, "pointer_mode": "absolute", "hot_corners": False}))
    c = config.load(str(p))
    assert c["pointer_mode"] == "absolute" and c["hot_corners"] is False


def test_new_defaults_numbers():
    h = config.DEFAULTS["hand"]
    assert config.DEFAULTS["pointer_mode"] == "relative" and config.DEFAULTS["hot_corners"] is True
    assert (h["far_face_frac"], h["near_face_frac"]) == (0.22, 0.27)
    assert h["flick_speed"] == 10.0 and h["flick_travel"] == 0.8 and h["flick_time"] == 0.25
    assert h["flick_gap"] == 0.35 and h["flick_return"] == 0.6
    assert h["full_every"] == 5 and config.DEFAULTS["camera"]["zoom_process_width"] == 1280
    assert sorted(config.GAIN_SCALE) == [1, 2, 3, 4] and config.GAIN_SCALE[2] == 1.0


def test_wake_decision_and_motion():
    import wake
    ok = dict(asleep=True, enabled=True, moving=True, fired=False, now=10.0, last_wake=-1e9)
    assert wake.should_wake(**ok)
    assert not wake.should_wake(**{**ok, "asleep": False})                 # awake: nothing to do
    assert not wake.should_wake(**{**ok, "enabled": False})                # gestyq off: never
    assert not wake.should_wake(**{**ok, "moving": False})                 # a still hand does not wake it ...
    assert wake.should_wake(**{**ok, "moving": False, "fired": True})      # ... a gesture does
    assert not wake.should_wake(**{**ok, "last_wake": 9.0})                # at most once per 2 s
    assert wake.should_wake(**{**ok, "last_wake": 7.9})
    assert wake.hands_moved([(0.5, 0.5)], [(0.5, 0.52)]) and not wake.hands_moved([(0.5, 0.5)], [(0.5005, 0.5)])
    assert not wake.hands_moved([(0.5, 0.5)], []) and wake.hands_moved([], [(0.5, 0.5)])


def test_corner_guard_math():
    from desktop import guard_corners
    one = [(0.0, 0.0, 1920.0, 1080.0)]
    assert guard_corners((0.0, 0.0), one) == (4.0, 4.0)
    assert guard_corners((1919.0, 1079.0), one) == (1915.0, 1075.0)
    assert guard_corners((2.0, 1078.0), one) == (4.0, 1075.0)
    assert guard_corners((0.0, 500.0), one) == (0.0, 500.0)                 # edges stay reachable
    assert guard_corners((900.0, 0.0), one) == (900.0, 0.0)
    assert guard_corners((5.0, 5.0), one) == (5.0, 5.0)
    two = [(0.0, 0.0, 1680.0, 1050.0), (1680.0, -569.0, 1920.0, 1080.0)]       # the second display's corners too
    assert guard_corners((3599.0, -569.0), two) == (3595.0, -565.0)
    assert guard_corners((1680.0, 0.0), two) == (1680.0, 0.0)                  # the seam between displays is no corner of its own
