import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import replay
from synth import PEACE, make_hand


def write(path, frames):
    with open(path, "w") as f:
        for fr in frames:
            f.write(json.dumps(fr) + "\n")


def frame(i, right=None, left=None):
    hands = []
    for lms, label in ((right, "Left"), (left, "Right")):          # unmirrored: user's right hand is 'Left'
        if lms is not None:
            hands.append({"lms": [list(p) for p in lms], "label": label, "conf": 0.9})
    return {"t": 100.0 + i / 30, "aspect": 1.0, "hands": hands}


def test_replay_summary_and_table(tmp_path):
    fr, i = [], 0
    def add(**kw):
        nonlocal i
        fr.append(frame(i, **kw)); i += 1
    for _ in range(30):
        add(right=make_hand("right", x=0.4))
    for _ in range(6):
        add(right=make_hand("right", x=0.4, pinch=1.0))              # one click
    for _ in range(10):
        add(right=make_hand("right", x=0.4))
    for k in range(20):
        add(left=make_hand("left", x=0.7, y=0.6 - 0.01 * k, curl=PEACE))      # scroll
    p = tmp_path / "s.jsonl"
    write(p, fr)
    p.write_text(p.read_text() + "\n")                              # trailing blank line is fine
    lines = []
    res = replay.replay(replay.load_frames(str(p)), out=lines.append)
    assert res["frames"] == len(fr)
    assert res["events"]["gesture:pinch"] == 1 and res["events"]["scroll"] >= 3
    assert res["events"]["move"] >= 1 and not res["events"]["gesture:swipe_left"]
    assert len(lines) == len(fr)
    assert any("R raw=" in l and "pinch=0.0" in l and "RC" in l for l in lines)       # pinch raw+confirmed shown
    assert any("L raw=scroll" in l and "f=eecc" in l for l in lines)
    assert "gesture:pinch" in replay.format_summary(res)


def test_replay_cli_quiet(tmp_path, capsys):
    p = tmp_path / "s.jsonl"
    write(p, [frame(i, right=make_hand("right", x=0.4)) for i in range(5)])
    assert replay.main([str(p), "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "5 frames" in out and "raw=" not in out
