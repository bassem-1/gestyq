"""Phase-0 tool for air-writing: feed a recording (the window's record button) through the GestureEngine with the
canvas active and print the letters it would type.

    python3 tools/write_replay.py <file.jsonl> [--trace]

Tune write.still / write.pause / the templates on real sessions of the alphabet in point pose. Pure Python.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config                      # noqa: E402
from gestures import GestureEngine  # noqa: E402
from replay import load_frames      # noqa: E402
from tracking import HandObs        # noqa: E402


def run(frames, cfg=None, trace=False):
    """-> [(t, text)] typed ("\\n" = enter, " " = space, "<-" = delete)."""
    cfg = cfg or config.load()
    eng = GestureEngine(cfg)
    eng.write_active = True
    out = []
    for fr in frames:
        eng.aspect = fr.get("aspect", 16 / 9)
        obs = [HandObs([tuple(p) for p in h["lms"]], h["label"], h["conf"]) for h in fr["hands"]]
        for e in eng.update(obs, fr["t"]):
            if e.kind == "write":
                out.append((fr["t"], "\n" if e.value["op"] == "enter" else e.value["text"]))
            elif e.kind == "gesture" and e.value["id"].startswith("write_flick"):
                out.append((fr["t"], " " if e.value["id"].endswith("right") else "<-"))
        if trace and eng.ink and eng.ink["result"] and eng.ink["result"]["t"] == fr["t"]:
            print(f"{fr['t']:.2f} result {eng.ink['result']['char']} alt={eng.ink['result']['alt']} "
                  f"why={eng.ink['result']['why']}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--trace", action="store_true")
    a = ap.parse_args()
    got = run(load_frames(a.file), trace=a.trace)
    for t, s in got:
        print(f"{t:8.2f}  {s!r}")
    print("typed:", "".join(s if s != "<-" else "" for _, s in got))
