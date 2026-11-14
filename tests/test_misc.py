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
    pure = ["bindings", "filters", "tracking", "gestures", "head", "gaze", "events", "config", "state", "login"]
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
