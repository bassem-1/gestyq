import json

import cameras
import config
from cameras import Device, choose, default_device, is_continuity, status_text

FACETIME = Device("CAM-BUILTIN", "FaceTime HD Camera", builtin=True)
PHONE = Device("CAM-PHONE-1", "Alex’s iPhone Camera", continuity=True)
PHONE_B = Device("CAM-PHONE-2", "Work iPhone Camera", continuity=True)
USB = Device("USB-1", "Logitech C920")


def test_classification_by_name():
    assert is_continuity("Alex’s iPhone Camera") and is_continuity("Work iPhone Camera") and is_continuity("My iPad Camera")
    assert not is_continuity("FaceTime HD Camera") and not is_continuity("Logitech C920") and not is_continuity(None)
    assert cameras.is_builtin("FaceTime HD Camera") and cameras.is_builtin("x", "AVCaptureDeviceTypeBuiltInWideAngleCamera")
    assert not cameras.is_builtin("Work iPhone Camera", "AVCaptureDeviceTypeExternal")


def test_auto_is_the_builtin_camera_whatever_the_order():
    for order in ([PHONE, PHONE_B, FACETIME], [FACETIME, PHONE], [PHONE, USB, FACETIME]):
        assert choose(order, {}) == (FACETIME, "")
    assert default_device([PHONE, USB]) == USB                   # no built-in: a real camera before a phone
    assert default_device([PHONE]) == PHONE and default_device([]) is None


def test_choice_is_by_unique_id_not_position_or_name():
    cfg = {"camera_id": PHONE_B.uid, "camera_name": "something else"}
    assert choose([PHONE, PHONE_B, FACETIME], cfg) == (PHONE_B, "")
    assert choose([FACETIME, PHONE_B], cfg) == (PHONE_B, "")     # same device, different position
    two = [Device("A", "iPhone Camera", continuity=True), Device("B", "iPhone Camera", continuity=True)]
    assert choose(two, {"camera_id": "B"})[0].uid == "B"           # identical names stay apart


def test_missing_camera_falls_back_with_a_lowercase_note_and_never_edits_the_saved_choice():
    cfg = {"camera_id": PHONE.uid, "camera_name": "Alex’s iPhone Camera"}
    dev, note = choose([FACETIME], cfg)
    assert dev == FACETIME and note == "alex’s iphone camera not found · using facetime hd camera"
    assert note == note.lower() and cfg == {"camera_id": PHONE.uid, "camera_name": "Alex’s iPhone Camera"}
    assert choose([FACETIME, PHONE], cfg)[0] == PHONE              # phone is back: chosen again
    assert choose([], cfg)[0] is None and "not found" in choose([], cfg)[1]
    assert status_text(note, dev) == note and status_text("", dev) == "facetime hd camera" and status_text("", None) == "no camera"


def test_a_name_only_choice_from_an_old_file_still_works():
    assert choose([FACETIME, USB], {"camera_name": "Logitech C920"}) == (USB, "")
    assert choose([FACETIME], {"camera_name": "Logitech C920"})[0] == FACETIME


def test_migration_resets_an_iphone_choice_to_auto(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"config_version": 3, "camera_name": "Alex’s iPhone Camera", "camera_id": "x"}))
    c = config.load(str(p))
    assert c["camera_name"] is None and c["camera_id"] is None and c["config_version"] == config.CONFIG_VERSION


def test_migration_keeps_a_real_choice_and_leaves_new_files_alone(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"config_version": 5, "camera_name": "Logitech C920"}))
    assert config.load(str(p))["camera_name"] == "Logitech C920"
    p.write_text(json.dumps({"config_version": config.CONFIG_VERSION, "camera_id": "I", "camera_name": "Work iPhone Camera"}))
    c = config.load(str(p))                                         # chosen on purpose after the fix: kept
    assert (c["camera_id"], c["camera_name"]) == ("I", "Work iPhone Camera")
